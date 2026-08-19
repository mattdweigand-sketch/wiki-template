#!/usr/bin/env python3
"""Crash, recovery, conflict, and corruption evals for file transactions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import _file_transactions as transactions
from _file_transactions import (
    AUTHORITY_NAME,
    TransactionConflict,
    TransactionCorrupt,
    TransactionError,
    recover_all,
    run_transaction,
    transaction_status,
    validate_journal,
)
from _transaction_contract import TRANSACTION_EXECUTION_CONTRACT
from eval_lib import Results
from _durable_files import stable_lock


REPO_ROOT = Path(__file__).resolve().parents[1]
results = Results()


def setup_repo(root: Path) -> tuple[dict[str, bytes], dict[str, bytes | None]]:
    (root / "data").mkdir()
    (root / "data/a.txt").write_bytes(b"old-a")
    (root / "data/b.txt").write_bytes(b"old-b")
    return (
        {"data/a.txt": b"new-a", "data/b.txt": b"new-b"},
        {"data/a.txt": b"old-a", "data/b.txt": b"old-b"},
    )


def tx_dirs(root: Path) -> list[Path]:
    authority = root / AUTHORITY_NAME
    return [path for path in authority.iterdir() if path.name != ".lock"] if authority.exists() else []


with tempfile.TemporaryDirectory(prefix="wiki-transactions-clean-") as td:
    root = Path(td)
    clean, reports = transaction_status(root)
    results.record("absent-authority-is-clean-and-not-created", clean and not reports and not (root / AUTHORITY_NAME).exists(), f"reports={reports}")


with tempfile.TemporaryDirectory(prefix="wiki-transactions-success-") as td:
    root = Path(td)
    outputs, preimages = setup_repo(root)
    recovery = run_transaction(
        root, consumer="rotate-log", outputs=outputs, expected_preimages=preimages, allowed_prefixes=("data",)
    )
    clean, reports = transaction_status(root)
    results.record(
        "successful-transaction-installs-complete-generation",
        recovery == [] and clean and not reports and (root / "data/a.txt").read_bytes() == b"new-a" and (root / "data/b.txt").read_bytes() == b"new-b" and not tx_dirs(root),
        f"recovery={recovery} reports={reports}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-absent-rollback-") as td:
    root = Path(td)
    (root / "data").mkdir()
    (root / "data/b.txt").write_bytes(b"old-b")
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs={"data/0.txt": b"new-zero", "data/b.txt": b"new-b"},
            expected_preimages={"data/0.txt": None, "data/b.txt": b"old-b"},
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_target:0" else None,
        )
    except RuntimeError:
        pass
    messages = recover_all(root)
    clean, reports = transaction_status(root)
    results.record(
        "rollback-durably-restores-absent-prestate",
        clean
        and not (root / "data/0.txt").exists()
        and (root / "data/b.txt").read_bytes() == b"old-b",
        f"messages={messages} reports={reports}",
    )


def fault_case(
    event: str,
    expected_after_recovery: tuple[bytes, bytes],
    recovery_fragment: str,
    *,
    may_finish_before_fault: bool = False,
) -> None:
    with tempfile.TemporaryDirectory(prefix="wiki-transactions-fault-") as td:
        root = Path(td)
        outputs, preimages = setup_repo(root)
        try:
            run_transaction(
                root,
                consumer="rotate-log",
                outputs=outputs,
                expected_preimages=preimages,
                allowed_prefixes=("data",),
                fault=lambda current: (_ for _ in ()).throw(RuntimeError(event)) if current == event else None,
            )
        except RuntimeError:
            faulted = True
        else:
            faulted = False
        before_clean, _ = transaction_status(root)
        try:
            messages = recover_all(root)
            recovered = True
        except TransactionError as exc:
            messages = [str(exc)]
            recovered = False
        after_clean, reports = transaction_status(root)
        observed = ((root / "data/a.txt").read_bytes(), (root / "data/b.txt").read_bytes())
        results.record(
            f"fault-{event.replace(':', '-')}-recovers",
            faulted
            and (may_finish_before_fault or not before_clean)
            and recovered
            and after_clean
            and observed == expected_after_recovery
            and (
                may_finish_before_fault
                or any(recovery_fragment in message for message in messages)
            ),
            f"messages={messages} reports={reports} observed={observed}",
        )


fault_case("after_journal:PREPARING", (b"old-a", b"old-b"), "preparation")
fault_case("after_journal:PREPARED", (b"old-a", b"old-b"), "preparation")
fault_case("after_journal:COMMITTING", (b"old-a", b"old-b"), "rolled back")
fault_case("after_target:0", (b"old-a", b"old-b"), "rolled back")
fault_case("after_progress:0", (b"old-a", b"old-b"), "rolled back")
fault_case("after_target:1", (b"new-a", b"new-b"), "forward")
fault_case("after_journal:COMMITTED", (b"new-a", b"new-b"), "terminal cleanup")
fault_case("after_journal:COMPLETE", (b"new-a", b"new-b"), "terminal cleanup")
for cleanup_event in (
    "before_cleanup_rename",
    "after_cleanup_rename",
    "before_cleanup_blob:0",
    "after_cleanup_blob:0",
    "before_cleanup_blob:1",
    "after_cleanup_blob:1",
    "before_cleanup_blob:2",
    "after_cleanup_blob:2",
    "before_cleanup_blob:3",
    "after_cleanup_blob:3",
    "before_cleanup_blobs_rmdir",
    "after_cleanup_blobs_rmdir",
    "before_cleanup_journal",
    "after_cleanup_journal",
    "before_cleanup_rmdir",
):
    fault_case(cleanup_event, (b"new-a", b"new-b"), "terminal cleanup")
fault_case(
    "after_cleanup_rmdir",
    (b"new-a", b"new-b"),
    "",
    may_finish_before_fault=True,
)
fault_case(
    "before_journal:PREPARING",
    (b"old-a", b"old-b"),
    "",
    may_finish_before_fault=True,
)
fault_case("before_prepared_publish", (b"old-a", b"old-b"), "preparation")
fault_case("after_prepared_publish", (b"old-a", b"old-b"), "preparation")


def fault_occurrence_case(
    name: str,
    event: str,
    occurrence: int,
    expected_after_recovery: tuple[bytes, bytes],
) -> None:
    with tempfile.TemporaryDirectory(prefix="wiki-transactions-durable-fault-") as td:
        root = Path(td)
        outputs, preimages = setup_repo(root)
        seen = 0

        def fail(current: str) -> None:
            nonlocal seen
            if current == event:
                seen += 1
                if seen == occurrence:
                    raise RuntimeError(event)

        try:
            run_transaction(
                root,
                consumer="rotate-log",
                outputs=outputs,
                expected_preimages=preimages,
                allowed_prefixes=("data",),
                fault=fail,
            )
        except RuntimeError:
            faulted = True
        else:
            faulted = False
        try:
            messages = recover_all(root)
            recovered = True
        except TransactionError as exc:
            messages = [str(exc)]
            recovered = False
        clean, reports = transaction_status(root)
        observed = (
            (root / "data/a.txt").read_bytes(),
            (root / "data/b.txt").read_bytes(),
        )
        results.record(
            name,
            faulted and recovered and clean and observed == expected_after_recovery,
            f"seen={seen} messages={messages} reports={reports} observed={observed}",
        )


durable_stages = (
    "before_write",
    "after_write",
    "after_file_fsync",
    "before_replace",
    "after_replace",
    "after_dir_fsync",
    "before_reopen",
    "after_reopen",
    "after_verify",
)
for state, expected in (
    ("PREPARING", (b"old-a", b"old-b")),
    ("PREPARED", (b"old-a", b"old-b")),
    ("COMMITTING", (b"old-a", b"old-b")),
    ("COMMITTED", (b"new-a", b"new-b")),
    ("COMPLETE", (b"new-a", b"new-b")),
):
    for stage in durable_stages:
        event = f"journal:{state}:{stage}"
        fault_occurrence_case(
            f"durable-{event.replace(':', '-')}-recovers",
            event,
            1,
            expected,
        )

for blob_kind in ("pre", "output"):
    for target_index in (0, 1):
        for stage in durable_stages:
            event = f"blob:{blob_kind}:{target_index}:{stage}"
            fault_occurrence_case(
                f"durable-{event.replace(':', '-')}-recovers",
                event,
                1,
                (b"old-a", b"old-b"),
            )

for progress_index, occurrence, expected in (
    (0, 2, (b"old-a", b"old-b")),
    (1, 3, (b"new-a", b"new-b")),
):
    for stage in durable_stages:
        event = f"journal:COMMITTING:{stage}"
        fault_occurrence_case(
            f"durable-progress-{progress_index}-{stage}-recovers",
            event,
            occurrence,
            expected,
        )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-conflict-") as td:
    root = Path(td)
    outputs, preimages = setup_repo(root)
    try:
        run_transaction(
            root, consumer="rotate-log", outputs=outputs, expected_preimages=preimages,
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop")) if event == "after_target:0" else None,
        )
    except RuntimeError:
        pass
    (root / "data/b.txt").write_bytes(b"third-party")
    try:
        recover_all(root)
    except TransactionConflict as exc:
        conflicted = True
        detail = str(exc)
    else:
        conflicted = False
        detail = "recovery overwrote concurrent bytes"
    clean, reports = transaction_status(root)
    results.record(
        "concurrent-edit-is-preserved-and-conflicted",
        conflicted and not clean and (root / "data/b.txt").read_bytes() == b"third-party" and any("CONFLICTED" in report for report in reports),
        f"{detail}; reports={reports}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-mode-conflict-") as td:
    root = Path(td)
    outputs, preimages = setup_repo(root)
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs=outputs,
            expected_preimages=preimages,
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_journal:COMMITTING" else None,
        )
    except RuntimeError:
        pass
    (root / "data/a.txt").chmod(0o600)
    try:
        recover_all(root)
    except TransactionConflict:
        mode_conflicted = True
    else:
        mode_conflicted = False
    clean, reports = transaction_status(root)
    results.record(
        "concurrent-mode-change-is-preserved-as-conflict",
        mode_conflicted
        and not clean
        and (root / "data/a.txt").read_bytes() == b"old-a"
        and (root / "data/a.txt").stat().st_mode & 0o777 == 0o600
        and any("CONFLICTED" in report for report in reports),
        f"reports={reports}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-parent-swap-") as td:
    root = Path(td) / "repo"
    outside = Path(td) / "outside"
    root.mkdir()
    outside.mkdir()
    outputs, preimages = setup_repo(root)
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs=outputs,
            expected_preimages=preimages,
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_target:0" else None,
        )
    except RuntimeError:
        pass
    (root / "data").rename(root / "original-data")
    (outside / "a.txt").write_bytes(b"new-a")
    (outside / "b.txt").write_bytes(b"old-b")
    (root / "data").symlink_to(outside, target_is_directory=True)
    try:
        recover_all(root)
    except TransactionCorrupt:
        blocked = True
    else:
        blocked = False
    clean, reports = transaction_status(root)
    results.record(
        "recovery-rejects-substituted-ancestor-symlink",
        blocked
        and not clean
        and (outside / "a.txt").read_bytes() == b"new-a"
        and (outside / "b.txt").read_bytes() == b"old-b"
        and (root / "original-data/a.txt").read_bytes() == b"new-a"
        and any("CORRUPT" in report for report in reports),
        f"reports={reports}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-rollback-race-") as td:
    root = Path(td)
    outputs, preimages = setup_repo(root)
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs=outputs,
            expected_preimages=preimages,
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_target:0" else None,
        )
    except RuntimeError:
        pass
    original_replace = transactions.atomic_replace_bytes
    edited = False

    def edit_during_rollback(path, content, **kwargs):
        nonlocal_edit = original_replace(path, content, **kwargs)
        if path == root / "data/a.txt":
            (root / "data/b.txt").write_bytes(b"third-party")
        return nonlocal_edit

    transactions.atomic_replace_bytes = edit_during_rollback
    try:
        recover_all(root)
    except TransactionConflict:
        edited = True
    finally:
        transactions.atomic_replace_bytes = original_replace
    clean, reports = transaction_status(root)
    results.record(
        "recovery-final-recheck-preserves-mid-rollback-edit",
        edited
        and not clean
        and (root / "data/a.txt").read_bytes() == b"old-a"
        and (root / "data/b.txt").read_bytes() == b"third-party"
        and any("CONFLICTED" in report for report in reports),
        f"reports={reports}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-rollback-restart-") as td:
    root = Path(td)
    outputs, preimages = setup_repo(root)
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs=outputs,
            expected_preimages=preimages,
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_progress:0" else None,
        )
    except RuntimeError:
        pass
    original_replace = transactions.atomic_replace_bytes
    raised = False

    def kill_after_restore(path, content, **kwargs):
        nonlocal_result = original_replace(path, content, **kwargs)
        if path == root / "data/a.txt":
            raise RuntimeError("recovery killed after restore")
        return nonlocal_result

    transactions.atomic_replace_bytes = kill_after_restore
    try:
        recover_all(root)
    except RuntimeError:
        raised = True
    finally:
        transactions.atomic_replace_bytes = original_replace
    messages = recover_all(root)
    clean, reports = transaction_status(root)
    results.record(
        "recovery-reconciles-stale-progress-after-restored-preimage",
        raised
        and clean
        and (root / "data/a.txt").read_bytes() == b"old-a"
        and (root / "data/b.txt").read_bytes() == b"old-b",
        f"messages={messages} reports={reports}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-unlink-restart-") as td:
    root = Path(td)
    (root / "data").mkdir()
    (root / "data/b.txt").write_bytes(b"old-b")
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs={"data/0.txt": b"new-zero", "data/b.txt": b"new-b"},
            expected_preimages={"data/0.txt": None, "data/b.txt": b"old-b"},
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_progress:0" else None,
        )
    except RuntimeError:
        pass
    original_unlink = transactions.durable_unlink
    unlink_raised = False

    def kill_after_unlink(path, **kwargs):
        original_unlink(path, **kwargs)
        raise RuntimeError("recovery killed after unlink")

    transactions.durable_unlink = kill_after_unlink
    try:
        recover_all(root)
    except RuntimeError:
        unlink_raised = True
    finally:
        transactions.durable_unlink = original_unlink
    messages = recover_all(root)
    clean, reports = transaction_status(root)
    results.record(
        "recovery-reconciles-stale-progress-after-absent-restore",
        unlink_raised
        and clean
        and not (root / "data/0.txt").exists()
        and (root / "data/b.txt").read_bytes() == b"old-b",
        f"messages={messages} reports={reports}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-guard-") as td:
    root = Path(td)
    outputs, preimages = setup_repo(root)
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs={"data/a.txt": outputs["data/a.txt"]},
            expected_preimages={"data/a.txt": preimages["data/a.txt"]},
            guard_preimages={"data/b.txt": b"old-b"},
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_journal:COMMITTING" else None,
        )
    except RuntimeError:
        pass
    (root / "data/b.txt").write_bytes(b"third-party")
    try:
        recover_all(root)
    except TransactionConflict:
        guarded = True
    else:
        guarded = False
    clean, reports = transaction_status(root)
    results.record(
        "read-only-guard-drift-blocks-and-preserves-bytes",
        guarded
        and not clean
        and (root / "data/a.txt").read_bytes() == b"old-a"
        and (root / "data/b.txt").read_bytes() == b"third-party"
        and any("CONFLICTED" in report for report in reports),
        f"reports={reports}",
    )


def corrupt_case(name: str, mutate, fragment: str = "CORRUPT") -> None:
    with tempfile.TemporaryDirectory(prefix="wiki-transactions-corrupt-") as td:
        root = Path(td)
        outputs, preimages = setup_repo(root)
        try:
            run_transaction(
                root, consumer="rotate-log", outputs=outputs, expected_preimages=preimages,
                allowed_prefixes=("data",),
                fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop")) if event == "after_journal:PREPARED" else None,
            )
        except RuntimeError:
            pass
        tx_dir = tx_dirs(root)[0]
        mutate(tx_dir)
        clean, reports = transaction_status(root)
        try:
            recover_all(root)
        except TransactionError:
            blocked = True
        else:
            blocked = False
        results.record(name, not clean and blocked and any(fragment in report for report in reports), f"reports={reports}")


corrupt_case("truncated-journal-blocks", lambda tx: (tx / "journal.json").write_text("{\n", encoding="utf-8"))
corrupt_case("altered-output-blob-blocks", lambda tx: next((tx / "blobs").glob("output-*.bin")).write_bytes(b"tampered"))
corrupt_case("altered-preimage-blob-blocks", lambda tx: next((tx / "blobs").glob("pre-*.bin")).write_bytes(b"tampered"))
corrupt_case("missing-output-blob-blocks", lambda tx: next((tx / "blobs").glob("output-*.bin")).unlink())
corrupt_case("missing-preimage-blob-blocks", lambda tx: next((tx / "blobs").glob("pre-*.bin")).unlink())
corrupt_case("unknown-transaction-entry-blocks", lambda tx: (tx / "unknown").write_text("x", encoding="utf-8"))
corrupt_case(
    "duplicate-journal-key-blocks",
    lambda tx: (tx / "journal.json").write_text(
        (tx / "journal.json").read_text(encoding="utf-8").replace(
            '  "state": "PREPARED",',
            '  "state": "PREPARED",\n  "state": "PREPARED",',
            1,
        ),
        encoding="utf-8",
    ),
)


def mutate_journal_identity(tx: Path, field: str, value) -> None:
    journal_path = tx / "journal.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal[field] = value
    journal["integrity_sha256"] = TRANSACTION_EXECUTION_CONTRACT.integrity(journal)
    journal_path.write_text(json.dumps(journal, sort_keys=True, indent=2) + "\n", encoding="utf-8")


corrupt_case(
    "wrong-repository-root-blocks",
    lambda tx: mutate_journal_identity(tx, "repo_root", "/wrong/repository"),
)
corrupt_case(
    "wrong-repository-device-blocks",
    lambda tx: mutate_journal_identity(tx, "repo_device", 2**62),
)


with tempfile.TemporaryDirectory(prefix="wiki-transactions-schema-") as td:
    root = Path(td)
    outputs, preimages = setup_repo(root)
    try:
        run_transaction(
            root, consumer="rotate-log", outputs=outputs, expected_preimages=preimages,
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop")) if event == "after_journal:PREPARED" else None,
        )
    except RuntimeError:
        pass
    journal_path = tx_dirs(root)[0] / "journal.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["state"] = "UNKNOWN"
    journal["integrity_sha256"] = TRANSACTION_EXECUTION_CONTRACT.integrity(journal)
    results.record("unknown-state-validator-fails", any("unknown state" in error for error in validate_journal(journal)), f"errors={validate_journal(journal)}")
    journal["state"] = "PREPARED"
    journal["plan_sha256"] = "0" * 64
    journal["integrity_sha256"] = TRANSACTION_EXECUTION_CONTRACT.integrity(journal)
    results.record("bad-plan-hash-validator-fails", any("plan_sha256 mismatch" in error for error in validate_journal(journal)), f"errors={validate_journal(journal)}")
    journal["plan_sha256"] = json.loads(journal_path.read_text(encoding="utf-8"))["plan_sha256"]
    journal["integrity_sha256"] = "0" * 64
    results.record("bad-integrity-validator-fails", any("integrity_sha256 mismatch" in error for error in validate_journal(journal)), f"errors={validate_journal(journal)}")


with tempfile.TemporaryDirectory(prefix="wiki-transactions-transition-") as td:
    root = Path(td)
    outputs, preimages = setup_repo(root)
    try:
        run_transaction(
            root,
            consumer="rotate-log",
            outputs=outputs,
            expected_preimages=preimages,
            allowed_prefixes=("data",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_journal:PREPARING" else None,
        )
    except RuntimeError:
        pass
    tx_dir = tx_dirs(root)[0]
    journal = TRANSACTION_EXECUTION_CONTRACT.load_journal(
        tx_dir,
        expected_transaction_id=tx_dir.name.removeprefix(transactions.PREPARING_PREFIX),
    )
    try:
        transactions._transition(tx_dir, journal, "COMMITTING")
    except TransactionCorrupt:
        invalid_transition_blocked = True
    else:
        invalid_transition_blocked = False
    results.record(
        "invalid-state-transition-is-rejected",
        invalid_transition_blocked,
        f"journal_state={journal['state']}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-authority-") as td:
    root = Path(td)
    outside = root / "outside"
    outside.mkdir()
    (root / AUTHORITY_NAME).symlink_to(outside, target_is_directory=True)
    clean, reports = transaction_status(root)
    results.record("symlink-authority-root-fails", not clean and any("unsafe" in report for report in reports), f"reports={reports}")


authority_entry_ok = True
authority_entry_details: list[str] = []
for kind in ("regular", "symlink", "fifo", "hardlink-lock"):
    with tempfile.TemporaryDirectory(prefix="wiki-transactions-authority-entry-") as td:
        root = Path(td)
        authority = root / AUTHORITY_NAME
        authority.mkdir(mode=0o700)
        entry_name = str(uuid.uuid4())
        entry = authority / entry_name
        if kind == "regular":
            entry.write_bytes(b"not a directory")
        elif kind == "symlink":
            outside = root / "outside"
            outside.mkdir()
            entry.symlink_to(outside, target_is_directory=True)
        elif kind == "fifo":
            os.mkfifo(entry)
        else:
            anchor = root / "lock-anchor"
            anchor.write_bytes(b"")
            os.link(anchor, authority / ".lock")
        clean, reports = transaction_status(root)
        if clean or not reports:
            authority_entry_ok = False
            authority_entry_details.append(f"{kind}: reports={reports}")
results.record(
    "unsafe-authority-entry-types-fail-closed",
    authority_entry_ok,
    "; ".join(authority_entry_details),
)


with tempfile.TemporaryDirectory(prefix="wiki-transactions-paths-") as td:
    root = Path(td)
    (root / "data").mkdir()
    for index, bad in enumerate(("/absolute", "data/../escape", "data\\file", "data//file"), start=1):
        try:
            run_transaction(root, consumer="rotate-log", outputs={bad: b"x"}, allowed_prefixes=("data",))
        except TransactionError:
            ok = True
        else:
            ok = False
        results.record(f"noncanonical-target-{index}-fails", ok, f"accepted {bad!r}")


target_entry_ok = True
target_entry_details: list[str] = []
for kind in ("symlink", "hardlink", "directory", "fifo", "parent-symlink"):
    with tempfile.TemporaryDirectory(prefix="wiki-transactions-target-entry-") as td:
        root = Path(td)
        (root / "data").mkdir()
        target = root / "data/a.txt"
        anchor = root / "anchor"
        anchor.write_bytes(b"old")
        if kind == "symlink":
            target.symlink_to(anchor)
        elif kind == "hardlink":
            os.link(anchor, target)
        elif kind == "directory":
            target.mkdir()
        elif kind == "fifo":
            os.mkfifo(target)
        else:
            (root / "data").rmdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "a.txt").write_bytes(b"old")
            (root / "data").symlink_to(outside, target_is_directory=True)
        try:
            run_transaction(
                root,
                consumer="rotate-log",
                outputs={"data/a.txt": b"new"},
                allowed_prefixes=("data",),
            )
        except TransactionError:
            pass
        else:
            target_entry_ok = False
            target_entry_details.append(f"accepted {kind}")
results.record(
    "unsafe-target-and-parent-entry-types-fail-closed",
    target_entry_ok,
    "; ".join(target_entry_details),
)


with tempfile.TemporaryDirectory(prefix="wiki-transactions-cross-device-") as td:
    root = Path(td)
    (root / "data").mkdir()
    (root / "data/a.txt").write_bytes(b"old")
    real_validate_target = transactions.validate_target_path

    class CrossDevicePath:
        @property
        def parent(self):
            return self

        def stat(self):
            return SimpleNamespace(st_dev=root.stat().st_dev + 1)

    def cross_device_target(*_args, **_kwargs):
        return CrossDevicePath()

    transactions.validate_target_path = cross_device_target
    try:
        try:
            run_transaction(
                root,
                consumer="rotate-log",
                outputs={"data/a.txt": b"new"},
                expected_preimages={"data/a.txt": b"old"},
                allowed_prefixes=("data",),
            )
        except TransactionError:
            cross_device_blocked = True
        else:
            cross_device_blocked = False
    finally:
        transactions.validate_target_path = real_validate_target
    results.record(
        "cross-device-target-staging-is-rejected",
        cross_device_blocked and (root / "data/a.txt").read_bytes() == b"old",
        f"blocked={cross_device_blocked}",
    )


child_code = """
import os, sys
from pathlib import Path
from _file_transactions import run_transaction
root = Path(sys.argv[1])
event = sys.argv[2]
run_transaction(root, consumer='rotate-log',
    outputs={'data/a.txt': b'new-a', 'data/b.txt': b'new-b'},
    expected_preimages={'data/a.txt': b'old-a', 'data/b.txt': b'old-b'},
    allowed_prefixes=('data',),
    fault=lambda current: os._exit(93) if current == event else None)
"""

kill_cases = (
    ("after_journal:PREPARING", (b"old-a", b"old-b")),
    ("after_journal:PREPARED", (b"old-a", b"old-b")),
    ("after_journal:COMMITTING", (b"old-a", b"old-b")),
    ("before_target:0", (b"old-a", b"old-b")),
    ("after_target:0", (b"old-a", b"old-b")),
    ("after_progress:0", (b"old-a", b"old-b")),
    ("before_target:1", (b"old-a", b"old-b")),
    ("after_target:1", (b"new-a", b"new-b")),
    ("after_progress:1", (b"new-a", b"new-b")),
    ("after_journal:COMMITTED", (b"new-a", b"new-b")),
    ("after_journal:COMPLETE", (b"new-a", b"new-b")),
    ("after_cleanup_rename", (b"new-a", b"new-b")),
    ("after_cleanup_blob:0", (b"new-a", b"new-b")),
    ("after_cleanup_blobs_rmdir", (b"new-a", b"new-b")),
    ("after_cleanup_journal", (b"new-a", b"new-b")),
)
for event, expected in kill_cases:
    with tempfile.TemporaryDirectory(prefix="wiki-transactions-kill-") as td:
        root = Path(td)
        setup_repo(root)
        proc = subprocess.run(
            [sys.executable, "-c", child_code, str(root), event],
            cwd=REPO_ROOT / "scripts", capture_output=True, text=True,
        )
        messages = recover_all(root)
        clean, reports = transaction_status(root)
        observed = (
            (root / "data/a.txt").read_bytes(),
            (root / "data/b.txt").read_bytes(),
        )
        results.record(
            f"subprocess-kill-{event.replace(':', '-')}-recovers",
            proc.returncode == 93 and clean and observed == expected,
            f"exit={proc.returncode} messages={messages} reports={reports} observed={observed}",
        )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-lock-contention-") as td:
    root = Path(td)
    setup_repo(root)
    authority = TRANSACTION_EXECUTION_CONTRACT.ensure_authority(root)
    contention_code = """
import sys
from pathlib import Path
from _file_transactions import run_transaction
print('READY', flush=True)
run_transaction(
    Path(sys.argv[1]), consumer='rotate-log',
    outputs={'data/a.txt': b'new-a', 'data/b.txt': b'new-b'},
    expected_preimages={'data/a.txt': b'old-a', 'data/b.txt': b'old-b'},
    allowed_prefixes=('data',),
)
print('DONE', flush=True)
"""
    child = None
    ready = ""
    completed_while_locked = False
    child_output = ""
    child_error = ""
    with stable_lock(authority / ".lock"):
        child = subprocess.Popen(
            [sys.executable, "-c", contention_code, str(root)],
            cwd=REPO_ROOT / "scripts",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert child.stdout is not None
        ready = child.stdout.readline().strip()
        try:
            child.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            completed_while_locked = False
        else:
            completed_while_locked = True
    assert child is not None
    child_output, child_error = child.communicate(timeout=10)
    clean, reports = transaction_status(root)
    results.record(
        "stable-root-lock-serializes-second-process",
        ready == "READY"
        and not completed_while_locked
        and child.returncode == 0
        and "DONE" in child_output
        and clean
        and (root / "data/a.txt").read_bytes() == b"new-a"
        and (root / "data/b.txt").read_bytes() == b"new-b",
        f"ready={ready!r} output={child_output!r} error={child_error!r} reports={reports}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-transactions-hook-") as td:
    root = Path(td)
    (root / "scripts/hooks").mkdir(parents=True)
    for name in ("wiki_transactions.py", "_file_transactions.py", "_durable_files.py"):
        shutil.copyfile(REPO_ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copyfile(REPO_ROOT / "scripts/hooks/pre-commit", root / "scripts/hooks/pre-commit")
    (root / "wiki").mkdir()
    (root / "wiki/page.md").write_bytes(b"old")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    try:
        run_transaction(
            root,
            consumer="rebuild-referenced-by",
            outputs={"wiki/page.md": b"new"},
            expected_preimages={"wiki/page.md": b"old"},
            allowed_prefixes=("wiki",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_journal:PREPARED" else None,
        )
    except RuntimeError:
        pass
    proc = subprocess.run(
        ["sh", "scripts/hooks/pre-commit"], cwd=root, capture_output=True, text=True
    )
    results.record(
        "precommit-blocks-nonclean-transaction-state",
        proc.returncode == 1 and ".wiki-transactions/ is nonclean" in proc.stderr,
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}",
    )

sys.exit(results.finish())
