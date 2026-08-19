#!/usr/bin/env python3
"""Validated vocabulary and journal parsing for file transactions."""

from __future__ import annotations

import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from _durable_files import (
    DurableFileError,
    atomic_replace_bytes,
    durable_unlink,
    fsync_directory,
    read_regular_bytes,
    require_single_link_regular,
    sha256_bytes,
    stable_lock,
)


AUTHORITY_NAME = ".wiki-transactions"
CLEANUP_PREFIX = ".cleanup-"
PREPARING_PREFIX = ".preparing-"
SCHEMA_VERSION = 1
CONSUMERS = frozenset({"rotate-log", "rebuild-referenced-by"})
STATES = frozenset(
    {
        "PREPARING", "PREPARED", "COMMITTING", "COMMITTED", "COMPLETE",
        "ROLLING_BACK", "ROLLED_BACK", "CONFLICTED", "CORRUPT",
    }
)
TRANSITIONS = {
    "PREPARING": {"PREPARED", "CONFLICTED", "CORRUPT"},
    "PREPARED": {"COMMITTING", "CONFLICTED", "CORRUPT"},
    "COMMITTING": {"COMMITTED", "ROLLING_BACK", "CONFLICTED", "CORRUPT"},
    "ROLLING_BACK": {"ROLLED_BACK", "CONFLICTED", "CORRUPT"},
    "ROLLED_BACK": {"COMPLETE", "CONFLICTED", "CORRUPT"},
    "COMMITTED": {"COMPLETE", "CONFLICTED", "CORRUPT"},
    "COMPLETE": set(),
    "CONFLICTED": set(),
    "CORRUPT": set(),
}
JOURNAL_FIELDS = frozenset(
    {
        "schema_version", "transaction_id", "consumer", "created_at", "updated_at",
        "repo_root", "repo_device", "state", "generation", "allowed_prefixes", "plan_sha256", "targets",
        "guards", "integrity_sha256",
    }
)
TARGET_FIELDS = frozenset(
    {
        "path", "pre_state", "pre_sha256", "pre_mode", "pre_blob",
        "output_sha256", "output_mode", "output_blob", "installed",
    }
)
GUARD_FIELDS = frozenset({"path", "sha256", "mode"})
FaultHook = Callable[[str], None]


class TransactionError(RuntimeError):
    """A transaction could not proceed safely."""


class TransactionConflict(TransactionError):
    """Target bytes changed outside the recorded transaction."""


class TransactionCorrupt(TransactionError):
    """Transaction authority is malformed, unsafe, or incomplete."""


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _integrity(journal: dict[str, object]) -> str:
    return sha256_bytes(_canonical_json({key: value for key, value in journal.items() if key != "integrity_sha256"}))


def _plan_hash(
    consumer: str,
    allowed_prefixes: list[str],
    targets: list[dict[str, object]],
    guards: list[dict[str, object]],
) -> str:
    plan = {
        "consumer": consumer,
        "allowed_prefixes": allowed_prefixes,
        "targets": [
            {
                key: target[key]
                for key in (
                    "path", "pre_state", "pre_sha256", "pre_mode",
                    "output_sha256", "output_mode",
                )
            }
            for target in targets
        ],
        "guards": guards,
    }
    return sha256_bytes(_canonical_json(plan))


def _is_int(value: object, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_mode(value: object) -> bool:
    return _is_int(value) and value <= 0o7777


def _canonical_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = Path(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _allowed(path: str, prefixes: Iterable[str]) -> bool:
    for prefix in prefixes:
        clean = prefix.rstrip("/")
        if path == clean or path.startswith(clean + "/"):
            return True
    return False


def validate_target_path(repo_root: Path, relative: str, allowed_prefixes: Iterable[str]) -> Path:
    """Confine a transaction target without dereferencing unsafe ancestors."""
    if not _canonical_relative(relative):
        raise TransactionError(f"noncanonical transaction target: {relative!r}")
    if not _allowed(relative, allowed_prefixes):
        raise TransactionError(f"transaction target outside consumer scope: {relative}")
    current = repo_root
    parts = Path(relative).parts
    for part in parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise TransactionError(f"cannot inspect target parent {current}: {exc}") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise TransactionError(f"unsafe target parent: {current}")
    target = repo_root / relative
    try:
        info = target.lstat()
    except FileNotFoundError:
        return target
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise TransactionError(f"unsafe transaction target entry: {relative}")
    return target


def _authority_root(repo_root: Path) -> Path:
    return repo_root / AUTHORITY_NAME


def _ensure_authority(repo_root: Path) -> Path:
    authority = _authority_root(repo_root)
    try:
        info = authority.lstat()
    except FileNotFoundError:
        try:
            authority.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            fsync_directory(repo_root)
        info = authority.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise TransactionCorrupt(f"transaction authority root is not a real directory: {authority}")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise TransactionCorrupt(f"transaction authority root mode must be 0700: {authority}")
    if info.st_dev != repo_root.stat().st_dev:
        raise TransactionCorrupt(f"transaction authority root is on a different device: {authority}")
    return authority


def _strict_regular(path: Path, *, mode: int | None = None) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise TransactionCorrupt(f"cannot inspect authority entry {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise TransactionCorrupt(f"unsafe authority file: {path}")
    if mode is not None and stat.S_IMODE(info.st_mode) != mode:
        raise TransactionCorrupt(f"authority file mode must be {mode:04o}: {path}")
    return info


def _strict_directory(path: Path, *, mode: int = 0o700) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise TransactionCorrupt(f"cannot inspect authority directory {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise TransactionCorrupt(f"unsafe authority directory: {path}")
    if stat.S_IMODE(info.st_mode) != mode:
        raise TransactionCorrupt(f"authority directory mode must be {mode:04o}: {path}")
    return info


def _load_journal(
    tx_dir: Path,
    *,
    expected_transaction_id: str | None = None,
) -> dict[str, object]:
    journal_path = tx_dir / "journal.json"
    _strict_regular(journal_path, mode=0o600)
    try:
        content, _ = read_regular_bytes(journal_path)
        assert content is not None
        journal = json.loads(content.decode("utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise TransactionCorrupt(f"cannot parse {journal_path}: {exc}") from exc
    errors = validate_journal(journal)
    if errors:
        raise TransactionCorrupt(f"invalid journal {journal_path}: {'; '.join(errors)}")
    expected_id = expected_transaction_id or tx_dir.name
    if journal["transaction_id"] != expected_id:
        raise TransactionCorrupt(f"journal transaction_id does not match directory {tx_dir.name}")
    return journal


def validate_journal(journal: object) -> list[str]:
    """Validate an untrusted journal before recovery may act on its paths."""
    if not isinstance(journal, dict):
        return ["journal must be an object"]
    errors: list[str] = []
    if set(journal) != JOURNAL_FIELDS:
        errors.append(f"journal fields differ: missing={sorted(JOURNAL_FIELDS - set(journal))} unknown={sorted(set(journal) - JOURNAL_FIELDS)}")
    if journal.get("schema_version") != 1 or isinstance(journal.get("schema_version"), bool):
        errors.append("schema_version must be integer 1")
    try:
        uuid.UUID(str(journal.get("transaction_id")))
    except ValueError:
        errors.append("transaction_id must be a UUID")
    if journal.get("consumer") not in CONSUMERS:
        errors.append("unknown consumer")
    for key in ("created_at", "updated_at", "repo_root"):
        if not isinstance(journal.get(key), str) or not journal[key]:
            errors.append(f"{key} must be nonempty")
    if not _is_int(journal.get("repo_device")):
        errors.append("repo_device must be a nonnegative integer")
    if journal.get("state") not in STATES:
        errors.append("unknown state")
    if not _is_int(journal.get("generation")):
        errors.append("generation must be a nonnegative integer")
    allowed_prefixes = journal.get("allowed_prefixes")
    if (
        not isinstance(allowed_prefixes, list)
        or not allowed_prefixes
        or allowed_prefixes != sorted(set(allowed_prefixes))
        or not all(_canonical_relative(prefix) for prefix in allowed_prefixes)
    ):
        errors.append("allowed_prefixes must be a sorted unique canonical path list")
        allowed_prefixes = []
    if not _is_sha(journal.get("plan_sha256")):
        errors.append("invalid plan_sha256")
    targets = journal.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append("targets must be a nonempty list")
        targets = []
    seen_paths: set[str] = set()
    for index, target in enumerate(targets):
        label = f"target {index + 1}"
        if not isinstance(target, dict):
            errors.append(f"{label} must be an object")
            continue
        if set(target) != TARGET_FIELDS:
            errors.append(f"{label} fields differ")
        path = target.get("path")
        if not _canonical_relative(path):
            errors.append(f"{label} has noncanonical path")
        elif path in seen_paths:
            errors.append(f"{label} repeats path {path}")
        else:
            seen_paths.add(path)
        if target.get("pre_state") not in {"absent", "regular"}:
            errors.append(f"{label} invalid pre_state")
        if target.get("pre_state") == "absent":
            if any(target.get(key) is not None for key in ("pre_sha256", "pre_mode", "pre_blob")):
                errors.append(f"{label} absent pre-state must use null preimage fields")
        else:
            if not _is_sha(target.get("pre_sha256")) or not _is_mode(target.get("pre_mode")) or not isinstance(target.get("pre_blob"), str):
                errors.append(f"{label} invalid regular preimage fields")
            elif target.get("pre_blob") != f"blobs/pre-{index:04d}.bin":
                errors.append(f"{label} has noncanonical pre_blob")
        if not _is_sha(target.get("output_sha256")) or not _is_mode(target.get("output_mode")) or not isinstance(target.get("output_blob"), str):
            errors.append(f"{label} invalid output fields")
        elif target.get("output_blob") != f"blobs/output-{index:04d}.bin":
            errors.append(f"{label} has noncanonical output_blob")
        for blob_key in ("pre_blob", "output_blob"):
            blob = target.get(blob_key)
            if blob is not None and (not _canonical_relative(blob) or not blob.startswith("blobs/")):
                errors.append(f"{label} invalid {blob_key}")
        if not isinstance(target.get("installed"), bool):
            errors.append(f"{label} installed must be boolean")
    guards = journal.get("guards")
    if not isinstance(guards, list):
        errors.append("guards must be a list")
        guards = []
    guard_paths: set[str] = set()
    for index, guard in enumerate(guards):
        label = f"guard {index + 1}"
        if not isinstance(guard, dict):
            errors.append(f"{label} must be an object")
            continue
        if set(guard) != GUARD_FIELDS:
            errors.append(f"{label} fields differ")
        path = guard.get("path")
        if not _canonical_relative(path):
            errors.append(f"{label} has noncanonical path")
        elif path in seen_paths or path in guard_paths:
            errors.append(f"{label} repeats governed path {path}")
        else:
            guard_paths.add(path)
        if not _is_sha(guard.get("sha256")):
            errors.append(f"{label} has invalid sha256")
        if not _is_mode(guard.get("mode")):
            errors.append(f"{label} has invalid mode")
    if targets and allowed_prefixes and _is_sha(journal.get("plan_sha256")) and _plan_hash(journal.get("consumer"), allowed_prefixes, targets, guards) != journal["plan_sha256"]:
        errors.append("plan_sha256 mismatch")
    if not _is_sha(journal.get("integrity_sha256")) or _integrity(journal) != journal.get("integrity_sha256"):
        errors.append("integrity_sha256 mismatch")
    return errors


__all__ = [
    "AUTHORITY_NAME",
    "CLEANUP_PREFIX",
    "CONSUMERS",
    "PREPARING_PREFIX",
    "SCHEMA_VERSION",
    "STATES",
    "TRANSITIONS",
    "TransactionConflict",
    "TransactionCorrupt",
    "TransactionError",
    "validate_journal",
    "validate_target_path",
]
