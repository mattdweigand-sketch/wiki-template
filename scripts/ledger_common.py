#!/usr/bin/env python3
"""Shared parsing and validation helpers for the capture application ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NewType

from _durable_files import DurableFileError, read_regular_bytes
from _repo_paths import MAY_CREATE_FILE, RepoPathError, resolve_repo_path


# Durable roots an approved capture/promotion/synthesis may edit. raw/ is
# excluded on purpose: source artifacts are never edited or committed.
ALLOWED_ROOTS = (
    "wiki/", "scripts/", "workflows/", ".agents/", ".claude/", ".codex/",
)
ALLOWED_ROOT_FILES = {"AGENTS.md", "CLAUDE.md", "CONTEXT.md", "README.md", "REFERENCES.md"}
APPROVAL_RECORD_TYPES = frozenset(
    {"capture_approval", "synthesis_approval", "capture_application"}
)
# Inert identifier field on historical records; new records never generate it.
LEGACY_ID_FIELD = "run_id"
IDENTITY_EXCLUDE_FIELDS = {"approved_at", LEGACY_ID_FIELD, "word_count_source", "word_count_path"}

ApprovalRecordSha256 = NewType("ApprovalRecordSha256", str)


class LedgerIntegrityError(ValueError):
    """A candidate or complete ledger failed deterministic validation."""

    def __init__(self, failures: str | list[str] | tuple[str, ...]) -> None:
        if isinstance(failures, str):
            failures = (failures,)
        self.failures = tuple(failures)
        super().__init__("approval ledger integrity check failed: " + "; ".join(self.failures))


class _DuplicateLedgerKeyError(ValueError):
    """One JSON object repeated a key and is therefore ambiguous."""


def _reject_duplicate_ledger_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise _DuplicateLedgerKeyError(f"duplicate JSON key: {key}")
        record[key] = value
    return record


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
            allowed_prefixes=tuple(prefix.rstrip("/") for prefix in ALLOWED_ROOTS),
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
    seen_application_digests: set[str] = set()
    schema_count = 0
    approval_count = 0
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"line {line_no}: blank lines are not allowed")
            continue
        try:
            record = json.loads(line, object_pairs_hook=_reject_duplicate_ledger_keys)
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
        if record_type == "capture_application":
            digest = record.get("authorization_digest")
            if isinstance(digest, str):
                if digest in seen_application_digests:
                    errors.append(
                        f"line {line_no}: duplicate capture application authorization_digest"
                    )
                seen_application_digests.add(digest)
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
