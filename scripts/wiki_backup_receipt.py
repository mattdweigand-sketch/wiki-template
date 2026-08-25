#!/usr/bin/env python3
"""Destination-neutral receipts for verified private off-device backups."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from _durable_files import (
    DurableFileError,
    atomic_replace_bytes,
    read_regular_bytes,
    require_safe_parent,
    require_single_link_regular,
    sha256_bytes,
    stable_lock,
)
from _strict_json import DuplicateJsonKeyError, reject_duplicate_json_keys

DEFAULT_BACKUP_RECEIPT_PATH = Path("scripts/backup-receipt.json")
UTC_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class BackupReceiptError(ValueError):
    """A backup receipt is malformed or cannot be persisted safely."""


@dataclass(frozen=True)
class VerifiedBackupReceipt:
    schema_version: int
    verified_at: str
    content_sha256: str
    byte_count: int
    destination_id: str


BackupFreshnessKind = Literal["not-configured", "invalid", "future", "stale", "fresh"]


@dataclass(frozen=True)
class BackupFreshness:
    kind: BackupFreshnessKind
    message: str
    receipt: VerifiedBackupReceipt | None


def _stream_backup_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _redacted_destination_id(destination: str) -> str:
    """Return an opaque identifier that reveals no provider, account, or path."""
    return "sha256:" + hashlib.sha256(destination.encode("utf-8")).hexdigest()


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        raise BackupReceiptError("verified_at must be UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise BackupReceiptError("verified_at is not a real UTC timestamp") from exc


def load_backup_receipt(path: Path) -> VerifiedBackupReceipt:
    try:
        content, _ = read_regular_bytes(path)
        assert content is not None
        raw = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    except DuplicateJsonKeyError as exc:
        raise BackupReceiptError(f"duplicate JSON key {exc.key!r}") from exc
    except BackupReceiptError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupReceiptError(f"unreadable JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BackupReceiptError("top level must be a JSON object")
    fields = {
        "schema_version", "verified_at", "content_sha256", "byte_count",
        "destination_id",
    }
    if set(raw) != fields:
        raise BackupReceiptError("receipt fields do not match schema version 1")
    if raw["schema_version"] != 1 or isinstance(raw["schema_version"], bool):
        raise BackupReceiptError("schema_version must equal 1")
    _parse_timestamp(raw["verified_at"])
    if not isinstance(raw["content_sha256"], str) or not SHA256_RE.fullmatch(raw["content_sha256"]):
        raise BackupReceiptError("content_sha256 must be 64 lowercase hex characters")
    if (
        not isinstance(raw["byte_count"], int)
        or isinstance(raw["byte_count"], bool)
        or raw["byte_count"] < 0
    ):
        raise BackupReceiptError("byte_count must be a nonnegative integer")
    destination_id = raw["destination_id"]
    if (
        not isinstance(destination_id, str)
        or not destination_id.startswith("sha256:")
        or not SHA256_RE.fullmatch(destination_id.removeprefix("sha256:"))
    ):
        raise BackupReceiptError("destination_id must be a redacted sha256 identifier")
    return VerifiedBackupReceipt(
        schema_version=1,
        verified_at=raw["verified_at"],
        content_sha256=raw["content_sha256"],
        byte_count=raw["byte_count"],
        destination_id=destination_id,
    )


def _write_backup_receipt(path: Path, receipt: VerifiedBackupReceipt) -> None:
    """Durably replace the local receipt under one stable writer lock."""
    payload = (json.dumps(asdict(receipt), indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        require_safe_parent(path)
        lock_path = path.with_name(f".{path.name}.lock")
        with stable_lock(lock_path):
            require_single_link_regular(path, allow_missing=True)
            current, _ = read_regular_bytes(path, allow_missing=True)
            atomic_replace_bytes(
                path,
                payload,
                mode=0o600,
                expected_sha256=sha256_bytes(current) if current is not None else None,
            )
    except (OSError, DurableFileError) as exc:
        raise BackupReceiptError(f"could not write receipt: {exc}") from exc


def record_verified_backup(
    archive: Path,
    destination: str,
    receipt_path: Path = DEFAULT_BACKUP_RECEIPT_PATH,
    verified_at: datetime | None = None,
    *,
    verified_content_sha256: str,
    verified_byte_count: int,
) -> VerifiedBackupReceipt:
    """Stamp only the exact local bytes bound by completed remote verification."""
    moment = verified_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise BackupReceiptError("verified_at must be timezone-aware")
    if not SHA256_RE.fullmatch(verified_content_sha256):
        raise BackupReceiptError("verified_content_sha256 must be lowercase SHA-256")
    if (
        not isinstance(verified_byte_count, int)
        or isinstance(verified_byte_count, bool)
        or verified_byte_count < 0
    ):
        raise BackupReceiptError("verified_byte_count must be a nonnegative integer")
    current_size = archive.stat().st_size
    current_sha256 = _stream_backup_file_sha256(archive)
    if current_size != verified_byte_count or current_sha256 != verified_content_sha256:
        raise BackupReceiptError("local archive changed after remote verification")
    receipt = VerifiedBackupReceipt(
        schema_version=1,
        verified_at=moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        content_sha256=verified_content_sha256,
        byte_count=verified_byte_count,
        destination_id=_redacted_destination_id(destination),
    )
    _write_backup_receipt(receipt_path, receipt)
    return receipt


def backup_freshness(
    path: Path = DEFAULT_BACKUP_RECEIPT_PATH,
    *,
    now: datetime | None = None,
    max_age_days: int = 30,
) -> BackupFreshness:
    """Classify receipt state without turning an advisory into a gate."""
    if max_age_days < 0:
        raise ValueError("max_age_days must be nonnegative")
    if not path.exists() and not path.is_symlink():
        return BackupFreshness(
            "not-configured", "no verified remote-backup receipt is configured", None
        )
    try:
        receipt = load_backup_receipt(path)
        verified = _parse_timestamp(receipt.verified_at)
    except BackupReceiptError as exc:
        return BackupFreshness("invalid", f"backup receipt is invalid: {exc}", None)
    if now is not None and now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if verified > current:
        return BackupFreshness(
            "future", f"backup receipt is future-dated ({receipt.verified_at})", receipt
        )
    age = current - verified
    if age > timedelta(days=max_age_days):
        return BackupFreshness(
            "stale",
            f"last verified remote backup is {age.days} day(s) old "
            f"(threshold {max_age_days})",
            receipt,
        )
    return BackupFreshness(
        "fresh", f"last verified remote backup: {receipt.verified_at}", receipt
    )


__all__ = [
    "DEFAULT_BACKUP_RECEIPT_PATH",
    "BackupFreshness",
    "BackupFreshnessKind",
    "BackupReceiptError",
    "VerifiedBackupReceipt",
    "backup_freshness",
    "load_backup_receipt",
    "record_verified_backup",
]
