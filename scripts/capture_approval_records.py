#!/usr/bin/env python3
"""Exact durable record construction for capture and synthesis approvals."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import NewType

from capture_approval_policy import DraftSha256, is_analyses_path
from ledger_common import ApprovalRecordSha256, approved_at_now, write_approval_record
from validate_capture_runs import validate_approval


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APPROVAL_LEDGER = str(REPO_ROOT / "scripts" / "capture-runs.jsonl")
SYNTHESIS_DEFAULT_HOME = "wiki/synthesis.md"
LEDGER_SCHEMA_DESCRIPTION = (
    "Append-only operational records written by scripts/capture_gate.py after "
    "the user approves exact analysis-capture, artifact-promotion, or synthesis "
    "approval scopes. Free routes such as ingest, decision capture, experience "
    "capture, and workflow updates remain unrecorded here."
)

AuthoredSha256 = NewType("AuthoredSha256", str)


def capture_approval_record(
    args: argparse.Namespace,
    route: str,
    home: str,
    scope: list[str],
    word_count: int,
    word_count_source: str,
    draft_sha256: DraftSha256 | None = None,
    authored_sha256: AuthoredSha256 | None = None,
) -> dict[str, object]:
    """Build the exact validated record owned by a capture approval."""
    record: dict[str, object] = {
        "record_type": "capture_approval",
        "schema_version": 1,
        "approval_status": "approved",
        "approved_at": approved_at_now(),
        "artifact": args.artifact.strip(),
        "route": route,
        "phase": args.phase,
        "primary_home": home.strip(),
        "pages_touched": scope,
        "source_path": args.source_path.strip(),
        "synthesized_pages": args.synthesized_pages,
        "word_count": word_count,
        "word_count_source": word_count_source,
        "word_count_path": args.path.strip(),
        "domain_context": args.domain_context,
        "triggers": sorted(set(args.trigger)),
    }
    if draft_sha256 is not None:
        record["draft_sha256"] = draft_sha256
    if authored_sha256 is not None and (
        route == "analysis-capture" or any(is_analyses_path(path) for path in scope)
    ):
        record["authored_sha256"] = authored_sha256
        record["authored_hash_policy"] = "strip_referenced_by_v1"
    return record


def synthesis_approval_record(
    args: argparse.Namespace,
    home: str,
    scope: list[str],
) -> dict[str, object]:
    """Build the exact validated record owned by a synthesis approval."""
    return {
        "record_type": "synthesis_approval",
        "schema_version": 1,
        "approval_status": "approved",
        "approved_at": approved_at_now(),
        "artifact": args.artifact.strip(),
        "drafts": args.drafts.strip(),
        "primary_home": home.strip(),
        "pages_touched": scope,
        # Fully derived: synthesis_guard has already required home in scope.
        "ledger_update_required": home.strip() == SYNTHESIS_DEFAULT_HOME,
    }


def append_capture_approval_record(
    record: dict[str, object],
    ledger: str,
    record_type: str,
) -> tuple[bool, Path, str, ApprovalRecordSha256]:
    """Bind capture records to the shared ledger validator and schema text."""
    return write_approval_record(
        Path(ledger),
        record,
        record_type=record_type,
        schema_description=LEDGER_SCHEMA_DESCRIPTION,
        validate_approval=validate_approval,
    )


__all__ = [
    "DEFAULT_APPROVAL_LEDGER",
    "AuthoredSha256",
    "LEDGER_SCHEMA_DESCRIPTION",
    "SYNTHESIS_DEFAULT_HOME",
    "append_capture_approval_record",
    "capture_approval_record",
    "synthesis_approval_record",
]
