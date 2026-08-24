#!/usr/bin/env python3
"""Public-behavior checks for exact capture proposal preview and application."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from capture_approval_records import LEDGER_SCHEMA_DESCRIPTION
from capture_ledger import (
    validate_capture_application,
    validate_capture_ledger_file,
)
from capture_gate import (
    CaptureProposalError,
    apply_capture_proposal,
    prepare_capture_proposal,
)
from eval_lib import Results


results = Results()
CAPTURE_GATE = Path(__file__).resolve().parent / "capture_gate.py"


missing_proposal = subprocess.run(
    [sys.executable, str(CAPTURE_GATE)],
    capture_output=True,
    text=True,
    check=False,
)
results.record(
    "capture-cli-requires-exact-proposal",
    missing_proposal.returncode == 2 and "--proposal" in missing_proposal.stderr,
)

legacy_cli = subprocess.run(
    [
        sys.executable,
        str(CAPTURE_GATE),
        "--proposal",
        "tmp/none.json",
        "--type",
        "analysis",
    ],
    capture_output=True,
    text=True,
    check=False,
)
results.record(
    "capture-cli-rejects-removed-flat-mode",
    legacy_cli.returncode == 2 and "unrecognized arguments" in legacy_cli.stderr,
)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def make_repo(root: Path, *, existing: bool = False) -> tuple[Path, bytes | None]:
    for directory in ("scripts", "tmp", "wiki/concepts"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    schema = {
        "record_type": "schema",
        "schema_version": 1,
        "description": LEDGER_SCHEMA_DESCRIPTION,
    }
    (root / "scripts/capture-runs.jsonl").write_bytes(canonical_json(schema))
    destination = root / "wiki/concepts/exact.md"
    preimage = b"old\n" if existing else None
    if preimage is not None:
        destination.write_bytes(preimage)
    postimage = b"new exact bytes\n"
    (root / "tmp/exact.md").write_bytes(postimage)
    descriptor = {
        "schema_version": 1,
        "capture_boundary": "artifact-promotion",
        "purpose": "Promote exact fixture",
        "primary_destination": "wiki/concepts/exact.md",
        "editable_scope": ["wiki/concepts/exact.md"],
        "targets": [{
            "destination": "wiki/concepts/exact.md",
            "expected_preimage": "ABSENT" if preimage is None else sha256(preimage),
            "staged_path": "tmp/exact.md",
            "postimage_sha256": sha256(postimage),
        }],
    }
    (root / "tmp/proposal.json").write_bytes(canonical_json(descriptor))
    return root / "tmp/proposal.json", preimage


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    proposal, _ = make_repo(root)
    governed_before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "wiki").rglob("*") if path.is_file()
    }
    ledger_before = (root / "scripts/capture-runs.jsonl").read_bytes()
    with working_directory(root):
        prepared = prepare_capture_proposal(root, proposal.relative_to(root).as_posix())
    governed_after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "wiki").rglob("*") if path.is_file()
    }
    results.record(
        "preview-has-zero-governed-delta",
        governed_before == governed_after
        and (root / "scripts/capture-runs.jsonl").read_bytes() == ledger_before
        and not (root / ".wiki-transactions").exists(),
    )
    preview = prepared["preview"]
    results.record(
        "preview-shows-exact-content-scope-and-digest",
        preview["targets"][0]["content_utf8"] == "new exact bytes\n"
        and preview["editable_scope"] == ["wiki/concepts/exact.md"]
        and preview["authorization_digest"] == prepared["authorization_digest"],
    )

    descriptor = json.loads(proposal.read_text())
    descriptor["purpose"] = "Changed purpose"
    proposal.write_bytes(canonical_json(descriptor))
    with working_directory(root):
        changed = prepare_capture_proposal(root, "tmp/proposal.json")
    results.record(
        "changed-descriptor-requires-new-approval",
        changed["authorization_digest"] != prepared["authorization_digest"],
    )

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    proposal, _ = make_repo(root)
    with working_directory(root):
        digest = prepare_capture_proposal(root, "tmp/proposal.json")["authorization_digest"]
    (root / "tmp/exact.md").write_bytes(b"changed staged bytes\n")
    try:
        with working_directory(root):
            apply_capture_proposal(root, "tmp/proposal.json", digest)
    except CaptureProposalError as exc:
        staged_rejected = "hash mismatch" in str(exc)
    else:
        staged_rejected = False
    results.record("changed-staged-bytes-invalidates-approval", staged_rejected)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    proposal, _ = make_repo(root)
    descriptor = json.loads(proposal.read_text())
    descriptor["primary_destination"] = "scripts/capture-runs.jsonl"
    descriptor["editable_scope"] = ["scripts/capture-runs.jsonl"]
    descriptor["targets"][0]["destination"] = "scripts/capture-runs.jsonl"
    proposal.write_bytes(canonical_json(descriptor))
    try:
        with working_directory(root):
            prepare_capture_proposal(root, "tmp/proposal.json")
    except CaptureProposalError as exc:
        ledger_target_rejected = "system output" in str(exc)
    else:
        ledger_target_rejected = False
    results.record("capture-ledger-cannot-be-a-user-target", ledger_target_rejected)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    proposal, _ = make_repo(root)
    descriptor = json.loads(proposal.read_text())
    malformed_values = (7, [{"not": "a path"}])
    rejected = True
    for malformed in malformed_values:
        descriptor["editable_scope"] = malformed
        proposal.write_bytes(canonical_json(descriptor))
        try:
            with working_directory(root):
                prepare_capture_proposal(root, "tmp/proposal.json")
        except CaptureProposalError:
            pass
        except Exception:
            rejected = False
        else:
            rejected = False
    results.record("malformed-descriptor-types-fail-cleanly", rejected)
    descriptor = json.loads((root / "tmp/proposal.json").read_text())
    descriptor["editable_scope"] = ["wiki/concepts/exact.md"]
    descriptor["capture_boundary"] = []
    proposal.write_bytes(canonical_json(descriptor))
    try:
        with working_directory(root):
            prepare_capture_proposal(root, "tmp/proposal.json")
    except CaptureProposalError:
        malformed_boundary_rejected = True
    except Exception:
        malformed_boundary_rejected = False
    else:
        malformed_boundary_rejected = False
    results.record("malformed-descriptor-boundary-fails-cleanly", malformed_boundary_rejected)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    proposal, _ = make_repo(root, existing=True)
    with working_directory(root):
        digest = prepare_capture_proposal(root, "tmp/proposal.json")["authorization_digest"]
    (root / "wiki/concepts/exact.md").write_bytes(b"third party\n")
    try:
        with working_directory(root):
            apply_capture_proposal(root, "tmp/proposal.json", digest)
    except CaptureProposalError as exc:
        preimage_rejected = "preimage changed" in str(exc)
    else:
        preimage_rejected = False
    results.record(
        "changed-destination-preimage-is-preserved",
        preimage_rejected and (root / "wiki/concepts/exact.md").read_bytes() == b"third party\n",
    )

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    proposal, _ = make_repo(root)
    with working_directory(root):
        prepared = prepare_capture_proposal(root, "tmp/proposal.json")
        outcome = apply_capture_proposal(
            root, "tmp/proposal.json", prepared["authorization_digest"]
        )
        ledger_errors, count = validate_capture_ledger_file(root / "scripts/capture-runs.jsonl")
    first_target = (root / "wiki/concepts/exact.md").read_bytes()
    first_ledger = (root / "scripts/capture-runs.jsonl").read_bytes()
    with working_directory(root):
        retry = apply_capture_proposal(
            root, "tmp/proposal.json", prepared["authorization_digest"]
        )
    results.record(
        "valid-apply-writes-target-and-one-ledger-postimage",
        outcome["result_code"] == "APPLIED"
        and first_target == b"new exact bytes\n"
        and not ledger_errors and count == 1,
    )
    results.record(
        "exact-retry-is-byte-no-op",
        retry["result_code"] == "ALREADY_APPLIED"
        and (root / "wiki/concepts/exact.md").read_bytes() == first_target
        and (root / "scripts/capture-runs.jsonl").read_bytes() == first_ledger,
    )
    records = [json.loads(line) for line in first_ledger.decode().splitlines()]
    application = next(record for record in records if record.get("record_type") == "capture_application")
    malformed_record = {**application, "capture_boundary": []}
    try:
        malformed_record_errors = validate_capture_application(malformed_record)
    except Exception:
        malformed_record_errors = []
    results.record(
        "malformed-ledger-boundary-fails-cleanly",
        any("capture_boundary" in error for error in malformed_record_errors),
    )
    duplicate = {**application, "applied_at": "2099-01-01T00:00:00Z"}
    duplicate_ledger = first_ledger + canonical_json(duplicate)
    (root / "scripts/capture-runs.jsonl").write_bytes(duplicate_ledger)
    with working_directory(root):
        duplicate_errors, _ = validate_capture_ledger_file(root / "scripts/capture-runs.jsonl")
    results.record(
        "duplicate-application-authorization-digest-is-invalid",
        any("duplicate capture application authorization_digest" in error for error in duplicate_errors),
    )

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    proposal, _ = make_repo(root)
    with working_directory(root):
        digest = prepare_capture_proposal(root, "tmp/proposal.json")["authorization_digest"]
        try:
            apply_capture_proposal(
                root,
                "tmp/proposal.json",
                digest,
                fault=lambda event: (_ for _ in ()).throw(RuntimeError("interrupt"))
                if event == "after_target:0" else None,
            )
        except RuntimeError:
            interrupted = True
        else:
            interrupted = False
        recovered = apply_capture_proposal(root, "tmp/proposal.json", digest)
        ledger_errors, count = validate_capture_ledger_file(root / "scripts/capture-runs.jsonl")
    results.record(
        "interrupted-apply-recovers-through-existing-transaction",
        interrupted
        and recovered["result_code"] == "APPLIED"
        and (root / "wiki/concepts/exact.md").read_bytes() == b"new exact bytes\n"
        and not ledger_errors and count == 1,
    )

raise SystemExit(results.finish())
