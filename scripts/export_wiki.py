#!/usr/bin/env python3
"""Build and verify a wiki export zip.

The export includes gitignored raw sources, but excludes local scratch,
deliverables, git internals, and private local settings. Upload is optional and
only runs when an explicit rclone destination is provided.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

from _file_transactions import transaction_status
from wiki_backup_receipt import (
    DEFAULT_BACKUP_RECEIPT_PATH,
    BackupReceiptError,
    record_verified_backup,
)


DEFAULT_EXCLUDES = (
    ".git/",
    ".agents/",
    "tmp/",
    "deliverables/",
    ".claude/worktrees/",
)
DEFAULT_EXCLUDE_FILES = {
    ".claude/settings.local.json",
    ".env",
    "scripts/backup-receipt.json",
}
REQUIRED_FILES = {
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTEXT.md",
    "LICENSE",
    "README.md",
    "REFERENCES.md",
}
REQUIRED_PREFIXES = (
    ".claude/commands/",
    ".agents/skills/",
    ".github/workflows/",
    "raw/",
    "scripts/",
    "wiki/",
    "workflows/",
)
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build and verify a complete wiki export zip.")
    p.add_argument("--date", default=date.today().isoformat(), help="Date stamp for the export filename.")
    p.add_argument("--output-dir", default="tmp", help="Directory for the export zip.")
    p.add_argument("--repo-root", default=".", help="Repository root to export.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List how many files would be exported without writing the zip.",
    )
    p.add_argument(
        "--upload-target",
        help=("Optional rclone destination for the verified zip, for example "
              "gdrive:wiki-exports/wiki-export.zip. Local-only by default."),
    )
    p.add_argument(
        "--init-rclone-drive",
        metavar="REMOTE",
        help=("Create this rclone Google Drive remote if it is missing before "
              "uploading. Requires --upload-target to use the same remote."),
    )
    p.add_argument(
        "--rclone-bin",
        default="rclone",
        help="rclone executable used for optional upload and first-run auth.",
    )
    p.add_argument(
        "--receipt-path",
        type=Path,
        default=DEFAULT_BACKUP_RECEIPT_PATH,
        help=("Local gitignored receipt to update only after a remote copy verifies. "
              "Relative paths are resolved from --repo-root."),
    )
    return p


def should_exclude(rel: str) -> bool:
    if rel in DEFAULT_EXCLUDE_FILES:
        return True
    if rel.endswith(".DS_Store"):
        return True
    if rel.startswith(".agents/skills/"):
        return False
    return any(rel.startswith(prefix) for prefix in DEFAULT_EXCLUDES)


def export_files(
    repo_root: Path,
    output: Path | None = None,
    local_state: Path | None = None,
) -> list[Path]:
    """Return exportable files, excluding the archive and local receipt state."""
    resolved_output = output.resolve() if output is not None else None
    resolved_local_state = local_state.resolve() if local_state is not None else None
    files: list[Path] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if resolved_output is not None and path.resolve() == resolved_output:
            continue
        if resolved_local_state is not None and path.resolve() == resolved_local_state:
            continue
        rel = path.relative_to(repo_root).as_posix()
        if should_exclude(rel):
            continue
        files.append(path)
    return files


def find_symlinks(repo_root: Path) -> list[Path]:
    """Return every symlink, including broken links, under the export root."""
    return sorted(path for path in repo_root.rglob("*") if path.is_symlink())


def zip_path(repo_root: Path, output_dir: str, stamp: str) -> Path:
    out_dir = repo_root / output_dir
    return out_dir / f"wiki-export-{stamp}.zip"


def _validated_export_date(value: str) -> str:
    if not ISO_DATE_RE.fullmatch(value):
        raise ValueError(f"--date {value!r} is not a valid YYYY-MM-DD date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"--date {value!r} is not a valid YYYY-MM-DD date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"--date {value!r} is not a valid YYYY-MM-DD date")
    return value


def build_zip(repo_root: Path, output: Path, files: list[Path]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(repo_root).as_posix())


def validate_names(names: list[str]) -> list[str]:
    errors: list[str] = []
    name_set = set(names)
    for required in sorted(REQUIRED_FILES):
        if required not in name_set:
            errors.append(f"archive does not contain {required}")
    for prefix in REQUIRED_PREFIXES:
        if not any(name.startswith(prefix) for name in names):
            errors.append(f"archive does not contain {prefix}")
    for name in names:
        if should_exclude(name):
            errors.append(f"archive contains excluded path {name}")
    return errors


def verify_zip(
    output: Path,
    expected_count: int,
    output_rel: str | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not output.exists():
        return False, [f"{output} was not created"]
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        corrupt = zf.testzip()
    if corrupt:
        errors.append(f"corrupt zip member: {corrupt}")
    if output_rel is not None and output_rel in names:
        errors.append(f"archive unexpectedly contains itself ({output_rel})")
    errors.extend(validate_names(names))
    if len(names) != expected_count:
        errors.append(f"archive file count {len(names)} did not match expected {expected_count}")
    return not errors, errors


def rclone_remote_name(target: str) -> str | None:
    if ":" not in target:
        return None
    remote = target.split(":", 1)[0].strip()
    return remote or None


def run_rclone(rclone_bin: str, args: list[str]) -> tuple[bool, str, list[str]]:
    cmd = [rclone_bin, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, "", [f"{rclone_bin!r} was not found; install rclone before upload"]
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        return False, proc.stdout, [f"{' '.join(cmd)} failed: {detail}"]
    return True, proc.stdout, []


def run_rclone_interactive(rclone_bin: str, args: list[str]) -> tuple[bool, list[str]]:
    cmd = [rclone_bin, *args]
    try:
        proc = subprocess.run(cmd, check=False)
    except FileNotFoundError:
        return False, [f"{rclone_bin!r} was not found; install rclone before upload"]
    if proc.returncode != 0:
        return False, [f"{' '.join(cmd)} failed with exit {proc.returncode}"]
    return True, []


def list_rclone_remotes(rclone_bin: str) -> tuple[set[str] | None, list[str]]:
    ok, stdout, errors = run_rclone(rclone_bin, ["listremotes"])
    if not ok:
        return None, errors
    remotes = {
        line.strip().rstrip(":")
        for line in stdout.splitlines()
        if line.strip()
    }
    return remotes, []


def ensure_google_drive_remote(remote: str, rclone_bin: str) -> tuple[bool, list[str]]:
    remotes, errors = list_rclone_remotes(rclone_bin)
    if remotes is None:
        return False, errors
    if remote in remotes:
        return True, []

    print(
        f"rclone remote {remote!r} was not found; starting Google Drive auth.",
        flush=True,
    )
    print(
        "Follow the browser or terminal prompts from rclone. Credentials stay "
        "in your local rclone config, not in this repo.",
        flush=True,
    )
    ok, errors = run_rclone_interactive(
        rclone_bin, ["config", "create", remote, "drive", "config_is_local=true"]
    )
    if not ok:
        return False, errors

    remotes, errors = list_rclone_remotes(rclone_bin)
    if remotes is None:
        return False, errors
    if remote not in remotes:
        return False, [f"rclone remote {remote!r} was not created"]
    return True, []


def parse_rclone_lsl_size(stdout: str) -> tuple[int | None, list[str]]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return None, [f"expected one remote listing line, got {len(lines)}"]
    first = lines[0].split(maxsplit=1)[0]
    try:
        return int(first), []
    except ValueError:
        return None, [f"remote listing did not start with a byte count: {lines[0]}"]


def parse_rclone_md5(stdout: str) -> tuple[str | None, list[str]]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return None, [f"expected one remote md5sum line, got {len(lines)}"]
    value = lines[0].split(maxsplit=1)[0].lower()
    if len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
        return None, [f"remote md5sum did not start with an MD5 hash: {lines[0]}"]
    return value, []


def _stream_file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload_rclone(
    output: Path,
    target: str,
    rclone_bin: str = "rclone",
    init_drive_remote: str | None = None,
) -> tuple[bool, list[str]]:
    if not output.exists():
        return False, [f"{output} was not created"]
    remote = rclone_remote_name(target)
    if remote is None:
        return False, ["--upload-target must be an rclone path like remote:path/file.zip"]
    if init_drive_remote and init_drive_remote != remote:
        return False, [
            f"--init-rclone-drive {init_drive_remote!r} does not match "
            f"--upload-target remote {remote!r}"
        ]
    if init_drive_remote:
        ok, errors = ensure_google_drive_remote(init_drive_remote, rclone_bin)
        if not ok:
            return False, errors

    expected_size = output.stat().st_size
    expected_md5 = _stream_file_md5(output)
    ok, _, errors = run_rclone(rclone_bin, ["copyto", str(output), target])
    if not ok:
        return False, errors
    ok, stdout, errors = run_rclone(rclone_bin, ["lsl", target])
    if not ok:
        return False, errors
    remote_size, parse_errors = parse_rclone_lsl_size(stdout)
    if parse_errors:
        return False, parse_errors
    if remote_size != expected_size:
        return False, [
            f"remote size {remote_size} did not match local size {expected_size}"
        ]
    ok, stdout, errors = run_rclone(rclone_bin, ["md5sum", target])
    if not ok:
        return False, errors
    remote_md5, parse_errors = parse_rclone_md5(stdout)
    if parse_errors:
        return False, parse_errors
    if remote_md5 != expected_md5:
        return False, [f"remote md5 {remote_md5} did not match local md5 {expected_md5}"]
    return True, []


def main() -> int:
    args = parser().parse_args()
    try:
        stamp = _validated_export_date(args.date)
    except ValueError as exc:
        print(f"Error: {exc}.", file=sys.stderr)
        return 2
    if args.init_rclone_drive and not args.upload_target:
        print("Error: --init-rclone-drive requires --upload-target.", file=sys.stderr)
        return 1
    if args.upload_target:
        remote = rclone_remote_name(args.upload_target)
        if remote is None:
            print(
                "Error: --upload-target must be an rclone path like "
                "remote:path/file.zip.",
                file=sys.stderr,
            )
            return 1
        if args.init_rclone_drive and args.init_rclone_drive != remote:
            print(
                f"Error: --init-rclone-drive {args.init_rclone_drive!r} does not "
                f"match --upload-target remote {remote!r}.",
                file=sys.stderr,
            )
            return 1
    repo_root = Path(args.repo_root).resolve()
    transactions_clean, transaction_reports = transaction_status(repo_root)
    if not transactions_clean:
        print("Wiki export refused: .wiki-transactions/ is nonclean:", file=sys.stderr)
        for report in transaction_reports:
            print(f"- {report}", file=sys.stderr)
        return 1

    symlinks = find_symlinks(repo_root)
    if symlinks:
        print("Wiki export refused: the tree contains symlink(s):", file=sys.stderr)
        for link in symlinks:
            print(f"- {link.relative_to(repo_root)}", file=sys.stderr)
        return 1
    output = zip_path(repo_root, args.output_dir, stamp)
    receipt_path = args.receipt_path
    if not receipt_path.is_absolute():
        receipt_path = repo_root / receipt_path
    if receipt_path.resolve() == output.resolve():
        print("Error: --receipt-path must differ from the export archive path.", file=sys.stderr)
        return 2
    files = export_files(repo_root, output, receipt_path)
    try:
        output_rel = output.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        output_rel = None

    if args.dry_run:
        names = [path.relative_to(repo_root).as_posix() for path in files]
        errors = validate_names(names)
        print(f"Export dry run: {len(files)} file(s) would be written to {output}")
        print("Required export coverage: " + ("yes" if not errors else "no"))
        if args.upload_target:
            print(f"Upload target (dry run only): {args.upload_target}")
        for error in errors:
            print(f"- {error}")
        return 0 if not errors else 1

    build_zip(repo_root, output, files)
    ok, errors = verify_zip(output, len(files), output_rel)
    if not ok:
        print("Wiki export verification failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Wiki export created: {output}")
    print(f"Files included: {len(files)}")
    print(f"Size bytes: {output.stat().st_size}")
    if args.upload_target:
        ok, errors = upload_rclone(
            output,
            args.upload_target,
            args.rclone_bin,
            args.init_rclone_drive,
        )
        if not ok:
            print("Wiki export upload failed:")
            for error in errors:
                print(f"- {error}")
            print(f"Local zip remains: {output}")
            return 1
        print(f"Upload verified: {args.upload_target}")
        try:
            receipt = record_verified_backup(output, args.upload_target, receipt_path)
        except (BackupReceiptError, OSError) as exc:
            print(f"Verified upload receipt failed: {exc}", file=sys.stderr)
            return 1
        print(f"Backup receipt updated: {receipt_path}")
        print(f"Verified at: {receipt.verified_at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
