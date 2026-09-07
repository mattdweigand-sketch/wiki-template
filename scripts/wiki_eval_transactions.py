#!/usr/bin/env python3
"""Focused recovery checks for exact capture file transactions."""

from __future__ import annotations

import hashlib
import json
import stat
import tempfile
from pathlib import Path

from _file_transactions import (
    AUTHORITY_NAME,
    TransactionConflict,
    TransactionError,
    recover_all,
    run_transaction,
    transaction_status,
)
from eval_lib import Results


results = Results()


def install_transaction_fixture(root: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Create the two-file capture application fixture."""
    (root / "data").mkdir()
    (root / "data/a.txt").write_bytes(b"old-a")
    (root / "data/b.txt").write_bytes(b"old-b")
    return (
        {"data/a.txt": b"new-a", "data/b.txt": b"new-b"},
        {"data/a.txt": b"old-a", "data/b.txt": b"old-b"},
    )


def transaction_files(root: Path) -> tuple[bytes, bytes]:
    """Read the exact two-file application state."""
    return (
        (root / "data/a.txt").read_bytes(),
        (root / "data/b.txt").read_bytes(),
    )


def install_historical_deletion_journal(
    root: Path,
    *,
    state: str,
    applied_paths: set[str],
) -> None:
    """Install an old schema-2 crash snapshot without using transaction creation."""
    _outputs, preimages = install_transaction_fixture(root)
    historical_outputs = {"data/a.txt": None, "data/b.txt": b"new-b"}
    pre_modes = {"data/a.txt": 0o600, "data/b.txt": 0o640}
    transaction_id = "00000000-0000-4000-8000-000000000001"
    transaction_directory = root / AUTHORITY_NAME / transaction_id
    (root / AUTHORITY_NAME).mkdir(mode=0o700)
    transaction_directory.mkdir(mode=0o700)
    (transaction_directory / "blobs").mkdir(mode=0o700)
    targets = []
    for index, (relative, output) in enumerate(historical_outputs.items()):
        path = root / relative
        path.chmod(pre_modes[relative])
        target = {
            "path": relative,
            "pre_state": "regular",
            "pre_sha256": hashlib.sha256(preimages[relative]).hexdigest(),
            "pre_mode": pre_modes[relative],
            "pre_blob": f"blobs/pre-{index:04d}.bin",
            "output_state": "absent" if output is None else "regular",
            "output_sha256": None if output is None else hashlib.sha256(output).hexdigest(),
            "output_mode": None if output is None else pre_modes[relative],
            "output_blob": None if output is None else f"blobs/output-{index:04d}.bin",
            "installed": relative in applied_paths and (
                state != "COMMITTING" or relative != max(applied_paths)
            ),
        }
        targets.append(target)
        for blob_name, content in ((target["pre_blob"], preimages[relative]), (target["output_blob"], output)):
            if blob_name is not None:
                blob_path = transaction_directory / blob_name
                blob_path.write_bytes(content)
                blob_path.chmod(0o600)
        if relative in applied_paths:
            if output is None:
                path.unlink()
            else:
                path.write_bytes(output)
    # Keep the historical hash projection independent of current production helpers.
    plan = {
        "consumer": "capture-gate", "allowed_prefixes": ["data"], "guards": [],
        "targets": [{key: target[key] for key in (
            "path", "pre_state", "pre_sha256", "pre_mode", "output_state", "output_sha256", "output_mode",
        )} for target in targets],
    }
    journal = {
        "schema_version": 2, "transaction_id": transaction_id, "consumer": "capture-gate",
        "created_at": "2026-08-01T00:00:00Z", "updated_at": "2026-08-01T00:00:00Z",
        "repo_root": str(root.resolve()), "repo_device": root.stat().st_dev,
        "state": state, "generation": 3, "allowed_prefixes": ["data"],
        "plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "targets": targets, "guards": [],
    }
    journal["integrity_sha256"] = hashlib.sha256(
        json.dumps(journal, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    journal_path = transaction_directory / "journal.json"
    journal_path.write_text(json.dumps(journal, indent=2) + "\n")
    journal_path.chmod(0o600)


with tempfile.TemporaryDirectory(prefix="wiki-transaction-clean-") as directory:
    root = Path(directory)
    clean, reports = transaction_status(root)
    results.record(
        "absent-transaction-authority-is-clean",
        clean and not reports and not (root / AUTHORITY_NAME).exists(),
        repr(reports),
    )


with tempfile.TemporaryDirectory(prefix="wiki-transaction-success-") as directory:
    root = Path(directory)
    outputs, preimages = install_transaction_fixture(root)
    run_transaction(
        root,
        consumer="capture-gate",
        outputs=outputs,
        expected_preimages=preimages,
        allowed_prefixes=("data",),
    )
    clean, reports = transaction_status(root)
    results.record(
        "capture-transaction-installs-complete-generation",
        clean and not reports and transaction_files(root) == (b"new-a", b"new-b"),
        repr(reports),
    )


def record_transaction_recovery_case(
    name: str,
    stop_event: str,
    expected: tuple[bytes, bytes],
) -> None:
    """Interrupt one capture generation and verify deterministic recovery."""
    with tempfile.TemporaryDirectory(prefix="wiki-transaction-recovery-") as directory:
        root = Path(directory)
        outputs, preimages = install_transaction_fixture(root)
        try:
            run_transaction(
                root,
                consumer="capture-gate",
                outputs=outputs,
                expected_preimages=preimages,
                allowed_prefixes=("data",),
                fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
                if event == stop_event else None,
            )
        except RuntimeError:
            pass
        messages = recover_all(root)
        clean, reports = transaction_status(root)
        results.record(
            name,
            clean and not reports and transaction_files(root) == expected and bool(messages),
            f"messages={messages} reports={reports}",
        )


record_transaction_recovery_case(
    "partial-capture-generation-rolls-back",
    "after_target:0",
    (b"old-a", b"old-b"),
)
record_transaction_recovery_case(
    "complete-capture-generation-finishes-forward",
    "after_target:1",
    (b"new-a", b"new-b"),
)


with tempfile.TemporaryDirectory(prefix="wiki-transaction-conflict-") as directory:
    root = Path(directory)
    outputs, preimages = install_transaction_fixture(root)

    def add_third_party_edit(event: str) -> None:
        if event == "after_target:0":
            (root / "data/b.txt").write_bytes(b"third-party")
            raise RuntimeError("stop")

    try:
        run_transaction(
            root,
            consumer="capture-gate",
            outputs=outputs,
            expected_preimages=preimages,
            allowed_prefixes=("data",),
            fault=add_third_party_edit,
        )
    except RuntimeError:
        pass
    try:
        recover_all(root)
    except TransactionConflict:
        conflicted = True
    else:
        conflicted = False
    clean, reports = transaction_status(root)
    results.record(
        "third-party-edit-blocks-capture-recovery",
        conflicted and not clean and (root / "data/b.txt").read_bytes() == b"third-party",
        repr(reports),
    )


with tempfile.TemporaryDirectory(prefix="wiki-transaction-consumer-") as directory:
    root = Path(directory)
    outputs, preimages = install_transaction_fixture(root)
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs=outputs,
            expected_preimages=preimages,
            allowed_prefixes=("data",),
        )
    except TransactionError:
        rejected = True
    else:
        rejected = False
    results.record(
        "transaction-engine-rejects-unknown-consumers",
        rejected,
        "noncapture consumer was accepted" if not rejected else "",
    )


for label, invalid_output in (("deletion", None), ("text", "not bytes")):
    with tempfile.TemporaryDirectory(prefix="wiki-transaction-invalid-output-") as directory:
        root = Path(directory)
        outputs, preimages = install_transaction_fixture(root)
        try:
            run_transaction(
                root, consumer="capture-gate", outputs={**outputs, "data/a.txt": invalid_output},
                expected_preimages=preimages, allowed_prefixes=("data",),
            )
        except TransactionError as exc:
            rejected = "must be bytes" in str(exc)
        else:
            rejected = False
        results.record("new-transaction-rejects-" + label + "-before-writes", rejected
                       and transaction_files(root) == (b"old-a", b"old-b")
                       and not (root / AUTHORITY_NAME).exists())


for label, state, applied_paths, expected_a, expected_b in (
    ("prepared", "PREPARED", set(), b"old-a", b"old-b"),
    ("partial", "COMMITTING", {"data/a.txt"}, b"old-a", b"old-b"),
    ("complete", "COMMITTING", {"data/a.txt", "data/b.txt"}, None, b"new-b"),
    ("committed", "COMMITTED", {"data/a.txt", "data/b.txt"}, None, b"new-b"),
):
    with tempfile.TemporaryDirectory(prefix="wiki-historical-deletion-") as directory:
        root = Path(directory)
        install_historical_deletion_journal(root, state=state, applied_paths=applied_paths)
        clean_before, reports_before = transaction_status(root)
        messages = recover_all(root)
        clean_after, reports_after = transaction_status(root)
        a = root / "data/a.txt"
        b = root / "data/b.txt"
        observed_a = a.read_bytes() if a.exists() else None
        modes_match = (not a.exists() or stat.S_IMODE(a.stat().st_mode) == 0o600)
        modes_match = modes_match and stat.S_IMODE(b.stat().st_mode) == 0o640
        results.record("historical-deletion-" + label + "-recovers", not clean_before
                       and not any("CORRUPT" in report for report in reports_before)
                       and bool(messages) and clean_after and not reports_after
                       and observed_a == expected_a and b.read_bytes() == expected_b and modes_match,
                       f"before={reports_before} messages={messages} after={reports_after}")


with tempfile.TemporaryDirectory(prefix="wiki-historical-deletion-conflict-") as directory:
    root = Path(directory)
    install_historical_deletion_journal(root, state="COMMITTING", applied_paths={"data/a.txt"})
    (root / "data/a.txt").write_bytes(b"third-party recreation")
    try:
        recover_all(root)
    except TransactionConflict:
        rejected = True
    else:
        rejected = False
    clean, reports = transaction_status(root)
    results.record("historical-deletion-preserves-third-party-recreation", rejected and not clean
                   and (root / "data/a.txt").read_bytes() == b"third-party recreation"
                   and (root / "data/b.txt").read_bytes() == b"old-b", repr(reports))


raise SystemExit(results.finish())
