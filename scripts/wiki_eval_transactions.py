#!/usr/bin/env python3
"""Focused recovery checks for exact capture and setup file transactions."""

from __future__ import annotations

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


with tempfile.TemporaryDirectory(prefix="wiki-transaction-delete-") as directory:
    root = Path(directory)
    (root / "data").mkdir()
    target = root / "data/remove.txt"
    target.write_bytes(b"remove-me")
    run_transaction(
        root,
        consumer="wiki-setup",
        outputs={"data/remove.txt": None},
        expected_preimages={"data/remove.txt": b"remove-me"},
        allowed_prefixes=("data",),
    )
    clean, reports = transaction_status(root)
    results.record(
        "setup-transaction-installs-absent-postimage",
        clean and not reports and not target.exists(),
        repr(reports),
    )


with tempfile.TemporaryDirectory(prefix="wiki-transaction-delete-recovery-") as directory:
    root = Path(directory)
    (root / "data").mkdir()
    target = root / "data/a-remove.txt"
    second = root / "data/b-change.txt"
    target.write_bytes(b"remove-me")
    second.write_bytes(b"old")
    try:
        run_transaction(
            root,
            consumer="wiki-setup",
            outputs={"data/a-remove.txt": None, "data/b-change.txt": b"new"},
            expected_preimages={
                "data/a-remove.txt": b"remove-me",
                "data/b-change.txt": b"old",
            },
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_target:0" else None,
        )
    except RuntimeError:
        pass
    messages = recover_all(root)
    clean, reports = transaction_status(root)
    results.record(
        "interrupted-setup-deletion-rolls-back",
        clean
        and not reports
        and target.read_bytes() == b"remove-me"
        and second.read_bytes() == b"old"
        and bool(messages),
        f"messages={messages} reports={reports}",
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
        "transaction-engine-rejects-noncapture-consumers",
        rejected,
        "noncapture consumer was accepted" if not rejected else "",
    )


raise SystemExit(results.finish())
