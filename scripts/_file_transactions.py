#!/usr/bin/env python3
"""Stable facade and execution engine for recoverable file transactions.

Journal vocabulary and validation live in the transaction contract module;
callers continue to use this facade so command and fault-injection behavior
stays stable while the protocol has a single concept owner.
"""

from __future__ import annotations

import json
import os
import stat
import uuid
from pathlib import Path
from typing import Callable, Iterable

from _durable_files import (
    DurableFileError,
    atomic_replace_bytes,
    durable_unlink,
    fsync_directory,
    read_regular_bytes,
    sha256_bytes,
    stable_lock,
)
from _transaction_contract import (
    AUTHORITY_NAME,
    CLEANUP_PREFIX,
    CONSUMERS,
    PREPARING_PREFIX,
    SCHEMA_VERSION,
    TRANSACTION_EXECUTION_CONTRACT,
    TRANSITIONS,
    TransactionConflict,
    TransactionCorrupt,
    TransactionError,
    validate_target_path,
)


FaultHook = Callable[[str], None]


def _write_journal(tx_dir: Path, journal: dict[str, object], *, expected: str | None, fault: FaultHook | None) -> None:
    journal["updated_at"] = TRANSACTION_EXECUTION_CONTRACT.now()
    journal["integrity_sha256"] = TRANSACTION_EXECUTION_CONTRACT.integrity(journal)
    atomic_replace_bytes(
        tx_dir / "journal.json",
        json.dumps(journal, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n",
        mode=0o600,
        expected_sha256=expected,
        fault=(lambda stage: _fault(fault, f"journal:{journal['state']}:{stage}")),
    )
    _fault(fault, f"after_journal:{journal['state']}")


def _transition(tx_dir: Path, journal: dict[str, object], state: str, fault: FaultHook | None = None) -> None:
    current_state = journal["state"]
    if state not in TRANSITIONS.get(current_state, set()):
        raise TransactionCorrupt(f"invalid transition {current_state} -> {state}")
    path = tx_dir / "journal.json"
    current, _ = read_regular_bytes(path)
    expected = sha256_bytes(current or b"")
    journal["state"] = state
    journal["generation"] += 1
    _fault(fault, f"before_journal:{state}")
    _write_journal(tx_dir, journal, expected=expected, fault=fault)


def _rewrite_progress(tx_dir: Path, journal: dict[str, object], fault: FaultHook | None = None) -> None:
    path = tx_dir / "journal.json"
    current, _ = read_regular_bytes(path)
    expected = sha256_bytes(current or b"")
    journal["generation"] += 1
    _fault(fault, f"before_journal:{journal['state']}")
    _write_journal(tx_dir, journal, expected=expected, fault=fault)


def _fault(fault: FaultHook | None, event: str) -> None:
    if fault is not None:
        fault(event)


def _target_state(repo_root: Path, target: dict[str, object]) -> str:
    try:
        path = validate_target_path(repo_root, target["path"], (target["path"],))
    except TransactionError:
        return "unsafe"
    try:
        info = path.lstat()
    except FileNotFoundError:
        if target.get("output_state", "regular") == "absent":
            return "output"
        return "pre" if target["pre_state"] == "absent" else "other"
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        return "unsafe"
    try:
        content, opened = read_regular_bytes(path)
    except DurableFileError:
        return "unsafe"
    if opened is None:
        return "unsafe"
    digest = sha256_bytes(content or b"")
    mode = stat.S_IMODE(opened.st_mode)
    matches_output = (
        target.get("output_state", "regular") == "regular"
        and digest == target["output_sha256"]
        and mode == target["output_mode"]
    )
    matches_pre = (
        target["pre_state"] == "regular"
        and digest == target["pre_sha256"]
        and mode == target["pre_mode"]
    )
    if matches_output and matches_pre:
        return "output" if target["installed"] else "pre"
    if matches_output:
        return "output"
    if matches_pre:
        return "pre"
    return "other"


def _guard_state(repo_root: Path, guard: dict[str, object]) -> str:
    try:
        path = validate_target_path(repo_root, guard["path"], (guard["path"],))
        content, info = read_regular_bytes(path)
    except (TransactionError, DurableFileError):
        return "unsafe"
    if content is None or info is None:
        return "unsafe"
    if sha256_bytes(content) != guard["sha256"]:
        return "other"
    if stat.S_IMODE(info.st_mode) != guard["mode"]:
        return "other"
    return "exact"


def _require_guards(repo_root: Path, tx_dir: Path, journal: dict[str, object]) -> None:
    states = [_guard_state(repo_root, guard) for guard in journal["guards"]]
    if any(value == "unsafe" for value in states):
        if journal["state"] != "COMPLETE":
            _mark_blocking(tx_dir, journal, "CORRUPT")
        raise TransactionCorrupt(f"unsafe transaction guard for {tx_dir.name}")
    if any(value != "exact" for value in states):
        if journal["state"] != "COMPLETE":
            _mark_blocking(tx_dir, journal, "CONFLICTED")
        raise TransactionConflict(f"guard changed during transaction {tx_dir.name}")


def _blob_bytes(tx_dir: Path, relative: str, expected_sha: str) -> bytes:
    path = tx_dir / relative
    TRANSACTION_EXECUTION_CONTRACT.strict_regular(path, mode=0o600)
    content, _ = read_regular_bytes(path)
    if content is None or sha256_bytes(content) != expected_sha:
        raise TransactionCorrupt(f"blob hash mismatch: {path}")
    return content


def _validate_authority_transaction(repo_root: Path, tx_dir: Path, journal: dict[str, object]) -> None:
    TRANSACTION_EXECUTION_CONTRACT.strict_directory(tx_dir)
    present_entries = {path.name for path in tx_dir.iterdir()}
    unknown_entries = present_entries - {"journal.json", "blobs"}
    if unknown_entries:
        raise TransactionCorrupt(f"unknown transaction entries: {sorted(unknown_entries)}")
    if journal["repo_root"] != str(repo_root.resolve()):
        raise TransactionCorrupt("journal repository root identity mismatch")
    if journal["repo_device"] != repo_root.stat().st_dev:
        raise TransactionCorrupt("journal repository device identity mismatch")
    for governed in [*journal["targets"], *journal["guards"]]:
        try:
            path = validate_target_path(repo_root, governed["path"], journal["allowed_prefixes"])
        except TransactionError as exc:
            raise TransactionCorrupt(str(exc)) from exc
        if path.parent.stat().st_dev != journal["repo_device"]:
            raise TransactionCorrupt(f"governed path is on a different device: {governed['path']}")
    expected_blobs = {
        target[key]
        for target in journal["targets"]
        for key in ("pre_blob", "output_blob")
        if target[key] is not None
    }
    if "blobs" in present_entries:
        TRANSACTION_EXECUTION_CONTRACT.strict_directory(tx_dir / "blobs")
        present_blobs = {f"blobs/{path.name}" for path in (tx_dir / "blobs").iterdir()}
        unexpected_blobs = present_blobs - expected_blobs
        if unexpected_blobs:
            raise TransactionCorrupt(f"unknown transaction blobs: {sorted(unexpected_blobs)}")
        for target in journal["targets"]:
            if target["pre_blob"] in present_blobs:
                _blob_bytes(tx_dir, target["pre_blob"], target["pre_sha256"])
            if target["output_blob"] in present_blobs:
                _blob_bytes(tx_dir, target["output_blob"], target["output_sha256"])
    else:
        present_blobs = set()
    if journal["state"] != "PREPARING" and present_blobs != expected_blobs:
        missing = expected_blobs - present_blobs
        raise TransactionCorrupt(f"missing transaction blobs: {sorted(missing)}")


def _mark_blocking(tx_dir: Path, journal: dict[str, object], state: str) -> None:
    if journal["state"] in {"CONFLICTED", "CORRUPT"}:
        return
    if state not in TRANSITIONS.get(journal["state"], set()):
        raise TransactionCorrupt(f"cannot mark {journal['state']} as {state}")
    _transition(tx_dir, journal, state)


def _cleanup_uuid(name: str) -> str | None:
    if not name.startswith(CLEANUP_PREFIX):
        return None
    candidate = name[len(CLEANUP_PREFIX):]
    try:
        uuid.UUID(candidate)
    except ValueError:
        return None
    return candidate


def _preparing_uuid(name: str) -> str | None:
    if not name.startswith(PREPARING_PREFIX):
        return None
    candidate = name[len(PREPARING_PREFIX):]
    try:
        uuid.UUID(candidate)
    except ValueError:
        return None
    return candidate


def _valid_blob_name(name: str) -> bool:
    for prefix in ("pre-", "output-"):
        if name.startswith(prefix) and name.endswith(".bin"):
            digits = name[len(prefix):-4]
            return len(digits) == 4 and digits.isdigit()
    return False


def _valid_blob_temp_name(name: str) -> bool:
    if not name.startswith(".") or "." not in name[1:]:
        return False
    return _valid_blob_name(name[1:].rsplit(".", 1)[0])


def _remove_cleanup_tombstone(
    tombstone: Path,
    fault: FaultHook | None = None,
    *,
    validate_only: bool = False,
) -> None:
    """Idempotently remove an atomically marked terminal transaction tree."""
    transaction_id = _cleanup_uuid(tombstone.name)
    if transaction_id is None:
        raise TransactionCorrupt(f"invalid cleanup tombstone name: {tombstone.name}")
    TRANSACTION_EXECUTION_CONTRACT.strict_directory(tombstone)
    entries = {path.name for path in tombstone.iterdir()}
    journal_temps = {name for name in entries if name.startswith(".journal.json.")}
    extras = entries - {"journal.json", "blobs"} - journal_temps
    if extras:
        raise TransactionCorrupt(f"unknown cleanup entries: {sorted(extras)}")

    journal: dict[str, object] | None = None
    if "journal.json" in entries:
        journal = TRANSACTION_EXECUTION_CONTRACT.load_journal(
            tombstone,
            expected_transaction_id=transaction_id,
        )
        if journal["transaction_id"] != transaction_id:
            raise TransactionCorrupt("cleanup tombstone transaction id mismatch")

    journal_temp_records: list[tuple[Path, str]] = []
    for name in sorted(journal_temps):
        path = tombstone / name
        TRANSACTION_EXECUTION_CONTRACT.strict_regular(path, mode=0o600)
        content, _ = read_regular_bytes(path)
        assert content is not None
        journal_temp_records.append((path, sha256_bytes(content)))

    blobs = tombstone / "blobs"
    blob_records: list[tuple[Path, str]] = []
    if "blobs" in entries:
        TRANSACTION_EXECUTION_CONTRACT.strict_directory(blobs)
        expected: dict[str, str] = {}
        if journal is not None:
            for target in journal["targets"]:
                if target["pre_blob"] is not None:
                    expected[Path(target["pre_blob"]).name] = target["pre_sha256"]
                if target["output_blob"] is not None:
                    expected[Path(target["output_blob"]).name] = target["output_sha256"]
        for path in sorted(blobs.iterdir(), key=lambda item: item.name):
            TRANSACTION_EXECUTION_CONTRACT.strict_regular(path, mode=0o600)
            is_temp = _valid_blob_temp_name(path.name)
            if not _valid_blob_name(path.name) and not is_temp:
                raise TransactionCorrupt(f"unknown cleanup blob: {path.name}")
            if journal is not None and not is_temp and path.name not in expected:
                raise TransactionCorrupt(f"unexpected cleanup blob: {path.name}")
            content, _ = read_regular_bytes(path)
            assert content is not None
            digest = sha256_bytes(content)
            if journal is not None and not is_temp and digest != expected[path.name]:
                raise TransactionCorrupt(f"cleanup blob hash mismatch: {path.name}")
            blob_records.append((path, digest))
    if validate_only:
        return

    if "blobs" in entries:
        for index, (path, digest) in enumerate(blob_records):
            _fault(fault, f"before_cleanup_blob:{index}")
            durable_unlink(path, expected_sha256=digest)
            _fault(fault, f"after_cleanup_blob:{index}")
        _fault(fault, "before_cleanup_blobs_rmdir")
        blobs.rmdir()
        fsync_directory(tombstone)
        _fault(fault, "after_cleanup_blobs_rmdir")

    journal_path = tombstone / "journal.json"
    if journal_path.exists():
        content, _ = read_regular_bytes(journal_path)
        assert content is not None
        _fault(fault, "before_cleanup_journal")
        durable_unlink(journal_path, expected_sha256=sha256_bytes(content))
        _fault(fault, "after_cleanup_journal")

    for path, digest in journal_temp_records:
        durable_unlink(path, expected_sha256=digest)

    if any(tombstone.iterdir()):
        raise TransactionCorrupt(f"cleanup tombstone is not empty: {tombstone.name}")
    _fault(fault, "before_cleanup_rmdir")
    tombstone.rmdir()
    fsync_directory(tombstone.parent)
    _fault(fault, "after_cleanup_rmdir")


def _begin_cleanup(tx_dir: Path, fault: FaultHook | None = None) -> None:
    """Atomically mark a validated terminal/abandoned transaction for cleanup."""
    try:
        uuid.UUID(tx_dir.name)
    except ValueError as exc:
        raise TransactionCorrupt(f"invalid transaction directory name: {tx_dir.name}") from exc
    tombstone = tx_dir.with_name(f"{CLEANUP_PREFIX}{tx_dir.name}")
    if tombstone.exists():
        raise TransactionCorrupt(f"cleanup tombstone already exists: {tombstone.name}")
    _fault(fault, "before_cleanup_rename")
    os.replace(tx_dir, tombstone)
    fsync_directory(tombstone.parent)
    _fault(fault, "after_cleanup_rename")
    _remove_cleanup_tombstone(tombstone, fault)


def _abandon_preparation(preparing: Path) -> None:
    transaction_id = _preparing_uuid(preparing.name)
    if transaction_id is None:
        raise TransactionCorrupt(f"invalid preparing directory name: {preparing.name}")
    repo_root = preparing.parent.parent
    _validate_preparation(repo_root, preparing)
    tombstone = preparing.with_name(f"{CLEANUP_PREFIX}{transaction_id}")
    if tombstone.exists():
        raise TransactionCorrupt(f"cleanup tombstone already exists: {tombstone.name}")
    os.replace(preparing, tombstone)
    fsync_directory(tombstone.parent)
    _remove_cleanup_tombstone(tombstone)


def _validate_preparation(repo_root: Path, preparing: Path) -> None:
    transaction_id = _preparing_uuid(preparing.name)
    if transaction_id is None:
        raise TransactionCorrupt(f"invalid preparing directory name: {preparing.name}")
    TRANSACTION_EXECUTION_CONTRACT.strict_directory(preparing)
    entries = {path.name for path in preparing.iterdir()}
    journal_temps = {name for name in entries if name.startswith(".journal.json.")}
    extras = entries - {"journal.json", "blobs"} - journal_temps
    if extras:
        raise TransactionCorrupt(f"unknown preparation entries: {sorted(extras)}")
    for name in journal_temps:
        TRANSACTION_EXECUTION_CONTRACT.strict_regular(preparing / name, mode=0o600)
    blobs = preparing / "blobs"
    present_blobs: dict[str, bytes] = {}
    if "blobs" in entries:
        TRANSACTION_EXECUTION_CONTRACT.strict_directory(blobs)
        for path in blobs.iterdir():
            TRANSACTION_EXECUTION_CONTRACT.strict_regular(path, mode=0o600)
            if not (_valid_blob_name(path.name) or _valid_blob_temp_name(path.name)):
                raise TransactionCorrupt(f"unknown preparation blob: {path.name}")
            if _valid_blob_name(path.name):
                content, _ = read_regular_bytes(path)
                assert content is not None
                present_blobs[f"blobs/{path.name}"] = content

    if "journal.json" not in entries:
        if present_blobs:
            raise TransactionCorrupt("preparation without journal contains installed blobs")
        return
    journal = TRANSACTION_EXECUTION_CONTRACT.load_journal(
        preparing,
        expected_transaction_id=transaction_id,
    )
    if journal["state"] not in {"PREPARING", "PREPARED"}:
        raise TransactionCorrupt(f"published state remained under preparation name: {journal['state']}")
    if journal["repo_root"] != str(repo_root.resolve()):
        raise TransactionCorrupt("preparation repository root identity mismatch")
    if journal["repo_device"] != repo_root.stat().st_dev:
        raise TransactionCorrupt("preparation repository device identity mismatch")
    expected = {
        target[key]: target["pre_sha256"] if key == "pre_blob" else target["output_sha256"]
        for target in journal["targets"]
        for key in ("pre_blob", "output_blob")
        if target[key] is not None
    }
    if set(present_blobs) - set(expected):
        raise TransactionCorrupt(f"unexpected preparation blobs: {sorted(set(present_blobs) - set(expected))}")
    for name, content in present_blobs.items():
        if sha256_bytes(content) != expected[name]:
            raise TransactionCorrupt(f"preparation blob hash mismatch: {name}")
    if journal["state"] == "PREPARED" and set(present_blobs) != set(expected):
        raise TransactionCorrupt("PREPARED transaction is missing blobs")
    for governed in [*journal["targets"], *journal["guards"]]:
        path = validate_target_path(repo_root, governed["path"], journal["allowed_prefixes"])
        if path.parent.stat().st_dev != journal["repo_device"]:
            raise TransactionCorrupt(f"governed path is on a different device: {governed['path']}")


def _safe_cleanup(tx_dir: Path, fault: FaultHook | None = None) -> None:
    journal = TRANSACTION_EXECUTION_CONTRACT.load_journal(tx_dir)
    if journal["state"] != "COMPLETE":
        raise TransactionCorrupt(f"refusing cleanup before COMPLETE: {tx_dir.name}")
    repo_root = Path(journal["repo_root"])
    _validate_authority_transaction(repo_root, tx_dir, journal)
    _require_guards(repo_root, tx_dir, journal)
    installed = [target["installed"] for target in journal["targets"]]
    if not (all(installed) or not any(installed)):
        raise TransactionCorrupt(f"mixed installed progress at COMPLETE: {tx_dir.name}")
    expected_state = "output" if all(installed) else "pre"
    states = [_target_state(repo_root, target) for target in journal["targets"]]
    if any(value == "unsafe" for value in states):
        raise TransactionCorrupt(f"unsafe target blocks terminal cleanup: {tx_dir.name}")
    if any(value != expected_state for value in states):
        raise TransactionConflict(f"target changed before terminal cleanup: {tx_dir.name}")
    _begin_cleanup(tx_dir, fault)


def _abandon_uncommitted(repo_root: Path, tx_dir: Path, journal: dict[str, object]) -> None:
    states = [_target_state(repo_root, target) for target in journal["targets"]]
    if any(state == "unsafe" for state in states):
        _mark_blocking(tx_dir, journal, "CORRUPT")
        raise TransactionCorrupt(f"unsafe target while abandoning {tx_dir.name}")
    if any(state != "pre" for state in states):
        _mark_blocking(tx_dir, journal, "CONFLICTED")
        raise TransactionConflict(f"target changed before commit for {tx_dir.name}")
    # The atomic tombstone rename makes interruption during cleanup resumable.
    _require_guards(repo_root, tx_dir, journal)
    _begin_cleanup(tx_dir)


def _rollback(repo_root: Path, tx_dir: Path, journal: dict[str, object]) -> None:
    _require_guards(repo_root, tx_dir, journal)
    states = [_target_state(repo_root, target) for target in journal["targets"]]
    if any(state == "unsafe" for state in states):
        _mark_blocking(tx_dir, journal, "CORRUPT")
        raise TransactionCorrupt(f"unsafe target blocks rollback for {tx_dir.name}")
    if any(state not in {"pre", "output"} for state in states):
        _mark_blocking(tx_dir, journal, "CONFLICTED")
        raise TransactionConflict(f"third-party bytes block rollback for {tx_dir.name}")
    if journal["state"] == "COMMITTING":
        _transition(tx_dir, journal, "ROLLING_BACK")
    for index, target in enumerate(journal["targets"]):
        _require_guards(repo_root, tx_dir, journal)
        current_states = [_target_state(repo_root, item) for item in journal["targets"]]
        if any(value == "unsafe" for value in current_states):
            _mark_blocking(tx_dir, journal, "CORRUPT")
            raise TransactionCorrupt(f"unsafe target during rollback for {tx_dir.name}")
        if any(value not in {"pre", "output"} for value in current_states):
            _mark_blocking(tx_dir, journal, "CONFLICTED")
            raise TransactionConflict(f"target changed during rollback for {tx_dir.name}")
        state_name = current_states[index]
        if state_name == "pre":
            if target["installed"]:
                target["installed"] = False
                _rewrite_progress(tx_dir, journal)
            continue
        path = repo_root / target["path"]
        if target["pre_state"] == "absent":
            durable_unlink(path, expected_sha256=target["output_sha256"])
        else:
            preimage = _blob_bytes(tx_dir, target["pre_blob"], target["pre_sha256"])
            atomic_replace_bytes(
                path,
                preimage,
                mode=target["pre_mode"],
                expected_sha256=target["output_sha256"],
            )
        target["installed"] = False
        _rewrite_progress(tx_dir, journal)
    _require_guards(repo_root, tx_dir, journal)
    final_states = [_target_state(repo_root, target) for target in journal["targets"]]
    if any(value == "unsafe" for value in final_states):
        _mark_blocking(tx_dir, journal, "CORRUPT")
        raise TransactionCorrupt(f"unsafe target after rollback for {tx_dir.name}")
    if any(value != "pre" for value in final_states):
        _mark_blocking(tx_dir, journal, "CONFLICTED")
        raise TransactionConflict(f"rollback verification changed for {tx_dir.name}")
    if any(target["installed"] for target in journal["targets"]):
        raise TransactionCorrupt(f"rollback progress flags were not reconciled for {tx_dir.name}")
    _transition(tx_dir, journal, "ROLLED_BACK")
    _require_guards(repo_root, tx_dir, journal)
    _transition(tx_dir, journal, "COMPLETE")
    _safe_cleanup(tx_dir)


def _finish_forward(repo_root: Path, tx_dir: Path, journal: dict[str, object]) -> None:
    _require_guards(repo_root, tx_dir, journal)
    states = [_target_state(repo_root, target) for target in journal["targets"]]
    if any(state == "unsafe" for state in states):
        _mark_blocking(tx_dir, journal, "CORRUPT")
        raise TransactionCorrupt(f"unsafe target blocks forward completion for {tx_dir.name}")
    if any(state != "output" for state in states):
        _mark_blocking(tx_dir, journal, "CONFLICTED")
        raise TransactionConflict(f"output set changed before forward completion for {tx_dir.name}")
    for target in journal["targets"]:
        target["installed"] = True
    if journal["state"] == "COMMITTING":
        _require_guards(repo_root, tx_dir, journal)
        _transition(tx_dir, journal, "COMMITTED")
    if journal["state"] == "COMMITTED":
        _require_guards(repo_root, tx_dir, journal)
        if any(_target_state(repo_root, target) != "output" for target in journal["targets"]):
            _mark_blocking(tx_dir, journal, "CONFLICTED")
            raise TransactionConflict(f"output set changed before completion for {tx_dir.name}")
        _transition(tx_dir, journal, "COMPLETE")
    _require_guards(repo_root, tx_dir, journal)
    if any(_target_state(repo_root, target) != "output" for target in journal["targets"]):
        raise TransactionConflict(f"output set changed before cleanup for {tx_dir.name}")
    _safe_cleanup(tx_dir)


def recover_transaction(repo_root: Path, tx_dir: Path) -> str:
    journal = TRANSACTION_EXECUTION_CONTRACT.load_journal(tx_dir)
    _validate_authority_transaction(repo_root, tx_dir, journal)
    state = journal["state"]
    if state in {"CONFLICTED", "CORRUPT"}:
        raise TransactionError(f"transaction {tx_dir.name} is {state}; diagnose it before proceeding")
    _require_guards(repo_root, tx_dir, journal)
    if state in {"PREPARING", "PREPARED"}:
        _abandon_uncommitted(repo_root, tx_dir, journal)
        return "rolled back uncommitted preparation"
    if state in {"COMMITTING", "ROLLING_BACK"}:
        states = [_target_state(repo_root, target) for target in journal["targets"]]
        if all(value == "output" for value in states) and state == "COMMITTING":
            _finish_forward(repo_root, tx_dir, journal)
            return "finished committed outputs forward"
        _rollback(repo_root, tx_dir, journal)
        return "rolled back interrupted commit"
    if state in {"COMMITTED", "COMPLETE"}:
        if state == "COMMITTED":
            _finish_forward(repo_root, tx_dir, journal)
        else:
            _safe_cleanup(tx_dir)
        return "completed terminal cleanup"
    if state == "ROLLED_BACK":
        _require_guards(repo_root, tx_dir, journal)
        if any(_target_state(repo_root, target) != "pre" for target in journal["targets"]):
            _mark_blocking(tx_dir, journal, "CONFLICTED")
            raise TransactionConflict(f"rolled-back targets changed for {tx_dir.name}")
        _transition(tx_dir, journal, "COMPLETE")
        _require_guards(repo_root, tx_dir, journal)
        _safe_cleanup(tx_dir)
        return "completed rollback cleanup"
    raise TransactionCorrupt(f"unsupported recovery state {state}")


def _transaction_dirs(authority: Path) -> tuple[list[Path], list[Path], list[Path]]:
    entries: list[Path] = []
    cleanup: list[Path] = []
    preparing: list[Path] = []
    for path in sorted(authority.iterdir(), key=lambda item: item.name):
        if path.name == ".lock":
            TRANSACTION_EXECUTION_CONTRACT.strict_regular(path, mode=0o600)
            continue
        if path.name.startswith(CLEANUP_PREFIX):
            if _cleanup_uuid(path.name) is None:
                raise TransactionCorrupt(f"unknown authority entry: {path.name}")
            TRANSACTION_EXECUTION_CONTRACT.strict_directory(path)
            cleanup.append(path)
            continue
        if path.name.startswith(PREPARING_PREFIX):
            if _preparing_uuid(path.name) is None:
                raise TransactionCorrupt(f"unknown authority entry: {path.name}")
            TRANSACTION_EXECUTION_CONTRACT.strict_directory(path)
            preparing.append(path)
            continue
        try:
            uuid.UUID(path.name)
        except ValueError as exc:
            raise TransactionCorrupt(f"unknown authority entry: {path.name}") from exc
        TRANSACTION_EXECUTION_CONTRACT.strict_directory(path)
        entries.append(path)
    return entries, cleanup, preparing


def recover_all_locked(repo_root: Path, authority: Path) -> list[str]:
    messages: list[str] = []
    tx_dirs, cleanup, preparing = _transaction_dirs(authority)
    for tombstone in cleanup:
        _remove_cleanup_tombstone(tombstone)
        messages.append(f"{tombstone.name}: completed terminal cleanup")
    for stage in preparing:
        _abandon_preparation(stage)
        messages.append(f"{stage.name}: abandoned uncommitted preparation")
    for tx_dir in tx_dirs:
        messages.append(f"{tx_dir.name}: {recover_transaction(repo_root, tx_dir)}")
    return messages


def transaction_status(repo_root: Path) -> tuple[bool, list[str]]:
    """Read-only clean-state check. It never creates the authority root."""
    authority = TRANSACTION_EXECUTION_CONTRACT.authority_root(repo_root)
    try:
        info = authority.lstat()
    except FileNotFoundError:
        return True, []
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return False, ["transaction authority root is unsafe"]
    if stat.S_IMODE(info.st_mode) != 0o700:
        return False, ["transaction authority root mode is not 0700"]
    try:
        tx_dirs, cleanup, preparing = _transaction_dirs(authority)
    except TransactionError as exc:
        return False, [str(exc)]
    reports: list[str] = []
    for path in cleanup:
        try:
            _remove_cleanup_tombstone(path, validate_only=True)
        except TransactionError as exc:
            reports.append(f"{path.name}: CORRUPT: {exc}")
        else:
            reports.append(f"{path.name}: terminal cleanup required")
    for path in preparing:
        try:
            _validate_preparation(repo_root, path)
        except TransactionError as exc:
            reports.append(f"{path.name}: CORRUPT: {exc}")
        else:
            reports.append(f"{path.name}: uncommitted preparation requires cleanup")
    for tx_dir in tx_dirs:
        try:
            journal = TRANSACTION_EXECUTION_CONTRACT.load_journal(tx_dir)
            _validate_authority_transaction(repo_root, tx_dir, journal)
        except TransactionError as exc:
            reports.append(f"{tx_dir.name}: CORRUPT: {exc}")
            continue
        guard_states = [_guard_state(repo_root, guard) for guard in journal["guards"]]
        if any(value == "unsafe" for value in guard_states):
            reports.append(f"{tx_dir.name}: CORRUPT: unsafe transaction guard")
            continue
        if any(value != "exact" for value in guard_states):
            reports.append(f"{tx_dir.name}: CONFLICTED: transaction guard changed")
            continue
        if journal["state"] == "COMPLETE":
            installed = [target["installed"] for target in journal["targets"]]
            if not (all(installed) or not any(installed)):
                reports.append(f"{tx_dir.name}: CORRUPT: mixed installed progress at COMPLETE")
                continue
            expected_state = "output" if all(installed) else "pre"
            target_states = [_target_state(repo_root, target) for target in journal["targets"]]
            if any(value == "unsafe" for value in target_states):
                reports.append(f"{tx_dir.name}: CORRUPT: unsafe terminal target")
                continue
            if any(value != expected_state for value in target_states):
                reports.append(f"{tx_dir.name}: CONFLICTED: terminal target changed")
                continue
        if journal["state"] != "COMPLETE":
            reports.append(f"{tx_dir.name}: {journal['state']}")
        else:
            reports.append(f"{tx_dir.name}: COMPLETE cleanup required")
    return not reports, reports


def recover_all(repo_root: Path) -> list[str]:
    authority = TRANSACTION_EXECUTION_CONTRACT.authority_root(repo_root)
    try:
        authority.lstat()
    except FileNotFoundError:
        return []
    authority = TRANSACTION_EXECUTION_CONTRACT.ensure_authority(repo_root)
    lock_path = authority / ".lock"
    with stable_lock(lock_path):
        return recover_all_locked(repo_root, authority)


def _prepare_targets(
    repo_root: Path,
    outputs: dict[str, bytes | None],
    allowed_prefixes: Iterable[str],
    expected_preimages: dict[str, bytes | None] | None,
    expected_preimage_modes: dict[str, int | None] | None,
    output_modes: dict[str, int] | None,
) -> list[dict[str, object]]:
    if not outputs:
        return []
    if expected_preimages is not None and set(expected_preimages) != set(outputs):
        raise TransactionError("expected_preimages keys must exactly match outputs")
    if expected_preimage_modes is not None and set(expected_preimage_modes) != set(outputs):
        raise TransactionError("expected_preimage_modes keys must exactly match outputs")
    if output_modes is not None and set(output_modes) != set(outputs):
        raise TransactionError("output_modes keys must exactly match outputs")
    targets: list[dict[str, object]] = []
    repo_device = repo_root.stat().st_dev
    for index, relative in enumerate(sorted(outputs)):
        output = outputs[relative]
        if output is not None and not isinstance(output, bytes):
            raise TransactionError(f"output for {relative} must be bytes or None")
        path = validate_target_path(repo_root, relative, allowed_prefixes)
        if path.parent.stat().st_dev != repo_device:
            raise TransactionError(f"target is on a different device: {relative}")
        try:
            preimage, info = read_regular_bytes(path, allow_missing=True)
        except DurableFileError as exc:
            raise TransactionError(str(exc)) from exc
        if expected_preimages is not None and preimage != expected_preimages[relative]:
            raise TransactionConflict(f"target changed after consumer snapshot: {relative}")
        pre_mode = stat.S_IMODE(info.st_mode) if info is not None else None
        if expected_preimage_modes is not None and pre_mode != expected_preimage_modes[relative]:
            raise TransactionConflict(f"target mode changed after consumer snapshot: {relative}")
        if preimage is None and output is None:
            continue
        pre_state = "regular" if preimage is not None else "absent"
        output_mode = (
            output_modes[relative] if output_modes is not None
            else pre_mode if output is not None and pre_mode is not None
            else 0o644 if output is not None else None
        )
        if output_mode is not None and (
            not isinstance(output_mode, int)
            or isinstance(output_mode, bool)
            or not 0 <= output_mode <= 0o7777
        ):
            raise TransactionError(f"output mode for {relative} is invalid")
        targets.append(
            {
                "path": relative,
                "pre_state": pre_state,
                "pre_sha256": sha256_bytes(preimage) if preimage is not None else None,
                "pre_mode": pre_mode,
                "pre_blob": f"blobs/pre-{index:04d}.bin" if preimage is not None else None,
                "output_state": "regular" if output is not None else "absent",
                "output_sha256": sha256_bytes(output) if output is not None else None,
                "output_mode": output_mode,
                "output_blob": f"blobs/output-{index:04d}.bin" if output is not None else None,
                "installed": False,
                "_preimage": preimage,
                "_output": output,
            }
        )
    return targets


def _prepare_guards(
    repo_root: Path,
    guard_preimages: dict[str, bytes] | None,
    allowed_prefixes: Iterable[str],
    target_paths: set[str],
) -> list[dict[str, object]]:
    if guard_preimages is None:
        return []
    guards: list[dict[str, object]] = []
    repo_device = repo_root.stat().st_dev
    for relative in sorted(guard_preimages):
        expected = guard_preimages[relative]
        if not isinstance(expected, bytes):
            raise TransactionError(f"guard preimage for {relative} must be bytes")
        if relative in target_paths:
            raise TransactionError(f"governed path cannot be both target and guard: {relative}")
        path = validate_target_path(repo_root, relative, allowed_prefixes)
        if path.parent.stat().st_dev != repo_device:
            raise TransactionError(f"guard is on a different device: {relative}")
        try:
            content, info = read_regular_bytes(path)
        except DurableFileError as exc:
            raise TransactionError(str(exc)) from exc
        if content != expected or info is None:
            raise TransactionConflict(f"guard changed after consumer snapshot: {relative}")
        guards.append(
            {
                "path": relative,
                "sha256": sha256_bytes(content),
                "mode": stat.S_IMODE(info.st_mode),
            }
        )
    return guards


def run_transaction(
    repo_root: Path,
    *,
    consumer: str,
    outputs: dict[str, bytes | None],
    allowed_prefixes: Iterable[str],
    expected_preimages: dict[str, bytes | None] | None = None,
    expected_preimage_modes: dict[str, int | None] | None = None,
    output_modes: dict[str, int] | None = None,
    guard_preimages: dict[str, bytes] | None = None,
    fault: FaultHook | None = None,
) -> list[str]:
    """Recover prior state, then atomically apply one planned file generation."""
    repo_root = repo_root.resolve()
    if consumer not in CONSUMERS:
        raise TransactionError(f"unsupported consumer: {consumer}")
    if not outputs:
        return []
    authority = TRANSACTION_EXECUTION_CONTRACT.ensure_authority(repo_root)
    with stable_lock(authority / ".lock"):
        recovery_messages = recover_all_locked(repo_root, authority)
        prefixes = tuple(sorted(set(allowed_prefixes)))
        if not prefixes or not all(
            TRANSACTION_EXECUTION_CONTRACT.canonical_relative(prefix) for prefix in prefixes
        ):
            raise TransactionError("allowed_prefixes must be canonical repository-relative paths")
        targets_with_bytes = _prepare_targets(
            repo_root,
            outputs,
            prefixes,
            expected_preimages,
            expected_preimage_modes,
            output_modes,
        )
        if not targets_with_bytes:
            return recovery_messages
        guards = _prepare_guards(
            repo_root,
            guard_preimages,
            prefixes,
            set(outputs),
        )
        tx_id = str(uuid.uuid4())
        _fault(fault, "before_journal:PREPARING")
        preparing_dir = authority / f"{PREPARING_PREFIX}{tx_id}"
        tx_dir = authority / tx_id
        preparing_dir.mkdir(mode=0o700)
        blobs = preparing_dir / "blobs"
        blobs.mkdir(mode=0o700)
        fsync_directory(authority)
        created = TRANSACTION_EXECUTION_CONTRACT.now()
        targets = [
            {key: value for key, value in target.items() if not key.startswith("_")}
            for target in targets_with_bytes
        ]
        journal = {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": tx_id,
            "consumer": consumer,
            "created_at": created,
            "updated_at": created,
            "repo_root": str(repo_root),
            "repo_device": repo_root.stat().st_dev,
            "state": "PREPARING",
            "generation": 0,
            "allowed_prefixes": list(prefixes),
            "plan_sha256": TRANSACTION_EXECUTION_CONTRACT.plan_hash(
                consumer,
                list(prefixes),
                targets,
                guards,
            ),
            "targets": targets,
            "guards": guards,
            "integrity_sha256": "",
        }
        _write_journal(preparing_dir, journal, expected=None, fault=fault)
        try:
            for index, (target, source) in enumerate(zip(targets, targets_with_bytes)):
                if source["_preimage"] is not None:
                    _fault(fault, f"before_blob:pre:{index}")
                    atomic_replace_bytes(
                        preparing_dir / target["pre_blob"],
                        source["_preimage"],
                        mode=0o600,
                        expected_sha256=None,
                        fault=(lambda stage, idx=index: _fault(fault, f"blob:pre:{idx}:{stage}")),
                    )
                    _fault(fault, f"after_blob:pre:{index}")
                if source["_output"] is not None:
                    _fault(fault, f"before_blob:output:{index}")
                    atomic_replace_bytes(
                        preparing_dir / target["output_blob"],
                        source["_output"],
                        mode=0o600,
                        expected_sha256=None,
                        fault=(lambda stage, idx=index: _fault(fault, f"blob:output:{idx}:{stage}")),
                    )
                    _fault(fault, f"after_blob:output:{index}")
            _transition(preparing_dir, journal, "PREPARED", fault)
            _fault(fault, "before_prepared_publish")
            os.replace(preparing_dir, tx_dir)
            fsync_directory(authority)
            _fault(fault, "after_prepared_publish")
            _require_guards(repo_root, tx_dir, journal)
            for target in targets:
                if _target_state(repo_root, target) != "pre":
                    _mark_blocking(tx_dir, journal, "CONFLICTED")
                    raise TransactionConflict(f"target changed before commit: {target['path']}")
            _transition(tx_dir, journal, "COMMITTING", fault)
            for index, target in enumerate(targets):
                _require_guards(repo_root, tx_dir, journal)
                current_states = [_target_state(repo_root, item) for item in targets]
                if any(value == "unsafe" for value in current_states):
                    _mark_blocking(tx_dir, journal, "CORRUPT")
                    raise TransactionCorrupt("unsafe target during commit")
                if any(
                    value not in ({"output"} if item["installed"] else {"pre"})
                    for item, value in zip(targets, current_states)
                ):
                    _mark_blocking(tx_dir, journal, "CONFLICTED")
                    raise TransactionConflict("target changed during commit")
                state_name = _target_state(repo_root, target)
                if state_name == "unsafe":
                    _mark_blocking(tx_dir, journal, "CORRUPT")
                    raise TransactionCorrupt(f"unsafe target during commit: {target['path']}")
                if state_name != "pre":
                    _mark_blocking(tx_dir, journal, "CONFLICTED")
                    raise TransactionConflict(f"target changed during commit: {target['path']}")
                _fault(fault, f"before_target:{index}")
                expected = target["pre_sha256"] if target["pre_state"] == "regular" else None
                if target.get("output_state", "regular") == "absent":
                    if expected is not None:
                        durable_unlink(repo_root / target["path"], expected_sha256=expected)
                else:
                    output = _blob_bytes(tx_dir, target["output_blob"], target["output_sha256"])
                    atomic_replace_bytes(
                        repo_root / target["path"],
                        output,
                        mode=target["output_mode"],
                        expected_sha256=expected,
                        fault=(lambda stage, idx=index: _fault(fault, f"target:{idx}:{stage}")),
                    )
                _fault(fault, f"after_target:{index}")
                target["installed"] = True
                _rewrite_progress(tx_dir, journal, fault)
                _fault(fault, f"after_progress:{index}")
                _require_guards(repo_root, tx_dir, journal)
            if any(_target_state(repo_root, target) != "output" for target in targets):
                _mark_blocking(tx_dir, journal, "CONFLICTED")
                raise TransactionConflict("installed output verification failed")
            _require_guards(repo_root, tx_dir, journal)
            _transition(tx_dir, journal, "COMMITTED", fault)
            _require_guards(repo_root, tx_dir, journal)
            if any(_target_state(repo_root, target) != "output" for target in targets):
                _mark_blocking(tx_dir, journal, "CONFLICTED")
                raise TransactionConflict("installed outputs changed before completion")
            _transition(tx_dir, journal, "COMPLETE", fault)
            _require_guards(repo_root, tx_dir, journal)
            _safe_cleanup(tx_dir, fault)
            return recovery_messages
        except (TransactionError, DurableFileError):
            raise
        except Exception:
            # Injected failures and process-level exceptions intentionally leave
            # durable authority for the next deterministic recovery.
            raise


def diagnose_transaction(repo_root: Path, transaction_id: str) -> dict[str, object]:
    try:
        uuid.UUID(transaction_id)
    except ValueError as exc:
        raise TransactionError("transaction id must be a UUID") from exc
    authority = TRANSACTION_EXECUTION_CONTRACT.authority_root(repo_root)
    candidates = [
        authority / transaction_id,
        authority / f"{PREPARING_PREFIX}{transaction_id}",
        authority / f"{CLEANUP_PREFIX}{transaction_id}",
    ]
    present: list[Path] = []
    for candidate in candidates:
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        present.append(candidate)
    if not present:
        raise TransactionError(f"transaction not found: {transaction_id}")
    if len(present) != 1:
        raise TransactionCorrupt(f"multiple authority entries exist for transaction {transaction_id}")
    tx_dir = present[0]
    TRANSACTION_EXECUTION_CONTRACT.strict_directory(tx_dir)
    journal_path = tx_dir / "journal.json"
    try:
        journal_path.lstat()
    except FileNotFoundError:
        return {
            "transaction_id": transaction_id,
            "authority_entry": tx_dir.name,
            "lifecycle": (
                "unpublished-preparation"
                if tx_dir.name.startswith(PREPARING_PREFIX)
                else "terminal-cleanup"
            ),
            "journal": "missing",
        }
    journal = TRANSACTION_EXECUTION_CONTRACT.load_journal(
        tx_dir,
        expected_transaction_id=transaction_id,
    )
    lifecycle = "active"
    if tx_dir.name.startswith(PREPARING_PREFIX):
        lifecycle = "unpublished-preparation"
    elif tx_dir.name.startswith(CLEANUP_PREFIX):
        lifecycle = "terminal-cleanup"
    report = {
        "transaction_id": transaction_id,
        "authority_entry": tx_dir.name,
        "lifecycle": lifecycle,
        "consumer": journal["consumer"],
        "state": journal["state"],
        "generation": journal["generation"],
        "allowed_prefixes": journal["allowed_prefixes"],
        "plan_sha256": journal["plan_sha256"],
        "integrity_sha256": journal["integrity_sha256"],
        "targets": [
            {
                "path": target["path"],
                "pre_sha256": target["pre_sha256"],
                "output_sha256": target["output_sha256"],
                "installed": target["installed"],
                "observed": _target_state(repo_root, target),
            }
            for target in journal["targets"]
        ],
        "guards": [
            {
                "path": guard["path"],
                "sha256": guard["sha256"],
                "mode": guard["mode"],
                "observed": _guard_state(repo_root, guard),
            }
            for guard in journal["guards"]
        ],
    }
    return report



__all__ = [
    "AUTHORITY_NAME",
    "TransactionConflict",
    "TransactionCorrupt",
    "TransactionError",
    "diagnose_transaction",
    "recover_all",
    "recover_all_locked",
    "recover_transaction",
    "run_transaction",
    "transaction_status",
]
