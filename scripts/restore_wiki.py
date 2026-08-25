#!/usr/bin/env python3
"""Verify or restore an exact wiki backup into an absent directory."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from _durable_files import fsync_directory
from check_document_reachability import document_reachability_problems
from export_wiki import verify_backup_archive
from wiki_schema_vocabularies import SchemaVocabularyError, load_wiki_schema_vocabularies


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
    """Recheck restored bytes and modes, then run trusted repository checks."""
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
        if manifest.get("schema_version") in {2, 3}:
            expected_mode = member.get("mode")
            actual_mode = stat.S_IMODE(path.stat().st_mode)
            if actual_mode != expected_mode:
                errors.append(
                    f"restored member mode does not match manifest: {relative}"
                )
    actual_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    )
    if actual_paths != expected_paths:
        errors.append("restored member set does not match manifest")
    if manifest.get("schema_version") == 3:
        directories = manifest.get("directories")
        if not isinstance(directories, list):
            errors.append("backup manifest directories are unavailable")
        else:
            expected_directories = []
            for directory in directories:
                if not isinstance(directory, dict) or not isinstance(directory.get("path"), str):
                    errors.append("backup manifest contains an invalid restored directory")
                    continue
                relative = directory["path"]
                expected_directories.append(relative)
                path = root.joinpath(*relative.split("/"))
                if not path.is_dir() or path.is_symlink():
                    errors.append(f"restored directory is missing or unsafe: {relative}")
                    continue
                if stat.S_IMODE(path.stat().st_mode) != directory.get("mode"):
                    errors.append(
                        f"restored directory mode does not match manifest: {relative}"
                    )
            actual_directories = sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_dir() and not path.is_symlink()
            )
            if actual_directories != expected_directories:
                errors.append("restored directory set does not match manifest")
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
    try:
        load_wiki_schema_vocabularies(root / "scripts/schema-vocabularies.json")
    except SchemaVocabularyError as exc:
        errors.append(f"restored schema vocabulary check failed: {exc}")
    errors.extend(
        f"restored document reachability check failed: {problem}"
        for problem in document_reachability_problems(root)
    )
    return errors


def _fsync_restored_regular_file(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def restore_backup_archive(
    archive: Path,
    destination: Path,
    *,
    fault: Callable[[str], None] | None = None,
) -> None:
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
            if manifest.get("schema_version") == 3:
                directories = manifest.get("directories")
                assert isinstance(directories, list)
                for directory in directories:
                    assert isinstance(directory, dict) and isinstance(directory.get("path"), str)
                    staged.joinpath(*directory["path"].split("/")).mkdir(
                        parents=True, exist_ok=True
                    )
            for member in members:
                assert isinstance(member, dict) and isinstance(member.get("path"), str)
                relative = member["path"]
                target = staged.joinpath(*relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(relative, "r") as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                if manifest.get("schema_version") in {2, 3}:
                    permission_mode = member.get("mode")
                    assert isinstance(permission_mode, int)
                else:
                    archived_mode = (zf.getinfo(relative).external_attr >> 16) & 0xFFFF
                    permission_mode = (
                        stat.S_IMODE(archived_mode) if archived_mode else 0o600
                    )
                os.chmod(target, permission_mode)
                _fsync_restored_regular_file(target)
            if manifest.get("schema_version") == 3:
                for directory in sorted(
                    manifest["directories"],
                    key=lambda item: len(item["path"].split("/")),
                    reverse=True,
                ):
                    os.chmod(
                        staged.joinpath(*directory["path"].split("/")),
                        directory["mode"],
                    )
            staged_directories = [
                path for path in staged.rglob("*")
                if path.is_dir() and not path.is_symlink()
            ]
            for directory in sorted(
                [*staged_directories, staged],
                key=lambda path: len(path.relative_to(staged).parts),
                reverse=True,
            ):
                fsync_directory(directory)
        restored_errors = verify_restored_wiki_tree(staged, manifest)
        if restored_errors:
            raise RestoreError("; ".join(restored_errors))
        if fault is not None:
            fault("before_install")
        _install_directory_exclusive(staged, destination)
        if fault is not None:
            fault("after_install")
        fsync_directory(parent)
        if fault is not None:
            fault("after_parent_fsync")
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
