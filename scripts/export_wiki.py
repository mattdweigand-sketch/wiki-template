#!/usr/bin/env python3
"""Build and verify a complete private backup of one local wiki tree."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator

from _durable_files import (
    anchored_mkdir, assert_directory_identity, directory_scope, pinned_parent,
    read_regular_bytes, stable_lock,
)
from _file_transactions import transaction_status
from _strict_json import DuplicateJsonKeyError, reject_duplicate_json_keys
from wiki_backup_receipt import (
    DEFAULT_BACKUP_RECEIPT_PATH,
    BackupReceiptError,
    record_verified_backup,
)


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
EXPORT_ARCHIVE_RE = re.compile(r"wiki-export-\d{4}-\d{2}-\d{2}\.zip\Z")
EXPORT_WORK_FILE_RE = re.compile(
    r"\.wiki-export-\d{4}-\d{2}-\d{2}\.zip\.(?:lock|[0-9a-f]{32}\.tmp)\Z"
)
BACKUP_MANIFEST_NAME = "BACKUP-MANIFEST.json"
BACKUP_MANIFEST_FIELDS = {
    "schema_version", "created_at", "members", "raw_artifact_manifest_sha256",
}
BACKUP_MANIFEST_FIELDS_V3 = BACKUP_MANIFEST_FIELDS | {"directories"}
BACKUP_MANIFEST_SCHEMA_VERSION = 3
SUPPORTED_BACKUP_MANIFEST_SCHEMA_VERSIONS = frozenset({1, 2, 3})
BACKUP_MEMBER_FIELDS_V1 = {"path", "size", "sha256"}
BACKUP_MEMBER_FIELDS_V2 = {"path", "size", "sha256", "mode"}
BACKUP_DIRECTORY_FIELDS_V3 = {"path", "mode"}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class VerifiedUpload:
    byte_count: int
    content_sha256: str


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build and verify a complete private wiki backup.")
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
        help=("Optional private rclone backup destination for the verified zip, "
              "for example gdrive:wiki-exports/wiki-export.zip. Local-only by default."),
    )
    p.add_argument(
        "--init-rclone-drive",
        metavar="REMOTE",
        help=("Create this rclone Google Drive remote if it is missing before "
              "copying the private backup. Requires --upload-target to use the same remote."),
    )
    p.add_argument(
        "--rclone-bin",
        default="rclone",
        help="rclone executable used for the optional private backup copy and first-run auth.",
    )
    p.add_argument(
        "--receipt-path",
        type=Path,
        default=DEFAULT_BACKUP_RECEIPT_PATH,
        help=("Local gitignored receipt to update only after a remote copy verifies. "
              "Relative paths are resolved from --repo-root."),
    )
    return p


def _export_entries(repo_root: Path, output: Path | None = None) -> Iterator[Path]:
    """Traverse the complete private tree, excluding generated export files."""
    def visit(directory: Path) -> Iterator[Path]:
        with pinned_parent(directory / ".inventory") as (parent_fd, _name):
            for name in sorted(os.listdir(parent_fd)):
                path = directory / name
                relative = path.relative_to(repo_root)
                if output is not None and path.absolute() == output.absolute():
                    continue
                metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                # Archive-shaped directory names still hold private backup data.
                if not stat.S_ISDIR(metadata.st_mode) and relative.parts[0] != "raw" and (
                    EXPORT_ARCHIVE_RE.fullmatch(name) or EXPORT_WORK_FILE_RE.fullmatch(name)
                ):
                    continue
                yield path
                if stat.S_ISDIR(metadata.st_mode):
                    yield from visit(path)
    with directory_scope(repo_root):
        yield from visit(repo_root)


def export_files(repo_root: Path, output: Path | None = None) -> list[Path]:
    """Inventory included regular files; unsafe included entries are errors."""
    files = []
    for path in _export_entries(repo_root, output):
        with pinned_parent(path) as (parent_fd, name):
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError(f"unsafe included backup member: {path.relative_to(repo_root)}")
        files.append(path)
    return sorted(files)


def find_symlinks(repo_root: Path, output: Path | None = None) -> list[Path]:
    """Return included links, including broken links, using the inventory policy."""
    links = []
    for path in _export_entries(repo_root, output):
        with pinned_parent(path) as (parent_fd, name):
            if stat.S_ISLNK(os.stat(name, dir_fd=parent_fd, follow_symlinks=False).st_mode):
                links.append(path)
    return sorted(links)


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


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def build_backup_manifest(repo_root: Path, files: list[Path]) -> dict[str, object]:
    """Build the canonical exact-member manifest for one export snapshot."""
    members = []
    for path in files:
        content, metadata = read_regular_bytes(path)
        assert content is not None and metadata is not None
        members.append({
            "path": path.relative_to(repo_root).as_posix(),
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "mode": stat.S_IMODE(metadata.st_mode),
        })
    members.sort(key=lambda member: str(member["path"]))
    raw_sha = next((m["sha256"] for m in members if m["path"] == "scripts/raw-artifacts.json"), None)
    directories = []
    # Complete template backups also preserve empty directories and local state.
    for path in _export_entries(repo_root):
        with pinned_parent(path) as (parent_fd, name):
            metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                with pinned_parent(path / ".directory-mode") as (directory_fd, _):
                    directories.append({
                        "path": path.relative_to(repo_root).as_posix(),
                        "mode": stat.S_IMODE(os.fstat(directory_fd).st_mode),
                    })
    directories.sort(key=lambda item: item["path"])
    return {
        "schema_version": BACKUP_MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "members": members,
        "directories": directories,
        "raw_artifact_manifest_sha256": raw_sha,
    }


@contextlib.contextmanager
def _archive_stream(path: Path) -> Iterator[BinaryIO]:
    with pinned_parent(path) as (parent_fd, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError(f"archive is not a single-link regular file: {path}")
            yield stream
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns
            ) or current.st_nlink != 1:
                raise ValueError(f"archive changed while being read: {path}")


def _stream_hashes(stream: BinaryIO) -> tuple[str, str]:
    md5, sha256 = hashlib.md5(), hashlib.sha256()
    stream.seek(0)
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        md5.update(chunk)
        sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def _archive_state(path: Path) -> tuple[int, str, int, int, int] | None:
    try:
        with _archive_stream(path) as stream:
            metadata = os.fstat(stream.fileno())
            _md5, sha256 = _stream_hashes(stream)
            return (metadata.st_size, sha256, stat.S_IMODE(metadata.st_mode), metadata.st_dev, metadata.st_ino)
    except FileNotFoundError:
        return None


@contextlib.contextmanager
def _export_directory_scope(repo_root: Path, output_parent: Path) -> Iterator[None]:
    """Create missing output components through opened, no-follow parents."""
    missing = []
    ancestor = output_parent.absolute()
    while True:
        try:
            ancestor.lstat()
            break
        except FileNotFoundError:
            missing.append(ancestor)
            ancestor = ancestor.parent
    with directory_scope(repo_root), directory_scope(ancestor):
        for directory in reversed(missing):
            try:
                anchored_mkdir(directory, mode=0o777)
            except FileExistsError:
                pass  # A participating publisher may have created it first.
            assert_directory_identity(directory)
        with directory_scope(output_parent):
            yield


def build_zip(
    repo_root: Path, output: Path, files: list[Path], *, require_restore_ready: bool = False,
) -> VerifiedUpload:
    """Validate a sibling candidate before atomically publishing one generation."""
    lock_path = output.with_name(f".{output.name}.lock")
    temporary = f".{output.name}.{uuid.uuid4().hex}.tmp"
    installed = False
    try:
        with _export_directory_scope(repo_root, output.parent), stable_lock(lock_path):
            expected = _archive_state(output)
            with pinned_parent(output) as (parent_fd, final_name):
                fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
                owned = os.fstat(fd)
                try:
                    with os.fdopen(fd, "w+b") as stream:
                        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                            for path in files:
                                content, metadata = read_regular_bytes(path)
                                assert content is not None and metadata is not None
                                info = zipfile.ZipInfo(path.relative_to(repo_root).as_posix())
                                info.compress_type = zipfile.ZIP_DEFLATED
                                info.external_attr = (stat.S_IFREG | stat.S_IMODE(metadata.st_mode)) << 16
                                zf.writestr(info, content)
                            info = zipfile.ZipInfo(BACKUP_MANIFEST_NAME)
                            info.compress_type = zipfile.ZIP_DEFLATED
                            info.external_attr = 0o100600 << 16
                            zf.writestr(info, _canonical_json_bytes(build_backup_manifest(repo_root, files)))
                        try:
                            output_rel = output.absolute().relative_to(repo_root.absolute()).as_posix()
                        except ValueError:
                            output_rel = None
                        stream.flush()
                        _md5, verified_sha256 = _stream_hashes(stream)
                        if require_restore_ready:
                            from restore_wiki import verify_backup_restore_readiness

                            with zipfile.ZipFile(stream) as zf:
                                errors = _backup_member_coverage_errors(zf.namelist(), len(files), output_rel)
                            if not errors:
                                errors = verify_backup_restore_readiness(stream)
                            if errors:
                                raise ValueError("backup restore readiness failed: " + "; ".join(errors))
                        else:
                            _manifest, errors = verify_backup_archive(stream)
                            if errors:
                                raise ValueError("backup verification failed: " + "; ".join(errors))
                        stream.flush()
                        os.fsync(stream.fileno())
                        _md5, sha256 = _stream_hashes(stream)
                        if sha256 != verified_sha256:
                            raise ValueError("candidate bytes changed during verification")
                        proof = VerifiedUpload(os.fstat(stream.fileno()).st_size, sha256)
                        assert_directory_identity(repo_root)
                        assert_directory_identity(output.parent)
                        if _archive_state(output) != expected:
                            raise ValueError("export destination changed before installation")
                        candidate = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
                        if (
                            not stat.S_ISREG(candidate.st_mode) or candidate.st_nlink != 1
                            or (candidate.st_dev, candidate.st_ino) != (owned.st_dev, owned.st_ino)
                        ):
                            raise ValueError("export candidate was replaced before installation")
                        os.replace(temporary, final_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                        installed = True
                        os.fsync(parent_fd)
                        actual = _archive_state(output)
                        if actual is None or actual[:2] != (proof.byte_count, proof.content_sha256):
                            raise ValueError("installed export identity differs from verified candidate")
                        return proof
                finally:
                    if not installed:
                        try:
                            remaining = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
                            if (remaining.st_dev, remaining.st_ino) == (owned.st_dev, owned.st_ino):
                                os.unlink(temporary, dir_fd=parent_fd)
                        except FileNotFoundError:
                            pass
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        phase = "after installation; new archive may be installed, durability/identity unconfirmed" if installed else "before installation; destination was not replaced by this export"
        raise ValueError(f"export failed {phase}: {exc}") from exc


def validate_names(names: list[str]) -> list[str]:
    errors: list[str] = []
    name_set = set(names)
    for required in sorted(REQUIRED_FILES):
        if required not in name_set:
            errors.append(f"archive does not contain {required}")
    for prefix in REQUIRED_PREFIXES:
        if not any(name.startswith(prefix) for name in names):
            errors.append(f"archive does not contain {prefix}")
    return errors


def _safe_backup_member_name(name: object) -> bool:
    if (
        not isinstance(name, str)
        or not name
        or name.endswith("/")
        or "\\" in name
        or "\x00" in name
        or re.match(r"^[A-Za-z]:", name)
    ):
        return False
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and path.as_posix() == name
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def verify_backup_archive(output: Path | BinaryIO) -> tuple[dict[str, object] | None, list[str]]:
    """Verify archive safety plus exact member paths, bytes, and permission modes."""
    errors: list[str] = []
    try:
        with (_archive_stream(output) if isinstance(output, Path) else contextlib.nullcontext(output)) as source, zipfile.ZipFile(source) as zf:
            infos = zf.infolist()
            names = [info.filename for info in infos]
            infos_by_name = {info.filename: info for info in infos}
            if len(names) != len(set(names)):
                errors.append("archive contains duplicate member names")
            unsafe = [name for name in names if not _safe_backup_member_name(name)]
            if unsafe:
                errors.append(f"archive contains unsafe member names: {unsafe}")
            casefolded = [name.casefold() for name in names]
            if len(casefolded) != len(set(casefolded)):
                errors.append("archive contains case-colliding member names")
            for info in infos:
                mode = (info.external_attr >> 16) & 0xFFFF
                file_type = mode & 0o170000
                if info.flag_bits & 0x1:
                    errors.append(f"archive member is encrypted: {info.filename}")
                if file_type not in {0, 0o100000}:
                    errors.append(f"archive contains symlink or special member: {info.filename}")
            if names.count(BACKUP_MANIFEST_NAME) != 1:
                errors.append("archive must contain exactly one BACKUP-MANIFEST.json")
                return None, errors
            manifest_bytes = zf.read(BACKUP_MANIFEST_NAME)
            try:
                manifest = json.loads(
                    manifest_bytes.decode("utf-8"),
                    object_pairs_hook=reject_duplicate_json_keys,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
                return None, [*errors, f"backup manifest is invalid JSON: {exc}"]
            if not isinstance(manifest, dict):
                errors.append("backup manifest must be an object")
                return None, errors
            if manifest_bytes != _canonical_json_bytes(manifest):
                errors.append("backup manifest is not canonical JSON")
            schema_version = manifest.get("schema_version")
            if (
                not isinstance(schema_version, int)
                or isinstance(schema_version, bool)
                or schema_version not in SUPPORTED_BACKUP_MANIFEST_SCHEMA_VERSIONS
            ):
                errors.append(
                    "backup manifest schema_version must be a supported integer"
                )
                return None, errors
            expected_manifest_fields = (
                BACKUP_MANIFEST_FIELDS_V3
                if schema_version == 3
                else BACKUP_MANIFEST_FIELDS
            )
            if set(manifest) != expected_manifest_fields:
                errors.append("backup manifest has missing or unknown fields")
                return None, errors
            member_fields = (
                BACKUP_MEMBER_FIELDS_V2
                if schema_version in {2, 3}
                else BACKUP_MEMBER_FIELDS_V1
            )
            created_at = manifest.get("created_at")
            if not isinstance(created_at, str):
                errors.append("backup manifest created_at must be a string")
            else:
                try:
                    datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                except ValueError:
                    errors.append("backup manifest created_at must be ISO-8601 parseable")
            members = manifest.get("members")
            if not isinstance(members, list):
                errors.append("backup manifest members must be a list")
                return None, errors
            member_paths: list[str] = []
            for index, member in enumerate(members):
                if not isinstance(member, dict) or set(member) != member_fields:
                    errors.append(f"backup manifest members[{index}] has invalid fields")
                    continue
                path = member.get("path")
                size = member.get("size")
                digest = member.get("sha256")
                permission_mode = member.get("mode")
                if not _safe_backup_member_name(path) or path == BACKUP_MANIFEST_NAME:
                    errors.append(f"backup manifest members[{index}].path is unsafe")
                    continue
                member_paths.append(path)
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    errors.append(f"backup manifest members[{index}].size is invalid")
                if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                    errors.append(f"backup manifest members[{index}].sha256 is invalid")
                if schema_version in {2, 3}:
                    if (
                        not isinstance(permission_mode, int)
                        or isinstance(permission_mode, bool)
                        or not 0 <= permission_mode <= 0o7777
                    ):
                        errors.append(
                            f"backup manifest members[{index}].mode is invalid"
                        )
                    elif path in infos_by_name:
                        archived_mode = stat.S_IMODE(
                            (infos_by_name[path].external_attr >> 16) & 0xFFFF
                        )
                        if permission_mode != archived_mode:
                            errors.append(
                                f"archive member mode does not match manifest: {path}"
                            )
                if path in names:
                    content = zf.read(path)
                    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                        errors.append(f"archive member does not match manifest: {path}")
            if member_paths != sorted(set(member_paths)):
                errors.append("backup manifest member paths must be sorted and unique")
            archive_members = sorted(name for name in names if name != BACKUP_MANIFEST_NAME)
            if archive_members != member_paths:
                errors.append("archive member set does not match backup manifest")
            if schema_version == 3:
                directories = manifest.get("directories")
                if not isinstance(directories, list):
                    errors.append("backup manifest directories must be a list")
                    return None, errors
                directory_paths: list[str] = []
                for index, directory in enumerate(directories):
                    if (
                        not isinstance(directory, dict)
                        or set(directory) != BACKUP_DIRECTORY_FIELDS_V3
                    ):
                        errors.append(
                            f"backup manifest directories[{index}] has invalid fields"
                        )
                        continue
                    path = directory.get("path")
                    permission_mode = directory.get("mode")
                    if not _safe_backup_member_name(path):
                        errors.append(
                            f"backup manifest directories[{index}].path is unsafe"
                        )
                        continue
                    directory_paths.append(path)
                    if (
                        not isinstance(permission_mode, int)
                        or isinstance(permission_mode, bool)
                        or not 0 <= permission_mode <= 0o7777
                    ):
                        errors.append(
                            f"backup manifest directories[{index}].mode is invalid"
                        )
                if directory_paths != sorted(set(directory_paths)):
                    errors.append(
                        "backup manifest directory paths must be sorted and unique"
                    )
            raw_sha = manifest.get("raw_artifact_manifest_sha256")
            if raw_sha is not None and (
                not isinstance(raw_sha, str) or not SHA256_RE.fullmatch(raw_sha)
            ):
                errors.append("raw_artifact_manifest_sha256 must be null or lowercase SHA-256")
            raw_path = "scripts/raw-artifacts.json"
            raw_member = next((member for member in members if isinstance(member, dict) and member.get("path") == raw_path), None)
            expected_raw_sha = raw_member.get("sha256") if raw_member is not None else None
            if raw_sha != expected_raw_sha:
                errors.append("raw artifact manifest hash does not match its member")
    except (OSError, KeyError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        return None, [f"cannot verify backup archive: {exc}"]
    return (manifest if not errors else None), errors


def _backup_member_coverage_errors(
    names: list[str], expected_count: int, output_rel: str | None,
) -> list[str]:
    errors = validate_names(names)
    if output_rel is not None and output_rel in names:
        errors.append(f"archive unexpectedly contains itself ({output_rel})")
    if len(names) != expected_count + 1:
        errors.append(f"archive file count {len(names)} did not match expected {expected_count + 1}")
    return errors


def verify_zip(
    output: Path | BinaryIO,
    expected_count: int,
    output_rel: str | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    _manifest, manifest_errors = verify_backup_archive(output)
    errors.extend(manifest_errors)
    try:
        with (_archive_stream(output) if isinstance(output, Path) else contextlib.nullcontext(output)) as source, zipfile.ZipFile(source) as zf:
            names = zf.namelist()
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        return False, [*errors, f"cannot inspect archive members: {exc}"]
    errors.extend(_backup_member_coverage_errors(names, expected_count, output_rel))
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


def _stream_file_hashes(path: Path) -> tuple[str, str]:
    with _archive_stream(path) as stream:
        return _stream_hashes(stream)


def upload_rclone(
    output: Path,
    target: str,
    rclone_bin: str = "rclone",
    init_drive_remote: str | None = None,
    *,
    installed_proof: VerifiedUpload | None = None,
) -> tuple[VerifiedUpload | None, list[str]]:
    if not output.exists():
        return None, [f"{output} was not created"]
    remote = rclone_remote_name(target)
    if remote is None:
        return None, ["--upload-target must be an rclone path like remote:path/file.zip"]
    if init_drive_remote and init_drive_remote != remote:
        return None, [
            f"--init-rclone-drive {init_drive_remote!r} does not match "
            f"--upload-target remote {remote!r}"
        ]
    if init_drive_remote:
        ok, errors = ensure_google_drive_remote(init_drive_remote, rclone_bin)
        if not ok:
            return None, errors

    expected_size = output.stat().st_size
    expected_md5, expected_sha256 = _stream_file_hashes(output)
    if installed_proof is not None and (
        expected_size != installed_proof.byte_count
        or expected_sha256 != installed_proof.content_sha256
    ):
        return None, ["local archive changed since verified installation; upload refused"]
    ok, _, errors = run_rclone(rclone_bin, ["copyto", str(output), target])
    if not ok:
        return None, errors
    ok, stdout, errors = run_rclone(rclone_bin, ["lsl", target])
    if not ok:
        return None, errors
    remote_size, parse_errors = parse_rclone_lsl_size(stdout)
    if parse_errors:
        return None, parse_errors
    if remote_size != expected_size:
        return None, [
            f"remote size {remote_size} did not match local size {expected_size}"
        ]
    ok, stdout, errors = run_rclone(rclone_bin, ["md5sum", target])
    if not ok:
        return None, errors
    remote_md5, parse_errors = parse_rclone_md5(stdout)
    if parse_errors:
        return None, parse_errors
    if remote_md5 != expected_md5:
        return None, [f"remote md5 {remote_md5} did not match local md5 {expected_md5}"]
    final_size = output.stat().st_size
    final_md5, final_sha256 = _stream_file_hashes(output)
    if (
        final_size != expected_size
        or final_md5 != expected_md5
        or final_sha256 != expected_sha256
    ):
        return None, ["local archive changed during remote verification"]
    return VerifiedUpload(expected_size, expected_sha256), []


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

    output = zip_path(repo_root, args.output_dir, stamp)
    try:
        symlinks = find_symlinks(repo_root, output)
    except (OSError, ValueError) as exc:
        print(f"Wiki export inventory failed: {exc}", file=sys.stderr)
        return 1
    if symlinks:
        print("Wiki export refused: the tree contains symlink(s):", file=sys.stderr)
        for link in symlinks:
            print(f"- {link.relative_to(repo_root)}", file=sys.stderr)
        return 1
    receipt_path = args.receipt_path
    if not receipt_path.is_absolute():
        receipt_path = repo_root / receipt_path
    if receipt_path.resolve() == output.resolve():
        print("Error: --receipt-path must differ from the export archive path.", file=sys.stderr)
        return 2
    try:
        files = export_files(repo_root, output)
    except (OSError, ValueError) as exc:
        print(f"Wiki export inventory failed: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        names = [path.relative_to(repo_root).as_posix() for path in files]
        errors = validate_names(names)
        print(f"Export dry run: {len(files)} file(s) would be written to {output}")
        print("Required export coverage: " + ("yes" if not errors else "no"))
        if args.upload_target:
            print(f"Private backup target (dry run only): {args.upload_target}")
        for error in errors:
            print(f"- {error}")
        return 0 if not errors else 1

    try:
        installed_proof = build_zip(repo_root, output, files, require_restore_ready=True)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Wiki export verification failed: {exc}", file=sys.stderr)
        return 1

    print(f"Wiki export created: {output}")
    print(f"Files included: {len(files)}")
    print(f"Size bytes: {output.stat().st_size}")
    if args.upload_target:
        proof, errors = upload_rclone(
            output,
            args.upload_target,
            args.rclone_bin,
            args.init_rclone_drive,
            installed_proof=installed_proof,
        )
        if proof is None:
            print("Private off-device backup copy failed:")
            for error in errors:
                print(f"- {error}")
            print(f"Local zip remains: {output}")
            return 1
        print(f"Private off-device backup verified: {args.upload_target}")
        try:
            receipt = record_verified_backup(
                output,
                args.upload_target,
                receipt_path,
                verified_content_sha256=proof.content_sha256,
                verified_byte_count=proof.byte_count,
            )
        except (BackupReceiptError, OSError) as exc:
            print(f"Verified backup receipt failed: {exc}", file=sys.stderr)
            return 1
        print(f"Backup receipt updated: {receipt_path}")
        print(f"Verified at: {receipt.verified_at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
