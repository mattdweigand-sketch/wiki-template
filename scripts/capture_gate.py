#!/usr/bin/env python3
"""Preview or apply one exact approved wiki capture proposal."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Callable

from _durable_files import DurableFileError, read_regular_bytes, sha256_bytes
from _file_transactions import recover_all, run_transaction
from _repo_paths import EXISTING_FILE, MAY_CREATE_FILE, RepoPathError, resolve_repo_path
from _transaction_contract import TransactionError
from capture_approval_records import (
    capture_application_from_ledger,
    capture_application_record,
    render_capture_application_ledger,
)
from capture_ledger import (
    ALLOWED_CAPTURE_ROOT_FILES,
    ALLOWED_CAPTURE_ROOTS,
    CaptureLedgerIntegrityError,
)


PROPOSAL_FIELDS = {
    "schema_version", "capture_boundary", "purpose", "primary_destination",
    "editable_scope", "targets",
}
PROPOSAL_TARGET_FIELDS = {
    "destination", "expected_preimage", "staged_path", "postimage_sha256",
}
PROPOSAL_BOUNDARIES = {
    "analysis-capture", "artifact-promotion", "synthesis-promotion",
}
CAPTURE_LEDGER_PATH = "scripts/capture-runs.jsonl"


class CaptureProposalError(ValueError):
    """An exact capture proposal failed deterministic validation."""


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise CaptureProposalError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def _utf8_or_none(value: bytes) -> str | None:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _capture_proposal_path(repo_root: Path, path: str, *, existing: bool) -> str:
    return resolve_repo_path(
        path,
        repo_root=repo_root,
        allowed_prefixes=("tmp",),
        mode=EXISTING_FILE if existing else MAY_CREATE_FILE,
    )


def prepare_capture_proposal(repo_root: Path, descriptor_path: str) -> dict[str, object]:
    """Validate one canonical descriptor and bind its exact staged postimages."""
    root = repo_root.resolve()
    descriptor_relative = _capture_proposal_path(root, descriptor_path, existing=True)
    descriptor_bytes, _ = read_regular_bytes(root / descriptor_relative)
    assert descriptor_bytes is not None
    try:
        descriptor = json.loads(
            descriptor_bytes.decode("utf-8"), object_pairs_hook=_strict_json_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError, CaptureProposalError) as exc:
        raise CaptureProposalError(f"invalid proposal descriptor: {exc}") from exc
    if not isinstance(descriptor, dict) or set(descriptor) != PROPOSAL_FIELDS:
        raise CaptureProposalError("proposal descriptor has missing or unknown fields")
    if descriptor_bytes != _canonical_json_bytes(descriptor):
        raise CaptureProposalError("proposal descriptor must be canonical JSON with one trailing LF")
    if descriptor.get("schema_version") != 1 or isinstance(descriptor.get("schema_version"), bool):
        raise CaptureProposalError("schema_version must be integer 1")
    capture_boundary = descriptor.get("capture_boundary")
    if not isinstance(capture_boundary, str) or capture_boundary not in PROPOSAL_BOUNDARIES:
        raise CaptureProposalError(f"capture_boundary must be one of {sorted(PROPOSAL_BOUNDARIES)}")
    if not isinstance(descriptor.get("purpose"), str) or not descriptor["purpose"].strip():
        raise CaptureProposalError("purpose must be a non-empty string")

    scope = descriptor.get("editable_scope")
    if (
        not isinstance(scope, list)
        or not scope
        or not all(isinstance(path, str) and path for path in scope)
        or scope != sorted(set(scope))
    ):
        raise CaptureProposalError("editable_scope must be a non-empty sorted unique list")
    if CAPTURE_LEDGER_PATH in scope:
        raise CaptureProposalError(
            f"{CAPTURE_LEDGER_PATH} is a system output and cannot be a proposal target"
        )
    allowed_prefixes = tuple(
        prefix.rstrip("/") for prefix in ALLOWED_CAPTURE_ROOTS
    )
    for destination in scope:
        resolve_repo_path(
            destination,
            repo_root=root,
            allowed_prefixes=allowed_prefixes,
            allowed_root_files=ALLOWED_CAPTURE_ROOT_FILES,
            mode=MAY_CREATE_FILE,
        )
    primary = descriptor.get("primary_destination")
    if not isinstance(primary, str) or primary not in scope:
        raise CaptureProposalError("primary_destination must name one editable_scope path")

    raw_targets = descriptor.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise CaptureProposalError("targets must be a non-empty list")
    prepared_targets: list[dict[str, object]] = []
    for index, target in enumerate(raw_targets):
        if not isinstance(target, dict) or set(target) != PROPOSAL_TARGET_FIELDS:
            raise CaptureProposalError(f"targets[{index}] has missing or unknown fields")
        destination = target.get("destination")
        if not isinstance(destination, str):
            raise CaptureProposalError(f"targets[{index}].destination must be a string")
        staged_path = target.get("staged_path")
        if not isinstance(staged_path, str):
            raise CaptureProposalError(f"targets[{index}].staged_path must be a string")
        staged_relative = _capture_proposal_path(root, staged_path, existing=True)
        staged_bytes, _ = read_regular_bytes(root / staged_relative)
        assert staged_bytes is not None
        postimage_sha = target.get("postimage_sha256")
        if not isinstance(postimage_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", postimage_sha):
            raise CaptureProposalError(f"targets[{index}].postimage_sha256 must be lowercase SHA-256")
        if sha256_bytes(staged_bytes) != postimage_sha:
            raise CaptureProposalError(f"staged postimage hash mismatch: {staged_relative}")
        expected = target.get("expected_preimage")
        if expected != "ABSENT" and (
            not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
        ):
            raise CaptureProposalError(f"targets[{index}].expected_preimage must be ABSENT or lowercase SHA-256")
        prepared_targets.append({
            "destination": destination,
            "expected_preimage": expected,
            "staged_path": staged_relative,
            "postimage_sha256": postimage_sha,
            "postimage": staged_bytes,
        })
    destinations = [str(target["destination"]) for target in prepared_targets]
    if destinations != sorted(set(destinations)) or destinations != scope:
        raise CaptureProposalError("sorted unique target destinations must exactly match editable_scope")

    projection = {
        "descriptor": descriptor,
        "postimages": [
            {
                "destination": target["destination"],
                "bytes_base64": base64.b64encode(target["postimage"]).decode("ascii"),
            }
            for target in prepared_targets
        ],
    }
    digest = sha256_bytes(_canonical_json_bytes(projection))
    return {
        "descriptor_path": descriptor_relative,
        "descriptor_bytes": descriptor_bytes,
        "descriptor": descriptor,
        "targets": prepared_targets,
        "authorization_digest": digest,
        "preview": {
            "result_code": "APPROVAL_REQUIRED",
            "authorization_digest": digest,
            "capture_boundary": descriptor["capture_boundary"],
            "purpose": descriptor["purpose"],
            "primary_destination": primary,
            "editable_scope": scope,
            "targets": [
                {
                    "destination": target["destination"],
                    "expected_preimage": target["expected_preimage"],
                    "postimage_sha256": target["postimage_sha256"],
                    "content_utf8": _utf8_or_none(target["postimage"]),
                    "bytes_base64": base64.b64encode(target["postimage"]).decode("ascii"),
                }
                for target in prepared_targets
            ],
        },
    }


def apply_capture_proposal(
    repo_root: Path,
    descriptor_path: str,
    approved_digest: str,
    *,
    fault: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Apply exact approved targets plus their ledger record in one transaction."""
    root = repo_root.resolve()
    prepared = prepare_capture_proposal(root, descriptor_path)
    digest = str(prepared["authorization_digest"])
    if approved_digest != digest:
        raise CaptureProposalError(f"approved digest does not match current Authorization ID: {digest}")
    recover_all(root)
    descriptor = prepared["descriptor"]
    targets = prepared["targets"]
    assert isinstance(descriptor, dict) and isinstance(targets, list)
    ledger_path = root / CAPTURE_LEDGER_PATH
    ledger_bytes, _ = read_regular_bytes(ledger_path)
    assert ledger_bytes is not None
    prior = capture_application_from_ledger(ledger_bytes, digest)
    target_states: dict[str, bytes | None] = {}
    for target in targets:
        destination = str(target["destination"])
        current, _ = read_regular_bytes(root / destination, allow_missing=True)
        target_states[destination] = current
    record_targets = [
        {
            "path": target["destination"],
            "preimage_sha256": (
                None if target["expected_preimage"] == "ABSENT" else target["expected_preimage"]
            ),
            "postimage_sha256": target["postimage_sha256"],
        }
        for target in targets
    ]
    expected_record = {
        "authorization_digest": digest,
        "capture_boundary": descriptor["capture_boundary"],
        "purpose": descriptor["purpose"],
        "primary_destination": descriptor["primary_destination"],
        "editable_scope": descriptor["editable_scope"],
        "targets": record_targets,
    }
    if prior is not None:
        comparable = {key: prior.get(key) for key in expected_record}
        outputs_match = all(
            target_states[str(target["destination"])] == target["postimage"]
            for target in targets
        )
        if comparable == expected_record and outputs_match:
            return {"result_code": "ALREADY_APPLIED", "authorization_digest": digest}
        raise CaptureProposalError("authorization ledger record exists but applied targets differ")

    expected_preimages: dict[str, bytes | None] = {}
    outputs: dict[str, bytes] = {}
    for target in targets:
        destination = str(target["destination"])
        current = target_states[destination]
        expected = target["expected_preimage"]
        if expected == "ABSENT":
            if current is not None:
                raise CaptureProposalError(f"destination preimage changed: {destination}")
        elif current is None or sha256_bytes(current) != expected:
            raise CaptureProposalError(f"destination preimage changed: {destination}")
        expected_preimages[destination] = current
        outputs[destination] = target["postimage"]

    record = capture_application_record(**expected_record)
    projected_ledger = render_capture_application_ledger(ledger_bytes, record)
    outputs[CAPTURE_LEDGER_PATH] = projected_ledger
    expected_preimages[CAPTURE_LEDGER_PATH] = ledger_bytes
    guard_preimages = {str(prepared["descriptor_path"]): prepared["descriptor_bytes"]}
    guard_preimages.update({
        str(target["staged_path"]): target["postimage"] for target in targets
    })
    run_transaction(
        root,
        consumer="capture-gate",
        outputs=outputs,
        allowed_prefixes=tuple(sorted({*outputs, *guard_preimages})),
        expected_preimages=expected_preimages,
        guard_preimages=guard_preimages,
        fault=fault,
    )
    return {
        "result_code": "APPLIED",
        "authorization_digest": digest,
        "targets": sorted(outputs),
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Preview or apply one exact approved wiki capture proposal.",
    )
    p.add_argument(
        "--proposal",
        required=True,
        help="Canonical exact-application descriptor under tmp/.",
    )
    p.add_argument(
        "--approve-digest",
        default="",
        help="Exact authorization digest approved after proposal preview.",
    )
    p.add_argument("--json", action="store_true", help="Emit canonical JSON only.")
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        if args.approve_digest:
            payload = apply_capture_proposal(
                Path(__file__).resolve().parents[1],
                args.proposal,
                args.approve_digest,
            )
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            return 0
        prepared = prepare_capture_proposal(
            Path(__file__).resolve().parents[1], args.proposal
        )
        print(json.dumps(prepared["preview"], sort_keys=True, separators=(",", ":")))
        if not args.json:
            print(f"Authorization ID: {prepared['authorization_digest']}")
        return 2
    except (
        CaptureProposalError,
        DurableFileError,
        RepoPathError,
        CaptureLedgerIntegrityError,
        TransactionError,
    ) as exc:
        print(f"capture proposal blocked: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
