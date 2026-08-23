#!/usr/bin/env python3
"""Verify or restore an exact wiki backup into an absent directory."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from check_document_reachability import document_reachability_problems
from check_schema_doc_parity import schema_doc_parity_problems
from export_wiki import verify_backup_archive


TRUSTED_SCRIPTS = Path(__file__).resolve().parent


class RestoreError(RuntimeError):
    """A backup could not be restored safely and exactly."""


def _install_directory_exclusive(source: Path, destination: Path) -> None:
    """Atomically rename a directory while refusing a concurrently created target."""
    library = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        operation = library.renamex_np
        operation.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        result = operation(source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        operation = library.renameat2
        operation.argtypes = (
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
        )
        result = operation(-100, source_bytes, -100, destination_bytes, 0x1)  # RENAME_NOREPLACE
    else:
        raise RestoreError("this platform lacks an atomic no-replace directory rename")
    if result != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise RestoreError(f"restore destination appeared before install: {destination}")
        raise RestoreError(f"atomic restore install failed: {os.strerror(error)}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Verify or restore an exact wiki backup.")
    commands = result.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="Verify archive safety and exact members.")
    verify.add_argument("archive", type=Path)
    restore = commands.add_parser("restore", help="Restore into an absent destination directory.")
    restore.add_argument("archive", type=Path)
    restore.add_argument("destination", type=Path)
    return result


def verify_restored_wiki_tree(root: Path, manifest: dict[str, object]) -> list[str]:
    """Recheck restored bytes and run trusted deterministic repository checks."""
    errors: list[str] = []
    members = manifest.get("members")
    if not isinstance(members, list):
        return ["backup manifest members are unavailable"]
    expected_paths = []
    for member in members:
        if not isinstance(member, dict) or not isinstance(member.get("path"), str):
            errors.append("backup manifest contains an invalid restored member")
            continue
        relative = member["path"]
        expected_paths.append(relative)
        path = root.joinpath(*relative.split("/"))
        if not path.is_file() or path.is_symlink():
            errors.append(f"restored member is missing or unsafe: {relative}")
            continue
        content = path.read_bytes()
        if len(content) != member.get("size") or hashlib.sha256(content).hexdigest() != member.get("sha256"):
            errors.append(f"restored member does not match manifest: {relative}")
    actual_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    )
    if actual_paths != expected_paths:
        errors.append("restored member set does not match manifest")
    if errors:
        return errors

    checks = (
        (
            "Tier 1",
            [sys.executable, str(TRUSTED_SCRIPTS / "lint.py"), "--tier1", "--restored-tree"],
        ),
        ("capture ledger", [sys.executable, str(TRUSTED_SCRIPTS / "validate_capture_runs.py")]),
    )
    for label, command in checks:
        proc = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            errors.append(f"restored {label} check failed: {detail}")
    errors.extend(
        f"restored schema parity check failed: {problem}"
        for problem in schema_doc_parity_problems(root, use_git=False)
    )
    errors.extend(
        f"restored document reachability check failed: {problem}"
        for problem in document_reachability_problems(root)
    )
    return errors


def restore_backup_archive(archive: Path, destination: Path) -> None:
    """Verify, stage, reverify, and atomically install one absent restore tree."""
    archive = archive.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise RestoreError(f"restore destination must be absent: {destination}")
    parent = destination.parent
    if not parent.is_dir() or parent.is_symlink():
        raise RestoreError(f"restore destination parent must be an existing real directory: {parent}")
    destination = parent.resolve(strict=True) / destination.name
    manifest, errors = verify_backup_archive(archive)
    if manifest is None:
        raise RestoreError("backup verification failed: " + "; ".join(errors))

    staged = Path(tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=parent))
    try:
        with zipfile.ZipFile(archive) as zf:
            members = manifest["members"]
            assert isinstance(members, list)
            for member in members:
                assert isinstance(member, dict) and isinstance(member.get("path"), str)
                relative = member["path"]
                target = staged.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(relative, "r") as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        restored_errors = verify_restored_wiki_tree(staged, manifest)
        if restored_errors:
            raise RestoreError("; ".join(restored_errors))
        _install_directory_exclusive(staged, destination)
    except Exception:
        if staged.exists():
            shutil.rmtree(staged)
        raise


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "verify":
            manifest, errors = verify_backup_archive(args.archive)
            if manifest is None:
                raise RestoreError("; ".join(errors))
            print(f"Backup verified: {args.archive}")
            print(f"Members: {len(manifest['members'])}")
            return 0
        restore_backup_archive(args.archive, args.destination)
        print(f"Wiki restored: {args.destination}")
        return 0
    except (OSError, RestoreError, RuntimeError, zipfile.BadZipFile) as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["RestoreError", "restore_backup_archive", "verify_restored_wiki_tree"]
