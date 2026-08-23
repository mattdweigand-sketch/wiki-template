#!/usr/bin/env python3
"""Exact durable record construction for approved capture applications."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ledger_common import LedgerIntegrityError
from validate_capture_runs import validate_approval


SYNTHESIS_DEFAULT_HOME = "wiki/synthesis.md"
LEDGER_SCHEMA_DESCRIPTION = (
    "Append-only exact application records written by scripts/capture_gate.py. "
    "Legacy capture and synthesis approval records remain valid as history but "
    "are no longer created. Free routes remain unrecorded here."
)


def capture_application_record(
    *,
    authorization_digest: str,
    capture_boundary: str,
    purpose: str,
    primary_destination: str,
    editable_scope: list[str],
    targets: list[dict[str, object]],
) -> dict[str, object]:
    """Build one combined record for an exact approved application."""
    return {
        "record_type": "capture_application",
        "schema_version": 2,
        "application_status": "applied",
        "applied_at": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "authorization_digest": authorization_digest,
        "capture_boundary": capture_boundary,
        "purpose": purpose,
        "primary_destination": primary_destination,
        "editable_scope": editable_scope,
        "targets": targets,
    }


def capture_application_from_ledger(
    ledger_bytes: bytes,
    authorization_digest: str,
) -> dict[str, object] | None:
    """Find an exact prior application after validating the complete ledger."""
    try:
        text = ledger_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LedgerIntegrityError(f"capture ledger is not valid UTF-8: {exc}") from exc
    from ledger_common import APPROVAL_RECORD_TYPES, validate_ledger_text

    validation = validate_ledger_text(text, APPROVAL_RECORD_TYPES, validate_approval)
    if validation.errors:
        raise LedgerIntegrityError(validation.errors)
    matches = [
        item.record for item in validation.approvals
        if item.record.get("record_type") == "capture_application"
        and item.record.get("authorization_digest") == authorization_digest
    ]
    if len(matches) > 1:
        raise LedgerIntegrityError("capture ledger repeats one authorization digest")
    return matches[0] if matches else None


def render_capture_application_ledger(
    ledger_bytes: bytes,
    record: dict[str, object],
) -> bytes:
    """Return the validated ledger postimage containing one application record."""
    existing = capture_application_from_ledger(
        ledger_bytes, str(record.get("authorization_digest", ""))
    )
    if existing is not None:
        if existing != record:
            raise LedgerIntegrityError("authorization digest already names a different record")
        return ledger_bytes
    problems = validate_approval(record)
    if problems:
        raise LedgerIntegrityError([f"candidate: {problem}" for problem in problems])
    separator = b"" if ledger_bytes.endswith(b"\n") else b"\n"
    line = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    projected = ledger_bytes + separator + line + b"\n"
    from ledger_common import APPROVAL_RECORD_TYPES, validate_ledger_text

    validation = validate_ledger_text(
        projected.decode("utf-8"), APPROVAL_RECORD_TYPES, validate_approval
    )
    if validation.errors:
        raise LedgerIntegrityError(validation.errors)
    return projected


__all__ = [
    "LEDGER_SCHEMA_DESCRIPTION",
    "SYNTHESIS_DEFAULT_HOME",
    "capture_application_from_ledger",
    "capture_application_record",
    "render_capture_application_ledger",
]
