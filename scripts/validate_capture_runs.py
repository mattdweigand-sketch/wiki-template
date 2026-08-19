#!/usr/bin/env python3
"""Validate the structured approval ledger."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ledger_common import (
    APPROVAL_RECORD_TYPES,
    is_nonempty_string,
    is_strict_int,
    validate_ledger,
    validate_pages as _validate_pages,
    validate_timestamp,
)


DEFAULT_LEDGER = Path("scripts/capture-runs.jsonl")
VALID_ROUTES = {"analysis-capture", "promotion-audit"}
VALID_PHASES = {"accepted"}
VALID_TRIGGERS = {
    "reusable_distinction",
    "ranking_or_framework",
    "open_question_resolution",
    "future_agent_behavior",
    "existing_page_update",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# One second after the last pre-commissioning live record
# (2026-07-08T17:11:13Z).
DRAFT_SHA256_REQUIRED_FROM = "2026-07-08T17:11:14Z"
# One second after the latest live approval at Phase-3 commissioning time.
AUTHORED_SHA256_REQUIRED_FROM = "2026-07-10T03:23:58Z"
AUTHORED_HASH_POLICY = "strip_referenced_by_v1"


def parse_utc_timestamp(value: object) -> datetime | None:
    if not is_nonempty_string(value):
        return None
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


DRAFT_SHA256_REQUIRED_FROM_DT = parse_utc_timestamp(DRAFT_SHA256_REQUIRED_FROM)
if DRAFT_SHA256_REQUIRED_FROM_DT is None:
    # A plain raise, not assert: python -O strips asserts, which would leave
    # the cutoff None and turn every timestamp comparison into a TypeError.
    raise RuntimeError(
        f"DRAFT_SHA256_REQUIRED_FROM is not a parseable timestamp: {DRAFT_SHA256_REQUIRED_FROM!r}"
    )
AUTHORED_SHA256_REQUIRED_FROM_DT = parse_utc_timestamp(AUTHORED_SHA256_REQUIRED_FROM)
if AUTHORED_SHA256_REQUIRED_FROM_DT is None:
    raise RuntimeError(
        "AUTHORED_SHA256_REQUIRED_FROM is not a parseable timestamp: "
        f"{AUTHORED_SHA256_REQUIRED_FROM!r}"
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Validate scripts/capture-runs.jsonl.")
    p.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_LEDGER),
        help="JSONL approval ledger to validate.",
    )
    return p


def validate_backfill_fields(record: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if record.get("backfilled") is True and not is_nonempty_string(record.get("backfill_source")):
        errors.append("backfilled records must include backfill_source")
    if "backfilled" in record and not isinstance(record.get("backfilled"), bool):
        errors.append("backfilled must be a boolean when present")
    return errors


def validate_capture_approval(record: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if not is_strict_int(record.get("schema_version")) or record["schema_version"] != 1:
        errors.append("approval record must have schema_version 1")
    if record.get("approval_status") != "approved":
        errors.append("approval_status must be approved")
    for key in ("artifact", "primary_home"):
        if not is_nonempty_string(record.get(key)):
            errors.append(f"{key} must be a non-empty string")

    route = record.get("route")
    if not isinstance(route, str) or route not in VALID_ROUTES:
        errors.append(f"route must be one of {sorted(VALID_ROUTES)}")
    phase = record.get("phase")
    if not isinstance(phase, str) or phase not in VALID_PHASES:
        errors.append("phase must be accepted for capture approvals")

    errors.extend(_validate_pages(record, repo_root=Path.cwd()))

    timestamp_error = validate_timestamp(record.get("approved_at"))
    approved_at = parse_utc_timestamp(record.get("approved_at"))
    if timestamp_error:
        errors.append(timestamp_error)

    synthesized_pages = record.get("synthesized_pages")
    word_count = record.get("word_count")
    domain_context = record.get("domain_context")
    triggers = record.get("triggers")
    if not is_strict_int(synthesized_pages) or synthesized_pages < 0:
        errors.append("synthesized_pages must be a non-negative integer")
    if not is_strict_int(word_count) or word_count < 0:
        errors.append("word_count must be a non-negative integer")
    # Measurement provenance; pre-cutoff historical values remain compatible.
    word_count_source = record.get("word_count_source")
    word_count_path = record.get("word_count_path")
    draft_sha256 = record.get("draft_sha256")
    if "word_count_path" in record and not isinstance(record.get("word_count_path"), str):
        errors.append("word_count_path must be a string when present")
    if "draft_sha256" in record:
        if not isinstance(draft_sha256, str) or not SHA256_RE.fullmatch(draft_sha256):
            errors.append("draft_sha256 must be 64 lowercase hex characters when present")
    pages_touched = record.get("pages_touched")
    primary_home = record.get("primary_home")
    analyses_targeting = (
        route == "analysis-capture"
        or (
            isinstance(primary_home, str)
            and primary_home.casefold().startswith("wiki/analyses/")
        )
        or (
        isinstance(pages_touched, list)
        and any(
            isinstance(path, str)
            and path.casefold().startswith("wiki/analyses/")
            for path in pages_touched
        )
        )
    )
    commissioned_measurement = (
        approved_at is not None and approved_at >= DRAFT_SHA256_REQUIRED_FROM_DT
    )
    if commissioned_measurement:
        if not isinstance(word_count_source, str) or word_count_source not in {
            "measured", "unmeasured"
        }:
            errors.append("word_count_source must be measured or unmeasured")
        if word_count_source == "measured":
            if not is_nonempty_string(word_count_path):
                errors.append("measured capture approvals require nonempty word_count_path")
            if not isinstance(draft_sha256, str) or not SHA256_RE.fullmatch(draft_sha256):
                errors.append("measured capture approvals require a valid draft_sha256")
        elif word_count_source == "unmeasured":
            if not isinstance(word_count_path, str) or word_count_path != "":
                errors.append("unmeasured capture approvals require empty word_count_path")
            if "draft_sha256" in record:
                errors.append("unmeasured capture approvals must not carry draft_sha256")
        if analyses_targeting and word_count_source != "measured":
            errors.append(
                "analyses-targeting capture approvals must use measured provenance"
            )

    authored_sha256 = record.get("authored_sha256")
    authored_policy = record.get("authored_hash_policy")
    if "authored_sha256" in record and (
        not isinstance(authored_sha256, str) or not SHA256_RE.fullmatch(authored_sha256)
    ):
        errors.append("authored_sha256 must be 64 lowercase hex characters when present")
    if "authored_hash_policy" in record and authored_policy != AUTHORED_HASH_POLICY:
        errors.append(f"authored_hash_policy must be {AUTHORED_HASH_POLICY}")
    if ("authored_sha256" in record) != ("authored_hash_policy" in record):
        errors.append("authored_sha256 and authored_hash_policy must be present together")
    commissioned_authored = (
        approved_at is not None and approved_at >= AUTHORED_SHA256_REQUIRED_FROM_DT
    )
    if commissioned_authored and analyses_targeting:
        if not isinstance(authored_sha256, str) or not SHA256_RE.fullmatch(authored_sha256):
            errors.append("authored_sha256 is required for commissioned analyses-targeting approvals")
        if authored_policy != AUTHORED_HASH_POLICY:
            errors.append(
                "commissioned analyses-targeting approvals require "
                f"authored_hash_policy {AUTHORED_HASH_POLICY}"
            )
    if not isinstance(domain_context, bool):
        errors.append("domain_context must be a boolean")
    if not isinstance(triggers, list) or not all(
        isinstance(trigger, str) and trigger in VALID_TRIGGERS
        for trigger in triggers
    ):
        errors.append("triggers must be a list of valid promotion triggers")
    elif commissioned_measurement and triggers != sorted(set(triggers)):
        errors.append("triggers must be sorted and unique for new approvals")

    if route == "analysis-capture":
        if not (
            is_strict_int(synthesized_pages)
            and synthesized_pages >= 3
            and is_strict_int(word_count)
            and word_count > 300
            and domain_context is True
        ):
            errors.append("analysis-capture records must meet the 3+ pages, >300 words, domain-context criteria")
    if route == "promotion-audit" and triggers == []:
        errors.append("promotion-audit records must include at least one trigger")

    errors.extend(validate_backfill_fields(record))
    return errors


def validate_synthesis_approval(record: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if not is_strict_int(record.get("schema_version")) or record["schema_version"] != 1:
        errors.append("approval record must have schema_version 1")
    if record.get("approval_status") != "approved":
        errors.append("approval_status must be approved")
    for key in ("artifact", "drafts", "primary_home"):
        if not is_nonempty_string(record.get(key)):
            errors.append(f"{key} must be a non-empty string")

    capture_only = (
        "word_count_source",
        "word_count_path",
        "draft_sha256",
        "authored_sha256",
        "authored_hash_policy",
    )
    present_capture_fields = [key for key in capture_only if key in record]
    if present_capture_fields:
        errors.append(
            "synthesis approvals must not carry capture measurement fields: "
            f"{present_capture_fields}"
        )

    pages_touched = record.get("pages_touched")
    errors.extend(_validate_pages(record, repo_root=Path.cwd()))

    timestamp_error = validate_timestamp(record.get("approved_at"))
    if timestamp_error:
        errors.append(timestamp_error)

    if isinstance(pages_touched, list) and record.get("primary_home") == "wiki/synthesis.md":
        if record.get("ledger_update_required") is not True:
            errors.append("wiki/synthesis.md primary_home requires ledger_update_required true")
    if record.get("primary_home") != "wiki/synthesis.md" and record.get("ledger_update_required") is True:
        errors.append("ledger_update_required must be false unless primary_home is wiki/synthesis.md")

    if "ledger_update_required" not in record or not isinstance(record.get("ledger_update_required"), bool):
        errors.append("ledger_update_required must be a boolean")

    errors.extend(validate_backfill_fields(record))
    return errors


def validate_approval(record: dict[str, object]) -> list[str]:
    if record.get("record_type") == "capture_approval":
        return validate_capture_approval(record)
    if record.get("record_type") == "synthesis_approval":
        return validate_synthesis_approval(record)
    return [f"unsupported record_type {record.get('record_type')!r}"]


def validate_capture_ledger(path: Path) -> tuple[list[str], int]:
    """Validate a complete approval ledger through its shared trust boundary."""
    return validate_ledger(path, APPROVAL_RECORD_TYPES, validate_approval)


def main() -> int:
    args = parser().parse_args()
    errors, approval_count = validate_capture_ledger(Path(args.path))
    if errors:
        print("Approval ledger validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Approval ledger validation passed: {approval_count} approved record(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
