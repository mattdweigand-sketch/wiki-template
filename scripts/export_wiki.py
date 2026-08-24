#!/usr/bin/env python3
"""Build and verify a complete private backup of one local wiki tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

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


def export_files(
    repo_root: Path,
    output: Path | None = None,
) -> list[Path]:
    """Return regular files while excluding generated wiki export archives."""
    resolved_output = output.resolve() if output is not None else None
    files: list[Path] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if resolved_output is not None:
            resolved_path = path.resolve()
            if resolved_path == resolved_output:
                continue
        relative = path.relative_to(repo_root)
        if (
            relative.parts[0] != "raw"
            and EXPORT_ARCHIVE_RE.fullmatch(path.name)
        ):
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


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def build_backup_manifest(repo_root: Path, files: list[Path]) -> dict[str, object]:
    """Build the canonical exact-member manifest for one export snapshot."""
    members = []
    for path in files:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"backup member is not a regular file: {path}")
        content = path.read_bytes()
        members.append({
            "path": path.relative_to(repo_root).as_posix(),
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "mode": stat.S_IMODE(metadata.st_mode),
        })
    members.sort(key=lambda member: str(member["path"]))
    raw_manifest = repo_root / "scripts/raw-artifacts.json"
    raw_sha = hashlib.sha256(raw_manifest.read_bytes()).hexdigest() if raw_manifest.is_file() else None
    directories = [
        {
            "path": path.relative_to(repo_root).as_posix(),
            "mode": stat.S_IMODE(path.lstat().st_mode),
        }
        for path in sorted(repo_root.rglob("*"))
        if path.is_dir() and not path.is_symlink()
    ]
    return {
        "schema_version": BACKUP_MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "members": members,
        "directories": directories,
        "raw_artifact_manifest_sha256": raw_sha,
    }


def build_zip(repo_root: Path, output: Path, files: list[Path]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(repo_root).as_posix())
        info = zipfile.ZipInfo(BACKUP_MANIFEST_NAME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o100600 << 16)
        zf.writestr(info, _canonical_json_bytes(build_backup_manifest(repo_root, files)))


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


def verify_backup_archive(output: Path) -> tuple[dict[str, object] | None, list[str]]:
    """Verify archive safety plus exact member paths, bytes, and permission modes."""
    errors: list[str] = []
    try:
        with zipfile.ZipFile(output) as zf:
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
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        return None, [f"cannot verify backup archive: {exc}"]
    return (manifest if not errors else None), errors


def verify_zip(
    output: Path,
    expected_count: int,
    output_rel: str | None = None,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not output.exists():
        return False, [f"{output} was not created"]
    manifest, manifest_errors = verify_backup_archive(output)
    errors.extend(manifest_errors)
    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
    if output_rel is not None and output_rel in names:
        errors.append(f"archive unexpectedly contains itself ({output_rel})")
    errors.extend(validate_names(names))
    if len(names) != expected_count + 1:
        errors.append(f"archive file count {len(names)} did not match expected {expected_count + 1}")
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
    files = export_files(repo_root, output)
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
            print(f"Private backup target (dry run only): {args.upload_target}")
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
            print("Private off-device backup copy failed:")
            for error in errors:
                print(f"- {error}")
            print(f"Local zip remains: {output}")
            return 1
        print(f"Private off-device backup verified: {args.upload_target}")
        try:
            receipt = record_verified_backup(output, args.upload_target, receipt_path)
        except (BackupReceiptError, OSError) as exc:
            print(f"Verified backup receipt failed: {exc}", file=sys.stderr)
            return 1
        print(f"Backup receipt updated: {receipt_path}")
        print(f"Verified at: {receipt.verified_at}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
