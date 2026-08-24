#!/usr/bin/env python3
"""Rotate wiki/log.md into archive/wiki-log/ when it grows past target size."""

from __future__ import annotations

import argparse
import hashlib
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from _wiki_parse import parse_log_entry_date
from _durable_files import DurableFileError, atomic_replace_bytes, read_regular_bytes
from wiki_lint_contract import LOG_ROTATION_WARN_LINES


DEFAULT_TARGET_LINES = 1500
MIN_ROTATION_HEADROOM_LINES = 25
LOG_PATH = Path("wiki/log.md")
ARCHIVE_DIR = Path("archive/wiki-log")


class RotationError(Exception):
    """A planned rotation would be unsafe or useless."""


@dataclass(frozen=True)
class Entry:
    date: str
    lines: list[str]


@dataclass(frozen=True)
class RotationPlan:
    no_op: bool
    before_lines: int
    after_lines: int
    target_lines: int
    archive_path: Path | None = None
    oldest: str = ""
    newest: str = ""
    moved_entries: int = 0
    kept_entries: int = 0
    archive_lines: list[str] | None = None
    live_lines: list[str] | None = None
    log_preimage: bytes | None = None
    log_preimage_sha256: str = ""
    log_mode: int = 0o644
    archive_preimage: bytes | None = None
    archive_preimage_sha256: str | None = None


def line_count(lines: list[str]) -> int:
    return len(lines)


def flatten(entries: list[Entry]) -> list[str]:
    out: list[str] = []
    for entry in entries:
        out.extend(entry.lines)
    return out


def parse_entry_date(line: str) -> str | None:
    # The header grammar is shared with lint.py via _wiki_parse, so the lint
    # check and the rotation cut points cannot drift.
    return parse_log_entry_date(line)


def parse_log(lines: list[str]) -> tuple[list[str], list[Entry]]:
    header_indices = [
        i for i, line in enumerate(lines)
        if parse_entry_date(line) is not None
    ]
    if not header_indices:
        raise RotationError("wiki/log.md has no recognized log entry headers")

    header = lines[:header_indices[0]]
    entries: list[Entry] = []
    for pos, start in enumerate(header_indices):
        end = header_indices[pos + 1] if pos + 1 < len(header_indices) else len(lines)
        entry_lines = lines[start:end]
        entry_date = parse_entry_date(entry_lines[0])
        if entry_date is None:
            raise RotationError(f"internal parser error at line {start + 1}")
        entries.append(Entry(entry_date, entry_lines))
    return header, entries


def archive_header(oldest: str, newest: str, rotation_date: str, moved_entries: int) -> list[str]:
    return [
        "# Rotated Wiki Log\n",
        "\n",
        "Source: wiki/log.md\n",
        f"Range: {oldest} to {newest}\n",
        f"Rotated: {rotation_date}\n",
        f"Entries: {moved_entries}\n",
        "\n",
        "Entries below are preserved from wiki/log.md in original order. This file has no frontmatter because archive/ is outside the wiki entity corpus.\n",
        "\n",
        "---\n",
        "\n",
    ]


def trim_terminal_blank_line(lines: list[str]) -> list[str]:
    if len(lines) >= 2 and lines[-2] == "---\n" and lines[-1] == "\n":
        return lines[:-1]
    return lines


def add_archive_pointer(header: list[str], archive_rel: Path, oldest: str, newest: str) -> list[str]:
    out = list(header)
    if out and out[-1].strip():
        out.append("\n")
    out.append(f"Archived entries: {oldest} to {newest} -> {archive_rel.as_posix()}.\n")
    out.append("\n")
    return out


def rotation_entry(
    *,
    rotation_date: str,
    archive_rel: Path,
    oldest: str,
    newest: str,
    moved_entries: int,
    kept_entries: int,
    before_lines: int,
    after_lines: int,
) -> list[str]:
    return [
        "\n",
        "---\n",
        "\n",
        f"## [{rotation_date}] maintenance | Log rotation\n",
        f"Archived range: {oldest} through {newest} to {archive_rel.as_posix()}.\n",
        f"Line delta: wiki/log.md {before_lines} lines -> {after_lines} lines.\n",
        f"Entries archived: {moved_entries}. Entries retained: {kept_entries}.\n",
        "Verification: rotate_log.py payload conservation check passed; rerun lint after rotation.\n",
    ]


def validate_target(target_lines: int) -> None:
    max_useful = LOG_ROTATION_WARN_LINES - MIN_ROTATION_HEADROOM_LINES
    if target_lines <= 0:
        raise RotationError("--target-lines must be positive")
    if target_lines >= max_useful:
        raise RotationError(
            f"--target-lines must be below {max_useful} so the rotation clears "
            f"the {LOG_ROTATION_WARN_LINES}-line lint threshold with headroom"
        )


def assert_payload_conserved(original: list[Entry], moved: list[Entry], kept: list[Entry]) -> None:
    original_payload = flatten(original)
    rotated_payload = flatten(moved) + flatten(kept)
    if original_payload != rotated_payload:
        raise RotationError("payload conservation failed: original log entries changed")


def _archive_candidate_index(path: Path, base_rel: Path) -> int | None:
    """Return deterministic slot 1/base, 2/-2, 3/-3, etc. for a path."""
    if path.name == base_rel.name:
        return 1
    prefix = f"{base_rel.stem}-"
    if not path.name.startswith(prefix) or path.suffix != ".md":
        return None
    raw_index = path.stem[len(prefix):]
    if not raw_index.isdigit():
        return None
    index = int(raw_index)
    return index if index >= 2 and raw_index == str(index) else None


def select_archive_path(root: Path, base_rel: Path, candidate_text: str) -> tuple[Path, bytes | None]:
    """Choose a non-overwriting archive path for already-rendered content.

    Interrupted runs recover by reusing the lowest-numbered base/suffixed file
    whose bytes already equal the candidate. If none match, choose the first
    unused deterministic slot (base, then -2, -3, ...). Selection happens in
    build_log_rotation_plan so the live pointer and maintenance entry render the real path.
    """
    archive_dir = root / base_rel.parent
    existing: dict[int, Path] = {}
    if archive_dir.exists():
        directory_info = archive_dir.lstat()
        if stat.S_ISLNK(directory_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode):
            raise RotationError(f"{base_rel.parent} exists but is not a directory")
        for path in archive_dir.iterdir():
            index = _archive_candidate_index(path, base_rel)
            if index is not None:
                existing[index] = path

    for index in sorted(existing):
        path = existing[index]
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RotationError(f"existing archive is not a single-link regular file: {path.relative_to(root)}")
            content = path.read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise RotationError(
                f"cannot compare existing archive {path.relative_to(root)}: {exc}"
            ) from exc
        if text == candidate_text:
            return path.relative_to(root), content

    index = 1
    while index in existing:
        index += 1
    if index == 1:
        return base_rel, None
    return base_rel.with_name(f"{base_rel.stem}-{index}.md"), None


def build_log_rotation_plan(root: Path, target_lines: int, rotation_date: str) -> RotationPlan:
    validate_target(target_lines)

    log_path = root / LOG_PATH
    if not log_path.exists():
        raise RotationError(f"{LOG_PATH} does not exist")

    try:
        log_info = log_path.lstat()
        if stat.S_ISLNK(log_info.st_mode) or not stat.S_ISREG(log_info.st_mode) or log_info.st_nlink != 1:
            raise RotationError(f"{LOG_PATH} must be a single-link regular file")
        log_preimage = log_path.read_bytes()
        original_lines = log_preimage.decode("utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError) as exc:
        raise RotationError(f"cannot read {LOG_PATH} once as UTF-8: {exc}") from exc
    before_count = line_count(original_lines)
    if before_count <= target_lines:
        return RotationPlan(
            no_op=True,
            before_lines=before_count,
            after_lines=before_count,
            target_lines=target_lines,
            log_preimage=log_preimage,
            log_preimage_sha256=hashlib.sha256(log_preimage).hexdigest(),
            log_mode=stat.S_IMODE(log_info.st_mode),
        )

    header, entries = parse_log(original_lines)
    if len(entries) < 2:
        raise RotationError(
            "cannot rotate under target without archiving the newest entry; "
            "wiki/log.md has fewer than two entries"
        )

    chosen: tuple[list[Entry], list[Entry]] | None = None
    for cut in range(1, len(entries)):
        moved = entries[:cut]
        kept = entries[cut:]
        if not kept:
            continue
        oldest = moved[0].date
        newest = moved[-1].date
        archive_rel = ARCHIVE_DIR / f"{oldest}-to-{newest}.md"
        new_header = add_archive_pointer(header, archive_rel, oldest, newest)
        after_without_rotation = new_header + flatten(kept)
        rotation_line_count = len(
            rotation_entry(
                rotation_date=rotation_date,
                archive_rel=archive_rel,
                oldest=oldest,
                newest=newest,
                moved_entries=len(moved),
                kept_entries=len(kept),
                before_lines=before_count,
                after_lines=0,
            )
        )
        after_count = line_count(after_without_rotation) + rotation_line_count
        if after_count <= target_lines:
            chosen = (moved, kept)
            break

    if chosen is None:
        raise RotationError(
            "cannot rotate under target while retaining the newest entry; "
            "choose a larger --target-lines value"
        )

    moved, kept = chosen
    assert_payload_conserved(entries, moved, kept)

    oldest = moved[0].date
    newest = moved[-1].date
    archive_lines = trim_terminal_blank_line(
        archive_header(oldest, newest, rotation_date, len(moved))
        + flatten(moved)
    )
    base_archive_rel = ARCHIVE_DIR / f"{oldest}-to-{newest}.md"
    archive_rel, archive_preimage = select_archive_path(
        root,
        base_archive_rel,
        "".join(archive_lines),
    )
    new_header = add_archive_pointer(header, archive_rel, oldest, newest)
    after_without_rotation = new_header + flatten(kept)
    rotation_line_count = len(
        rotation_entry(
            rotation_date=rotation_date,
            archive_rel=archive_rel,
            oldest=oldest,
            newest=newest,
            moved_entries=len(moved),
            kept_entries=len(kept),
            before_lines=before_count,
            after_lines=0,
        )
    )
    after_count = line_count(after_without_rotation) + rotation_line_count
    live_lines = (
        new_header
        + flatten(kept)
        + rotation_entry(
            rotation_date=rotation_date,
            archive_rel=archive_rel,
            oldest=oldest,
            newest=newest,
            moved_entries=len(moved),
            kept_entries=len(kept),
            before_lines=before_count,
            after_lines=after_count,
        )
    )

    if line_count(live_lines) != after_count:
        raise RotationError("internal line-count error while building rotation plan")

    return RotationPlan(
        no_op=False,
        before_lines=before_count,
        after_lines=after_count,
        target_lines=target_lines,
        archive_path=root / archive_rel,
        oldest=oldest,
        newest=newest,
        moved_entries=len(moved),
        kept_entries=len(kept),
        archive_lines=archive_lines,
        live_lines=live_lines,
        log_preimage=log_preimage,
        log_preimage_sha256=hashlib.sha256(log_preimage).hexdigest(),
        log_mode=stat.S_IMODE(log_info.st_mode),
        archive_preimage=archive_preimage,
        archive_preimage_sha256=(
            hashlib.sha256(archive_preimage).hexdigest()
            if archive_preimage is not None else None
        ),
    )


def apply_log_rotation_plan(
    root: Path,
    plan: RotationPlan,
    *,
    fault: Callable[[str], None] | None = None,
) -> list[str]:
    """Install archive then live log with guarded atomic single-file writes.

    If the process stops after the archive write, a rerun reuses those exact
    bytes and completes the log update without a duplicate archive.
    """
    if plan.no_op:
        return []
    if (
        plan.archive_path is None
        or plan.archive_lines is None
        or plan.live_lines is None
        or plan.log_preimage is None
    ):
        raise RotationError("internal error: write requested for incomplete plan")

    archive_bytes = "".join(plan.archive_lines).encode("utf-8")
    live_bytes = "".join(plan.live_lines).encode("utf-8")
    plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_rel = plan.archive_path.relative_to(root).as_posix()
    try:
        if fault is not None:
            fault("before_archive")
        if plan.archive_preimage is None:
            atomic_replace_bytes(
                plan.archive_path,
                archive_bytes,
                mode=0o644,
                expected_sha256=None,
            )
        elif plan.archive_preimage != archive_bytes:
            raise RotationError(
                f"selected archive preimage is not byte-identical: {archive_rel}"
            )
        if fault is not None:
            fault("after_archive")
        current_archive, _ = read_regular_bytes(plan.archive_path)
        if current_archive != archive_bytes:
            raise RotationError(f"archive changed before log install: {archive_rel}")
        if fault is not None:
            fault("before_log")
        atomic_replace_bytes(
            root / LOG_PATH,
            live_bytes,
            mode=plan.log_mode,
            expected_sha256=plan.log_preimage_sha256,
        )
        if fault is not None:
            fault("after_log")
    except DurableFileError as exc:
        raise RotationError(str(exc)) from exc
    if (root / LOG_PATH).read_bytes() != live_bytes:
        raise RotationError("installed live log failed byte verification")
    if plan.archive_path.read_bytes() != archive_bytes:
        raise RotationError("installed archive failed byte verification")
    return []


def print_plan(plan: RotationPlan, *, dry_run: bool) -> None:
    if plan.no_op:
        print(
            f"No rotation needed: {LOG_PATH} has {plan.before_lines} lines "
            f"against target {plan.target_lines}."
        )
        return

    action = "Would rotate" if dry_run else "Rotated"
    archive_rel = plan.archive_path.relative_to(Path.cwd()) if plan.archive_path else ARCHIVE_DIR
    print(f"{action} {LOG_PATH}: {plan.before_lines} lines -> {plan.after_lines} lines")
    print(f"Archive: {archive_rel}")
    print(f"Range: {plan.oldest} to {plan.newest}")
    print(f"Entries archived: {plan.moved_entries}; entries retained: {plan.kept_entries}")
    print(f"Target: {plan.target_lines}; lint threshold: {LOG_ROTATION_WARN_LINES}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Rotate wiki/log.md into archive/wiki-log/.")
    p.add_argument("--dry-run", action="store_true", help="Show the planned rotation without writing.")
    p.add_argument(
        "--target-lines",
        type=int,
        default=DEFAULT_TARGET_LINES,
        help=f"Maximum live log lines after rotation (default: {DEFAULT_TARGET_LINES}).",
    )
    p.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Rotation date for the maintenance entry (YYYY-MM-DD).",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        date.fromisoformat(args.date)
        root = Path.cwd().resolve()
        plan = build_log_rotation_plan(root, args.target_lines, args.date)
        if not args.dry_run:
            apply_log_rotation_plan(root, plan)
        print_plan(plan, dry_run=args.dry_run)
        return 0
    except ValueError:
        print("--date must be YYYY-MM-DD", file=sys.stderr)
        return 1
    except RotationError as exc:
        print(f"rotate_log.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
