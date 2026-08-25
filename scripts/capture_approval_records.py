#!/usr/bin/env python3
"""Exact durable record construction for approved capture applications."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from capture_ledger import (
    CaptureLedgerIntegrityError,
    validate_capture_application,
    validate_capture_ledger_text,
)


LEDGER_SCHEMA_DESCRIPTION = (
    "Append-only exact application records written by scripts/capture_gate.py."
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
        "schema_version": 3,
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
        raise CaptureLedgerIntegrityError(
            f"capture ledger is not valid UTF-8: {exc}"
        ) from exc
    validation = validate_capture_ledger_text(text)
    if validation.errors:
        raise CaptureLedgerIntegrityError(validation.errors)
    matches = [
        item.record for item in validation.applications
        if item.record.get("record_type") == "capture_application"
        and item.record.get("authorization_digest") == authorization_digest
    ]
    if len(matches) > 1:
        raise CaptureLedgerIntegrityError(
            "capture ledger repeats one authorization digest"
        )
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
            raise CaptureLedgerIntegrityError(
                "authorization digest already names a different record"
            )
        return ledger_bytes
    problems = validate_capture_application(record)
    if problems:
        raise CaptureLedgerIntegrityError(
            [f"candidate: {problem}" for problem in problems]
        )
    separator = b"" if ledger_bytes.endswith(b"\n") else b"\n"
    line = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    projected = ledger_bytes + separator + line + b"\n"
    validation = validate_capture_ledger_text(projected.decode("utf-8"))
    if validation.errors:
        raise CaptureLedgerIntegrityError(validation.errors)
    return projected


__all__ = [
    "LEDGER_SCHEMA_DESCRIPTION",
    "capture_application_from_ledger",
    "capture_application_record",
    "render_capture_application_ledger",
]
