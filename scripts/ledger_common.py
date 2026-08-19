#!/usr/bin/env python3
"""Shared helpers for the approval ledger.

The approval gate writes capture_approval and synthesis_approval records to one
JSONL ledger through a stable sidecar lock and atomic full-file replacement.
Idempotency is based on canonical approval content identity:
historical records may still carry inert legacy run_id fields, but new records
do not generate legacy identifiers and validators ignore them. Measured capture
records may carry draft_sha256 as durable content evidence; that hash remains
part of the approval identity.

Every approval record's primary_home must be included in pages_touched, so the
main approved destination is always part of the explicit editable scope.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NewType

from _durable_files import (
    DurableFileError,
    atomic_replace_bytes,
    read_regular_bytes,
    sha256_bytes,
    stable_lock,
)
from _repo_paths import MAY_CREATE_FILE, RepoPathError, resolve_repo_path


# Durable roots an approved capture/promotion/synthesis may edit. raw/ is
# excluded on purpose: source artifacts are never edited or committed.
ALLOWED_ROOTS = ("wiki/", "scripts/", "workflows/", ".claude/", ".codex/")
ALLOWED_ROOT_FILES = {"AGENTS.md", "CLAUDE.md", "CONTEXT.md", "README.md", "REFERENCES.md"}
APPROVAL_RECORD_TYPES = frozenset({"capture_approval", "synthesis_approval"})
# Inert identifier field on historical records; new records never generate it.
LEGACY_ID_FIELD = "run_id"
IDENTITY_EXCLUDE_FIELDS = {"approved_at", LEGACY_ID_FIELD, "word_count_source", "word_count_path"}

ApprovalRecordSha256 = NewType("ApprovalRecordSha256", str)


class LedgerIntegrityError(ValueError):
    """A candidate or complete ledger failed deterministic validation."""

    def __init__(self, failures: str | list[str] | tuple[str, ...]):
        if isinstance(failures, str):
            failures = (failures,)
        self.failures = tuple(failures)
        super().__init__("approval ledger integrity check failed: " + "; ".join(self.failures))


@dataclass(frozen=True)
class ValidatedApprovalLine:
    record: dict[str, object]
    line_no: int
    line_text: str
    sha256: ApprovalRecordSha256


@dataclass(frozen=True)
class LedgerValidation:
    errors: tuple[str, ...]
    approval_count: int
    approvals: tuple[ValidatedApprovalLine, ...]


def under_allowed_root(path: str, *, repo_root: Path) -> bool:
    """True when a destination path is under an allowed durable root and not
    under raw/. The explicit raw/ exclusion is redundant defense (raw/ is not an
    allowed root) but makes the no-raw rule legible at the one place it matters."""
    try:
        resolve_repo_path(
            path,
            repo_root=repo_root,
            allowed_prefixes=(prefix.rstrip("/") for prefix in ALLOWED_ROOTS),
            allowed_root_files=ALLOWED_ROOT_FILES,
            mode=MAY_CREATE_FILE,
        )
    except RepoPathError:
        return False
    return True


def is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_strict_int(value: object) -> bool:
    """True for real integers only. bool subclasses int in Python (True == 1),
    so a bare isinstance/equality check would accept `"schema_version": true`;
    every integer-shaped ledger field must reject booleans explicitly."""
    return isinstance(value, int) and not isinstance(value, bool)


def split_scope(value: str) -> list[str]:
    """Comma-separated --pages-touched into a clean list: blanks dropped,
    duplicates removed order-preservingly."""
    items = [item.strip() for item in value.split(",") if item.strip()]
    return list(dict.fromkeys(items))


def approved_at_now() -> str:
    """Current UTC time in the ISO-8601 'Z' form the gate emits."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_timestamp(value: object) -> str | None:
    if not is_nonempty_string(value):
        return "approved_at must be a non-empty string"
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return "approved_at must be ISO-8601 parseable"
    return None


def validate_schema(record: dict[str, object], line_no: int) -> list[str]:
    errors: list[str] = []
    if line_no != 1:
        errors.append("schema record must be the first line")
    if not is_strict_int(record.get("schema_version")) or record["schema_version"] != 1:
        errors.append("schema record must have schema_version 1")
    if not is_nonempty_string(record.get("description")):
        errors.append("schema record must have a description")
    return errors


def validate_pages(record: dict[str, object], *, repo_root: Path) -> list[str]:
    """Validate pages_touched shape, allowed-root scope, and primary_home membership."""
    pages_touched = record.get("pages_touched")
    if not isinstance(pages_touched, list) or not pages_touched:
        return ["pages_touched must be a non-empty list"]
    if not all(is_nonempty_string(path) for path in pages_touched):
        return ["pages_touched entries must be non-empty strings"]
    errors: list[str] = []
    # An approval names real files: placeholder ("<...>") paths are invalid in
    # any approved scope, matching the gate's own guard.
    placeholders = [p for p in pages_touched if "<" in p or ">" in p]
    if placeholders:
        errors.append(f"pages_touched must not contain placeholder paths: {placeholders}")
    primary_home = record.get("primary_home")
    if is_nonempty_string(primary_home) and ("<" in primary_home or ">" in primary_home):
        errors.append("primary_home must not be a placeholder path")
    if is_nonempty_string(primary_home) and primary_home not in pages_touched:
        errors.append("primary_home must be included in pages_touched")
    # Historical backfills may reference paths that predate current roots.
    if record.get("backfilled") is not True:
        outside = [
            path for path in pages_touched
            if not under_allowed_root(path, repo_root=repo_root)
        ]
        if outside:
            errors.append(f"pages_touched paths must be under an allowed root: {outside}")
    return errors


def has_schema_record(path: Path) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("record_type") == "schema":
            return True
    return False


def approval_identity(record: dict[str, object]) -> str:
    """Canonical content identity for idempotency and duplicate detection.

    approved_at is event metadata, the legacy identifier is inert historical
    residue, and word_count_source / word_count_path are measurement metadata.
    None should make the same approved boundary look different.
    """
    filtered = {
        key: value
        for key, value in record.items()
        if key not in IDENTITY_EXCLUDE_FIELDS
    }
    return json.dumps(filtered, sort_keys=True, separators=(",", ":"))


def approval_label(record: dict[str, object]) -> str:
    artifact = str(record.get("artifact") or "approval").strip() or "approval"
    return artifact if len(artifact) <= 80 else artifact[:77] + "..."


def approval_record_sha256(line: str | bytes) -> ApprovalRecordSha256:
    """SHA-256 of one exact UTF-8 JSONL line, excluding only its LF."""
    encoded = line.encode("utf-8") if isinstance(line, str) else line
    if encoded.endswith(b"\n"):
        encoded = encoded[:-1]
    return ApprovalRecordSha256(hashlib.sha256(encoded).hexdigest())


def _json_nesting_exceeds(value: object, maximum_depth: int = 128) -> bool:
    """Reject adversarial JSON depth independently of interpreter limits."""
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > maximum_depth:
            return True
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
    return False


def validate_ledger_text(
    text: str,
    record_types: set[str] | frozenset[str],
    validate_approval: Callable[[dict[str, object]], list[str]],
    *,
    allow_empty: bool = False,
) -> LedgerValidation:
    """Pure structural and semantic validation over exact JSONL text."""
    if text == "":
        errors = () if allow_empty else ("expected exactly one schema record, found 0",)
        return LedgerValidation(errors, 0, ())
    if not text.strip():
        return LedgerValidation(
            ("ledger is nonempty but contains only whitespace",), 0, ()
        )

    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()

    errors: list[str] = []
    approvals: list[ValidatedApprovalLine] = []
    seen_identities: set[str] = set()
    schema_count = 0
    approval_count = 0
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"line {line_no}: blank lines are not allowed")
            continue
        try:
            record = json.loads(line)
        except (ValueError, RecursionError) as exc:
            detail = getattr(exc, "msg", str(exc))
            errors.append(f"line {line_no}: invalid JSON: {detail}")
            continue
        if _json_nesting_exceeds(record):
            errors.append(f"line {line_no}: invalid JSON: maximum nesting depth exceeded")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {line_no}: record must be a JSON object")
            continue

        record_type = record.get("record_type")
        if record_type == "schema":
            schema_count += 1
            errors.extend(
                f"line {line_no}: {error}"
                for error in validate_schema(record, line_no)
            )
            continue
        if not isinstance(record_type, str) or record_type not in record_types:
            errors.append(f"line {line_no}: unsupported record_type {record_type!r}")
            continue

        approval_count += 1
        errors.extend(
            f"line {line_no}: {error}" for error in validate_approval(record)
        )
        try:
            identity = approval_identity(record)
        except (TypeError, ValueError, RecursionError) as exc:
            errors.append(f"line {line_no}: approval identity is not canonicalizable: {exc}")
        else:
            if identity in seen_identities:
                errors.append(f"line {line_no}: duplicate approval record")
            seen_identities.add(identity)
        approvals.append(
            ValidatedApprovalLine(
                record=record,
                line_no=line_no,
                line_text=line,
                sha256=approval_record_sha256(line),
            )
        )

    if schema_count != 1:
        errors.append(f"expected exactly one schema record, found {schema_count}")
    return LedgerValidation(tuple(errors), approval_count, tuple(approvals))


def _decode_ledger(content: bytes, label: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LedgerIntegrityError(f"{label} is not valid UTF-8: {exc}") from exc


def _require_valid(result: LedgerValidation) -> None:
    if result.errors:
        raise LedgerIntegrityError(result.errors)


def _validate_candidate(
    record: dict[str, object],
    record_type: str,
    validate_approval: Callable[[dict[str, object]], list[str]],
) -> None:
    errors: list[str] = []
    if not isinstance(record_type, str) or record_type not in APPROVAL_RECORD_TYPES:
        errors.append(f"unsupported candidate record_type {record_type!r}")
    if not isinstance(record, dict):
        errors.append("candidate record must be a JSON object")
    elif record.get("record_type") != record_type:
        errors.append(
            f"candidate record_type {record.get('record_type')!r} does not match {record_type!r}"
        )
    elif record.get("backfilled") is True:
        errors.append("the live writer may not create backfilled approval records")
    elif _json_nesting_exceeds(record):
        errors.append("candidate JSON exceeds maximum nesting depth")
    else:
        errors.extend(validate_approval(record))
    if errors:
        raise LedgerIntegrityError([f"candidate: {error}" for error in errors])


def approval_lock_path(ledger_path: Path) -> Path:
    """Stable sidecar lock whose inode survives replacement of the ledger."""
    return ledger_path.with_name(f".{ledger_path.stem}.lock")


def write_approval_record(
    ledger_path: Path,
    record: dict[str, object],
    record_type: str,
    schema_description: str,
    validate_approval: Callable[[dict[str, object]], list[str]],
    *,
    fault: Callable[[str], None] | None = None,
) -> tuple[bool, Path, str, ApprovalRecordSha256]:
    """Validate then idempotently install one complete approval-ledger image."""
    _validate_candidate(record, record_type, validate_approval)
    if not is_nonempty_string(schema_description):
        raise LedgerIntegrityError("candidate schema description must be nonempty")
    try:
        record_line = json.dumps(
            record, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise LedgerIntegrityError(f"candidate is not JSON serializable: {exc}") from exc

    label = approval_label(record)
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with stable_lock(approval_lock_path(ledger_path)):
            content_or_none, _ = read_regular_bytes(ledger_path, allow_missing=True)
            content = content_or_none or b""
            if content:
                existing = validate_ledger_text(
                    _decode_ledger(content, str(ledger_path)),
                    APPROVAL_RECORD_TYPES,
                    validate_approval,
                )
                _require_valid(existing)
                identity = approval_identity(record)
                for approval in existing.approvals:
                    if approval_identity(approval.record) == identity:
                        return False, ledger_path, label, approval.sha256
            else:
                existing = validate_ledger_text(
                    "", APPROVAL_RECORD_TYPES, validate_approval, allow_empty=True
                )
                _require_valid(existing)

            if content:
                separator = b"" if content.endswith(b"\n") else b"\n"
                payload = separator + record_line + b"\n"
            else:
                schema = {
                    "record_type": "schema",
                    "schema_version": 1,
                    "description": schema_description,
                }
                schema_line = json.dumps(
                    schema, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                payload = schema_line + b"\n" + record_line + b"\n"

            projected = content + payload
            projected_result = validate_ledger_text(
                _decode_ledger(projected, "projected ledger"),
                APPROVAL_RECORD_TYPES,
                validate_approval,
            )
            _require_valid(projected_result)
            expected = sha256_bytes(content) if content_or_none is not None else None
            atomic_replace_bytes(
                ledger_path,
                projected,
                mode=0o600,
                expected_sha256=expected,
                fault=fault,
            )
            installed, _ = read_regular_bytes(ledger_path)
            if installed is None or sha256_bytes(installed) != sha256_bytes(projected):
                raise LedgerIntegrityError("installed ledger hash does not match projected bytes")
            installed_result = validate_ledger_text(
                _decode_ledger(installed, str(ledger_path)),
                APPROVAL_RECORD_TYPES,
                validate_approval,
            )
            _require_valid(installed_result)
    except LedgerIntegrityError:
        raise
    except (OSError, DurableFileError) as exc:
        raise LedgerIntegrityError(f"ledger I/O failed for {ledger_path}: {exc}") from exc
    return True, ledger_path, label, approval_record_sha256(record_line)


def lookup_approval_record_by_sha256(
    path: Path,
    record_sha256: ApprovalRecordSha256,
    record_types: set[str] | frozenset[str],
    validate_approval: Callable[[dict[str, object]], list[str]],
) -> dict[str, object] | None:
    """Return a record by exact line hash, only after full-ledger validation."""
    try:
        content, _ = read_regular_bytes(path)
    except (OSError, DurableFileError) as exc:
        raise LedgerIntegrityError(f"cannot read approval ledger {path}: {exc}") from exc
    assert content is not None
    result = validate_ledger_text(
        _decode_ledger(content, str(path)), record_types, validate_approval
    )
    _require_valid(result)
    for approval in result.approvals:
        if approval.sha256 == record_sha256:
            return approval.record
    return None


def validate_ledger(
    path: Path,
    record_types: set[str] | frozenset[str],
    validate_approval: Callable[[dict[str, object]], list[str]],
) -> tuple[list[str], int]:
    """Read a JSONL approval ledger and apply the shared pure validator."""
    try:
        content, _ = read_regular_bytes(path)
    except (OSError, DurableFileError) as exc:
        return [f"cannot read {path}: {exc}"], 0
    assert content is not None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"{path} is not valid UTF-8: {exc}"], 0
    result = validate_ledger_text(text, record_types, validate_approval)
    return list(result.errors), result.approval_count
