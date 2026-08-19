#!/usr/bin/env python3
"""Regression evals for rotate_log.py.

The rotator is allowed to mutate wiki/log.md, but only when explicitly run. These
cases exercise it in temporary repos so the live wiki is never touched.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import rotate_log  # noqa: E402
from eval_lib import Results  # noqa: E402


ROTATE = REPO_ROOT / "scripts" / "rotate_log.py"
LINT = REPO_ROOT / "scripts" / "lint.py"
LINT_FIXTURE = REPO_ROOT / "scripts" / "fixtures" / "wiki-lint"

ROTATION_DATE = "2026-06-27"


def write_log(root: Path, entries: list[str], header: str | None = None) -> None:
    header = header or (
        "# Wiki Log\n"
        "\n"
        "Append-only, oldest first.\n"
        "\n"
        "---\n"
        "\n"
    )
    path = root / "wiki" / "log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "".join(entries), encoding="utf-8")


def plain_entry(day: int, title: str, extra: str = "") -> str:
    body = extra or f"Body line for plain entry {day}.\n"
    return (
        f"## 2026-01-{day:02d} | {title}\n"
        f"Action: fixture {day}.\n"
        f"{body}"
        "Verification: fixture.\n"
        "\n"
    )


def bracket_entry(day: int, title: str, extra: str = "") -> str:
    body = extra or f"Body line for bracket entry {day}.\n"
    return (
        f"## [2026-01-{day:02d}] {title}\n"
        f"Action: fixture {day}.\n"
        f"{body}"
        "Verification: fixture.\n"
        "\n"
    )


def run_rotate(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROTATE), "--date", ROTATION_DATE, *args],
        cwd=root,
        text=True,
        capture_output=True,
    )


def parse_entries_from_text(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    _, entries = rotate_log.parse_log(lines)
    return ["".join(entry.lines) for entry in entries]


def archive_payload(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "\n---\n\n"
    assert marker in text, "archive header marker missing"
    payload = text.split(marker, 1)[1]
    if payload.endswith("\n---\n"):
        payload += "\n"
    return payload


def live_original_entries(root: Path) -> list[str]:
    entries = parse_entries_from_text((root / "wiki" / "log.md").read_text(encoding="utf-8"))
    original_entries = [entry for entry in entries if "maintenance | Log rotation" not in entry]
    if original_entries and original_entries[-1].endswith("\n---\n\n"):
        original_entries[-1] = original_entries[-1][:-len("\n---\n\n")]
    return original_entries


def with_temp_root(fn) -> None:
    with tempfile.TemporaryDirectory(prefix="wiki-rotate-eval-") as td:
        fn(Path(td))


results = Results()
record = results.record


def case_rotates_losslessly(root: Path) -> None:
    entries = [
        plain_entry(1, "bootstrap", "Body date 2025-10-28 must not name archive.\n"),
        plain_entry(2, "second"),
        bracket_entry(3, "ingest | third"),
        bracket_entry(4, "maintenance | fourth", "Future body date 2026-12-31 must not name archive.\n"),
        bracket_entry(5, "promotion | fifth"),
        bracket_entry(6, "query | sixth"),
        bracket_entry(7, "ingest | seventh"),
        bracket_entry(8, "lint"),
    ]
    write_log(root, entries)
    original_entries = parse_entries_from_text((root / "wiki" / "log.md").read_text(encoding="utf-8"))
    target = 35

    proc = run_rotate(root, "--target-lines", str(target))
    archive_files = sorted((root / "archive" / "wiki-log").glob("*.md"))
    archive_entries = parse_entries_from_text(archive_payload(archive_files[0]))
    kept_entries = live_original_entries(root)
    live_line_count = len((root / "wiki" / "log.md").read_text(encoding="utf-8").splitlines())

    record("rotate-exits-zero", proc.returncode == 0, proc.stderr.strip())
    record("rotates-under-target", live_line_count <= target, f"{live_line_count} > {target}")
    record("archive-created-on-header-dates",
           len(archive_files) == 1
           and archive_files[0].name.startswith("2026-01-01-to-")
           and "2025-10-28" not in archive_files[0].name
           and "2026-12-31" not in archive_files[0].name,
           f"archive files: {[p.name for p in archive_files]}")
    record("archive-has-human-header",
           archive_files and "Rotated Wiki Log" in archive_files[0].read_text(encoding="utf-8"),
           "archive header missing")
    record("live-log-has-pointer",
           "Archived entries:" in (root / "wiki" / "log.md").read_text(encoding="utf-8"),
           "live log pointer missing")
    record("live-log-has-rotation-entry",
           "maintenance | Log rotation" in (root / "wiki" / "log.md").read_text(encoding="utf-8"),
           "rotation entry missing")
    record("payload-conserved",
           original_entries == archive_entries + kept_entries,
           "original entries were not exactly partitioned across archive and live log")

    before_second = {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.md"))
    }
    second = run_rotate(root, "--target-lines", str(target))
    after_second = {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*.md"))
    }
    record("second-run-noop",
           second.returncode == 0 and before_second == after_second and "No rotation needed" in second.stdout,
           f"stdout={second.stdout!r} stderr={second.stderr!r}")


with_temp_root(case_rotates_losslessly)


def case_dry_run_no_write(root: Path) -> None:
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    write_log(root, entries)
    before = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    proc = run_rotate(root, "--dry-run", "--target-lines", "30")
    after = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    record("dry-run-no-write",
           proc.returncode == 0 and before == after and not (root / "archive").exists(),
           f"stdout={proc.stdout!r} stderr={proc.stderr!r}")


with_temp_root(case_dry_run_no_write)


def case_under_target_noop(root: Path) -> None:
    write_log(root, [plain_entry(1, "small"), bracket_entry(2, "small | two")])
    before = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    proc = run_rotate(root, "--target-lines", "80")
    after = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    record("under-target-left-untouched",
           proc.returncode == 0 and before == after and "No rotation needed" in proc.stdout,
           f"stdout={proc.stdout!r} stderr={proc.stderr!r}")


with_temp_root(case_under_target_noop)


def case_target_validation(root: Path) -> None:
    write_log(root, [plain_entry(i, f"entry {i}") for i in range(1, 8)])
    before = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    bad_target = rotate_log.LOG_ROTATION_WARN_LINES - rotate_log.MIN_ROTATION_HEADROOM_LINES
    proc = run_rotate(root, "--target-lines", str(bad_target))
    after = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    record("target-at-headroom-rejected",
           proc.returncode != 0 and before == after and "must be below" in proc.stderr,
           f"stdout={proc.stdout!r} stderr={proc.stderr!r}")


with_temp_root(case_target_validation)


def case_newest_entry_floor(root: Path) -> None:
    huge_body = "".join(f"Newest line {i}.\n" for i in range(40))
    write_log(root, [plain_entry(1, "old"), bracket_entry(2, "huge newest", huge_body)])
    before = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    proc = run_rotate(root, "--target-lines", "20")
    after = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    record("newest-entry-floor-refuses-impossible-cut",
           proc.returncode != 0 and before == after and not (root / "archive").exists(),
           f"stdout={proc.stdout!r} stderr={proc.stderr!r}")


with_temp_root(case_newest_entry_floor)


def selected_path_is_embedded(root: Path, archive_path: Path) -> bool:
    """Both planned live references must name the selected archive."""
    relative = archive_path.relative_to(root).as_posix()
    live = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    return f"-> {relative}." in live and f" to {relative}." in live


def seed_base_archive(root: Path, entries: list[str]) -> tuple[Path, str]:
    write_log(root, entries)
    proc = run_rotate(root, "--target-lines", "30")
    archive_files = sorted((root / "archive" / "wiki-log").glob("*.md"))
    assert proc.returncode == 0 and len(archive_files) == 1, proc.stderr
    base = archive_files[0]
    return base, base.read_text(encoding="utf-8")


def case_identical_base_reused(root: Path) -> None:
    """An interrupted same-date run reuses the identical base archive."""
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    base, archive_before = seed_base_archive(root, entries)
    write_log(root, entries)
    plan = rotate_log.build_log_rotation_plan(root, 30, ROTATION_DATE)
    recover = run_rotate(root, "--target-lines", "30")
    archive_files = sorted((root / "archive" / "wiki-log").glob("*.md"))
    record(
        "identical-base-selected-in-build-plan",
        plan.archive_path == base,
        f"planned={plan.archive_path} expected={base}",
    )
    record(
        "identical-base-rerun-completes-idempotently",
        recover.returncode == 0
        and archive_files == [base]
        and base.read_text(encoding="utf-8") == archive_before
        and selected_path_is_embedded(root, base),
        f"stdout={recover.stdout!r} stderr={recover.stderr!r} files={archive_files}",
    )


with_temp_root(case_identical_base_reused)


def case_distinct_content_gets_suffix_and_reruns(root: Path) -> None:
    """Distinct same-range content takes -2; an interrupted rerun reuses it."""
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    base, base_before = seed_base_archive(root, entries)
    write_log(root, entries)
    expected = base.with_name(f"{base.stem}-2.md")
    plan = rotate_log.build_log_rotation_plan(root, 30, "2026-06-28")
    later = subprocess.run(
        [sys.executable, str(ROTATE), "--date", "2026-06-28", "--target-lines", "30"],
        cwd=root, text=True, capture_output=True,
    )
    record(
        "distinct-content-selects-minus-2-in-build-plan",
        plan.archive_path == expected,
        f"planned={plan.archive_path} expected={expected}",
    )
    record(
        "distinct-content-writes-suffix-with-selected-live-paths",
        later.returncode == 0
        and expected.is_file()
        and base.read_text(encoding="utf-8") == base_before
        and expected.read_text(encoding="utf-8") != base_before
        and selected_path_is_embedded(root, expected),
        f"stdout={later.stdout!r} stderr={later.stderr!r}",
    )

    suffix_before = expected.read_text(encoding="utf-8") if expected.exists() else ""
    archive_before = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((root / "archive" / "wiki-log").glob("*.md"))
    }
    write_log(root, entries)
    recovery_plan = rotate_log.build_log_rotation_plan(root, 30, "2026-06-28")
    recovery = subprocess.run(
        [sys.executable, str(ROTATE), "--date", "2026-06-28", "--target-lines", "30"],
        cwd=root, text=True, capture_output=True,
    )
    archive_after = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((root / "archive" / "wiki-log").glob("*.md"))
    }
    record(
        "identical-suffixed-rerun-reuses-minus-2",
        recovery_plan.archive_path == expected
        and recovery.returncode == 0
        and expected.read_text(encoding="utf-8") == suffix_before
        and archive_after == archive_before
        and selected_path_is_embedded(root, expected),
        f"planned={recovery_plan.archive_path}; stdout={recovery.stdout!r}; "
        f"stderr={recovery.stderr!r}; files={sorted(archive_after)}",
    )


with_temp_root(case_distinct_content_gets_suffix_and_reruns)


def case_identical_later_suffix_beats_earlier_gap(root: Path) -> None:
    """An identical -3 is reused even when the unused -2 name is available."""
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    base, _base_before = seed_base_archive(root, entries)
    write_log(root, entries)
    candidate_plan = rotate_log.build_log_rotation_plan(root, 30, "2026-06-28")
    assert candidate_plan.archive_lines is not None
    matching_suffix = base.with_name(f"{base.stem}-3.md")
    matching_suffix.write_text("".join(candidate_plan.archive_lines), encoding="utf-8")

    selected = rotate_log.build_log_rotation_plan(root, 30, "2026-06-28")
    proc = subprocess.run(
        [sys.executable, str(ROTATE), "--date", "2026-06-28", "--target-lines", "30"],
        cwd=root, text=True, capture_output=True,
    )
    gap = base.with_name(f"{base.stem}-2.md")
    record(
        "identical-existing-suffix-wins-over-earlier-free-name",
        selected.archive_path == matching_suffix
        and proc.returncode == 0
        and not gap.exists()
        and selected_path_is_embedded(root, matching_suffix),
        f"planned={selected.archive_path}; stdout={proc.stdout!r}; stderr={proc.stderr!r}",
    )


with_temp_root(case_identical_later_suffix_beats_earlier_gap)


def case_first_unused_gap_selected(root: Path) -> None:
    """With distinct base and -3 content, the first free suffix is -2."""
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    base, _base_before = seed_base_archive(root, entries)
    occupied_later = base.with_name(f"{base.stem}-3.md")
    occupied_later.write_text("different pre-existing archive\n", encoding="utf-8")
    write_log(root, entries)
    expected = base.with_name(f"{base.stem}-2.md")
    plan = rotate_log.build_log_rotation_plan(root, 30, "2026-06-29")
    proc = subprocess.run(
        [sys.executable, str(ROTATE), "--date", "2026-06-29", "--target-lines", "30"],
        cwd=root, text=True, capture_output=True,
    )
    record(
        "first-unused-suffix-gap-is-selected",
        plan.archive_path == expected
        and proc.returncode == 0
        and expected.is_file()
        and occupied_later.read_text(encoding="utf-8") == "different pre-existing archive\n"
        and selected_path_is_embedded(root, expected),
        f"planned={plan.archive_path}; stdout={proc.stdout!r}; stderr={proc.stderr!r}",
    )


with_temp_root(case_first_unused_gap_selected)


def case_minus_3_selected_after_occupied_minus_2(root: Path) -> None:
    """When base and -2 are distinct, the next deterministic slot is -3."""
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    base, _base_before = seed_base_archive(root, entries)
    occupied = base.with_name(f"{base.stem}-2.md")
    occupied.write_text("different pre-existing minus-2 archive\n", encoding="utf-8")
    write_log(root, entries)
    expected = base.with_name(f"{base.stem}-3.md")
    plan = rotate_log.build_log_rotation_plan(root, 30, "2026-06-29")
    proc = subprocess.run(
        [sys.executable, str(ROTATE), "--date", "2026-06-29", "--target-lines", "30"],
        cwd=root, text=True, capture_output=True,
    )
    record(
        "occupied-minus-2-selects-minus-3",
        plan.archive_path == expected
        and proc.returncode == 0
        and expected.is_file()
        and occupied.read_text(encoding="utf-8")
            == "different pre-existing minus-2 archive\n"
        and selected_path_is_embedded(root, expected),
        f"planned={plan.archive_path}; stdout={proc.stdout!r}; stderr={proc.stderr!r}",
    )


with_temp_root(case_minus_3_selected_after_occupied_minus_2)


def case_no_recognized_headers(root: Path) -> None:
    write_log(root, ["Free prose with no entry headers at all.\n" for _ in range(40)])
    before = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    proc = run_rotate(root, "--target-lines", "30")
    after = (root / "wiki" / "log.md").read_text(encoding="utf-8")
    record("no-recognized-headers-refused",
           proc.returncode != 0 and before == after
           and "no recognized log entry headers" in proc.stderr
           and not (root / "archive").exists(),
           f"stdout={proc.stdout!r} stderr={proc.stderr!r}")


with_temp_root(case_no_recognized_headers)


def case_archive_ignored_by_lint(root: Path) -> None:
    shutil.copytree(LINT_FIXTURE / "wiki", root / "wiki")
    shutil.copytree(LINT_FIXTURE / "scripts", root / "scripts")
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    write_log(root, entries)
    proc = run_rotate(root, "--target-lines", "30")
    lint = subprocess.run(
        [sys.executable, str(LINT), "--tier1"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    record("archive-ignored-by-tier1-lint",
           proc.returncode == 0 and lint.returncode == 0,
           f"rotate stderr={proc.stderr!r}; lint stdout={lint.stdout!r}; lint stderr={lint.stderr!r}")


with_temp_root(case_archive_ignored_by_lint)


def case_transaction_fault_recovery(root: Path) -> None:
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    write_log(root, entries)
    original = (root / "wiki/log.md").read_bytes()
    plan = rotate_log.build_log_rotation_plan(root, 30, ROTATION_DATE)
    assert plan.archive_path is not None
    try:
        rotate_log.apply_log_rotation_plan(
            root,
            plan,
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop")) if event == "after_target:0" else None,
        )
    except RuntimeError:
        faulted = True
    else:
        faulted = False
    split_guarded = plan.archive_path.exists() and (root / "wiki/log.md").read_bytes() == original
    recovery = rotate_log.recover_all(root)
    clean, reports = rotate_log.transaction_status(root)
    record(
        "archive-installed-fault-recovers-original-pair",
        faulted and split_guarded and clean and not plan.archive_path.exists()
        and (root / "wiki/log.md").read_bytes() == original
        and any("rolled back" in message for message in recovery),
        f"recovery={recovery} reports={reports}",
    )


with_temp_root(case_transaction_fault_recovery)


def case_transaction_forward_recovery(root: Path) -> None:
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    write_log(root, entries)
    plan = rotate_log.build_log_rotation_plan(root, 30, ROTATION_DATE)
    assert plan.archive_path is not None and plan.archive_lines is not None and plan.live_lines is not None
    try:
        rotate_log.apply_log_rotation_plan(
            root,
            plan,
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop")) if event == "after_target:1" else None,
        )
    except RuntimeError:
        pass
    recovery = rotate_log.recover_all(root)
    clean, reports = rotate_log.transaction_status(root)
    record(
        "all-targets-installed-fault-finishes-forward",
        clean
        and plan.archive_path.read_text(encoding="utf-8") == "".join(plan.archive_lines)
        and (root / "wiki/log.md").read_text(encoding="utf-8") == "".join(plan.live_lines)
        and any("forward" in message for message in recovery),
        f"recovery={recovery} reports={reports}",
    )


with_temp_root(case_transaction_forward_recovery)


def case_concurrent_live_edit_conflicts(root: Path) -> None:
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    write_log(root, entries)
    plan = rotate_log.build_log_rotation_plan(root, 30, ROTATION_DATE)
    third_party = b"third-party live log edit\n"

    def mutate(event: str) -> None:
        if event == "after_target:0":
            (root / "wiki/log.md").write_bytes(third_party)

    try:
        rotate_log.apply_log_rotation_plan(root, plan, fault=mutate)
    except rotate_log.RotationError:
        conflicted = True
    else:
        conflicted = False
    clean, reports = rotate_log.transaction_status(root)
    record(
        "concurrent-live-log-edit-is-preserved-as-conflict",
        conflicted and not clean and (root / "wiki/log.md").read_bytes() == third_party
        and any("CONFLICTED" in report for report in reports),
        f"reports={reports}",
    )


with_temp_root(case_concurrent_live_edit_conflicts)


def case_reused_archive_guard_conflicts(root: Path) -> None:
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    archive, _ = seed_base_archive(root, entries)
    write_log(root, entries)
    original_log = (root / "wiki/log.md").read_bytes()
    plan = rotate_log.build_log_rotation_plan(root, 30, ROTATION_DATE)
    assert plan.archive_path == archive and plan.archive_preimage is not None
    third_party = b"third-party archive edit\n"

    def mutate(event: str) -> None:
        if event == "after_journal:COMMITTING":
            archive.write_bytes(third_party)

    try:
        rotate_log.apply_log_rotation_plan(root, plan, fault=mutate)
    except rotate_log.RotationError:
        conflicted = True
    else:
        conflicted = False
    clean, reports = rotate_log.transaction_status(root)
    record(
        "reused-archive-concurrent-change-is-guarded-conflict",
        conflicted
        and not clean
        and archive.read_bytes() == third_party
        and (root / "wiki/log.md").read_bytes() == original_log
        and any("CONFLICTED" in report for report in reports),
        f"reports={reports}",
    )


with_temp_root(case_reused_archive_guard_conflicts)


def case_dry_run_blocks_on_unfinished(root: Path) -> None:
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    write_log(root, entries)
    plan = rotate_log.build_log_rotation_plan(root, 30, ROTATION_DATE)
    try:
        rotate_log.apply_log_rotation_plan(
            root,
            plan,
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop")) if event == "after_journal:COMMITTING" else None,
        )
    except RuntimeError:
        pass
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }
    proc = run_rotate(root, "--dry-run", "--target-lines", "30")
    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }
    record(
        "dry-run-reports-recovery-required-with-zero-writes",
        proc.returncode != 0 and "recovery required" in proc.stderr and before == after,
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}",
    )


with_temp_root(case_dry_run_blocks_on_unfinished)


def case_subprocess_kill_after_archive(root: Path) -> None:
    entries = [plain_entry(i, f"entry {i}") for i in range(1, 8)]
    write_log(root, entries)
    original = (root / "wiki/log.md").read_bytes()
    child_code = """
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
import rotate_log
root = Path(sys.argv[1])
plan = rotate_log.build_log_rotation_plan(root, 30, '2026-06-27')
rotate_log.apply_log_rotation_plan(root, plan, fault=lambda event: os._exit(94) if event == 'after_target:0' else None)
"""
    proc = subprocess.run(
        [sys.executable, "-c", child_code, str(root), str(REPO_ROOT / "scripts")],
        cwd=root, capture_output=True, text=True,
    )
    recovery = rotate_log.recover_all(root)
    clean, reports = rotate_log.transaction_status(root)
    record(
        "process-kill-after-archive-recovers-losslessly",
        proc.returncode == 94 and clean and (root / "wiki/log.md").read_bytes() == original
        and not list((root / "archive/wiki-log").glob("*.md")),
        f"recovery={recovery} reports={reports}",
    )


with_temp_root(case_subprocess_kill_after_archive)


sys.exit(results.finish())
