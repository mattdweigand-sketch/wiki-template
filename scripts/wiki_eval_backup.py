#!/usr/bin/env python3
"""Regression eval for destination-neutral verified-backup receipts."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import export_wiki
from eval_lib import Results
from wiki_backup_receipt import (
    BackupReceiptError,
    VerifiedBackupReceipt,
    backup_freshness,
    load_backup_receipt,
    record_verified_backup,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT = REPO_ROOT / "scripts" / "export_wiki.py"
results = Results()


def build_export_fixture(root: Path) -> None:
    for rel in export_wiki.REQUIRED_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    for prefix in export_wiki.REQUIRED_PREFIXES:
        path = root / prefix / "fixture.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")


def fake_rclone(root: Path, *, size_delta: int = 0) -> Path:
    path = root / "fake-rclone"
    path.write_text(
        f"""#!{sys.executable}
import hashlib
import pathlib
import shutil
import sys

root = pathlib.Path(sys.argv[0]).parent
remote = root / "remote.zip"
command = sys.argv[1]
if command == "copyto":
    shutil.copyfile(sys.argv[2], remote)
elif command == "lsl":
    print(f"{{remote.stat().st_size + {size_delta}}} 2026-01-01 remote.zip")
elif command == "md5sum":
    print(hashlib.md5(remote.read_bytes()).hexdigest() + "  remote.zip")
else:
    print("unexpected command", file=sys.stderr)
    sys.exit(2)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def receipt(
    verified_at: str,
    *,
    content_sha256: str = "a" * 64,
) -> VerifiedBackupReceipt:
    return VerifiedBackupReceipt(
        schema_version=1,
        verified_at=verified_at,
        content_sha256=content_sha256,
        byte_count=7,
        destination_id="sha256:" + "b" * 64,
    )


def write_receipt_fixture(path: Path, value: VerifiedBackupReceipt) -> None:
    path.write_text(json.dumps(asdict(value)), encoding="utf-8")


NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)

with tempfile.TemporaryDirectory(prefix="wiki-backup-state-") as td:
    root = Path(td)
    path = root / "receipt.json"
    state = backup_freshness(path, now=NOW)
    results.record(
        "missing-receipt-is-not-configured-advisory",
        state.kind == "not-configured" and state.receipt is None,
        repr(state),
    )

    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    state = backup_freshness(path, now=NOW)
    results.record(
        "duplicate-key-receipt-is-invalid-advisory",
        state.kind == "invalid" and "duplicate JSON key" in state.message,
        repr(state),
    )

    path.unlink()
    path.symlink_to(root / "missing-receipt-target.json")
    state = backup_freshness(path, now=NOW)
    results.record(
        "dangling-receipt-symlink-is-invalid-advisory",
        state.kind == "invalid" and "symlink" in state.message,
        repr(state),
    )
    path.unlink()

    write_receipt_fixture(path, receipt("2026-06-01T12:00:00Z"))
    state = backup_freshness(path, now=NOW, max_age_days=30)
    results.record("stale-receipt-warns", state.kind == "stale", repr(state))

    write_receipt_fixture(path, receipt("2026-08-20T12:00:00Z"))
    state = backup_freshness(path, now=NOW)
    results.record("future-receipt-warns", state.kind == "future", repr(state))

    write_receipt_fixture(path, receipt("2026-08-18T12:00:00Z"))
    state = backup_freshness(path, now=NOW)
    results.record("fresh-receipt-reports", state.kind == "fresh", repr(state))

with tempfile.TemporaryDirectory(prefix="wiki-backup-record-") as td:
    root = Path(td)
    archive = root / "archive.zip"
    archive.write_bytes(b"archive")
    path = root / "receipt.json"
    target = "fixture-remote:private/path/archive.zip"
    verified_sha256 = hashlib.sha256(b"archive").hexdigest()
    recorded = record_verified_backup(
        archive,
        target,
        path,
        NOW,
        verified_content_sha256=verified_sha256,
        verified_byte_count=7,
    )
    loaded = load_backup_receipt(path)
    results.record(
        "recorded-receipt-hashes-content-and-redacts-destination",
        loaded == recorded
        and loaded.content_sha256 == hashlib.sha256(b"archive").hexdigest()
        and loaded.byte_count == 7
        and (path.stat().st_mode & 0o7777) == 0o600
        and target not in json.dumps(loaded.__dict__)
        and "fixture-remote" not in loaded.destination_id,
        repr(loaded),
    )

with tempfile.TemporaryDirectory(prefix="wiki-backup-unsafe-receipt-") as td:
    root = Path(td)
    archive = root / "archive.zip"
    archive.write_bytes(b"archive")
    verified_sha256 = hashlib.sha256(b"archive").hexdigest()
    real_parent = root / "real"
    real_parent.mkdir()
    linked_parent = root / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    try:
        record_verified_backup(
            archive,
            "fixture:private/archive.zip",
            linked_parent / "receipt.json",
            NOW,
            verified_content_sha256=verified_sha256,
            verified_byte_count=7,
        )
    except BackupReceiptError as exc:
        symlink_parent_rejected = "parent is a symlink" in str(exc)
    else:
        symlink_parent_rejected = False
    results.record("receipt-rejects-symlinked-parent", symlink_parent_rejected)

    receipt_path = real_parent / "receipt.json"
    receipt_path.write_text("old\n", encoding="utf-8")
    os.link(receipt_path, real_parent / "receipt-hardlink.json")
    try:
        record_verified_backup(
            archive,
            "fixture:private/archive.zip",
            receipt_path,
            NOW,
            verified_content_sha256=verified_sha256,
            verified_byte_count=7,
        )
    except BackupReceiptError as exc:
        hardlink_rejected = "link count" in str(exc)
    else:
        hardlink_rejected = False
    results.record("receipt-rejects-multiple-hardlinks", hardlink_rejected)


def concurrent_receipt_writer(
    archive_text: str,
    receipt_text: str,
    destination: str,
    verified_sha256: str,
    queue: object,
) -> None:
    try:
        record_verified_backup(
            Path(archive_text),
            destination,
            Path(receipt_text),
            NOW,
            verified_content_sha256=verified_sha256,
            verified_byte_count=7,
        )
    except Exception as exc:
        queue.put(type(exc).__name__ + ":" + str(exc))
    else:
        queue.put("ok")


with tempfile.TemporaryDirectory(prefix="wiki-backup-concurrent-receipt-") as td:
    root = Path(td)
    archive = root / "archive.zip"
    archive.write_bytes(b"archive")
    receipt_path = root / "receipt.json"
    verified_sha256 = hashlib.sha256(b"archive").hexdigest()
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    processes = [
        context.Process(
            target=concurrent_receipt_writer,
            args=(
                str(archive),
                str(receipt_path),
                f"fixture:private/archive-{index}.zip",
                verified_sha256,
                queue,
            ),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
    outcomes = [queue.get(timeout=2), queue.get(timeout=2)]
    loaded = load_backup_receipt(receipt_path)
    results.record(
        "concurrent-receipt-writers-produce-one-complete-record",
        outcomes.count("ok") == 2
        and loaded.content_sha256 == verified_sha256
        and loaded.byte_count == 7,
        repr(outcomes),
    )

with tempfile.TemporaryDirectory(prefix="wiki-backup-receipt-race-") as td:
    root = Path(td)
    archive = root / "archive.zip"
    archive.write_bytes(b"verified")
    verified_sha256 = hashlib.sha256(b"verified").hexdigest()
    archive.write_bytes(b"changed!")
    receipt_path = root / "receipt.json"
    try:
        record_verified_backup(
            archive,
            "fixture:private/archive.zip",
            receipt_path,
            NOW,
            verified_content_sha256=verified_sha256,
            verified_byte_count=8,
        )
    except BackupReceiptError as exc:
        rejected = "changed after remote verification" in str(exc)
    else:
        rejected = False
    results.record(
        "receipt-rejects-local-drift-after-remote-verification",
        rejected and not receipt_path.exists(),
    )

with tempfile.TemporaryDirectory(prefix="wiki-backup-local-only-") as td:
    root = Path(td)
    build_export_fixture(root)
    receipt_path = root / "scripts" / "backup-receipt.json"
    proc = subprocess.run(
        [
            sys.executable, str(EXPORT), "--repo-root", str(root),
            "--date", "2026-08-19",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    results.record(
        "local-only-export-does-not-advance-receipt",
        proc.returncode == 0 and not receipt_path.exists(),
        f"exit={proc.returncode}; stdout={proc.stdout!r}; stderr={proc.stderr!r}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-backup-path-collision-") as td:
    root = Path(td)
    proc = subprocess.run(
        [
            sys.executable, str(EXPORT), "--repo-root", str(root),
            "--date", "2026-08-19",
            "--receipt-path", "tmp/wiki-export-2026-08-19.zip",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    results.record(
        "receipt-cannot-overwrite-export-archive",
        proc.returncode == 2
        and "must differ from the export archive" in proc.stderr
        and not list(root.rglob("*.zip")),
        f"exit={proc.returncode}; stdout={proc.stdout!r}; stderr={proc.stderr!r}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-backup-verified-") as td:
    root = Path(td)
    build_export_fixture(root)
    rclone = fake_rclone(root)
    receipt_path = root / "scripts" / "backup-receipt.json"
    proc = subprocess.run(
        [
            sys.executable, str(EXPORT), "--repo-root", str(root),
            "--date", "2026-08-19", "--upload-target", "fixture:archive.zip",
            "--rclone-bin", str(rclone),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    state = backup_freshness(receipt_path)
    results.record(
        "verified-private-remote-backup-advances-receipt",
        proc.returncode == 0 and state.kind == "fresh",
        f"exit={proc.returncode}; state={state}; stderr={proc.stderr!r}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-backup-unverified-") as td:
    root = Path(td)
    build_export_fixture(root)
    rclone = fake_rclone(root, size_delta=1)
    receipt_path = root / "scripts" / "backup-receipt.json"
    proc = subprocess.run(
        [
            sys.executable, str(EXPORT), "--repo-root", str(root),
            "--date", "2026-08-19", "--upload-target", "fixture:archive.zip",
            "--rclone-bin", str(rclone),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    results.record(
        "failed-remote-verification-does-not-advance-receipt",
        proc.returncode == 1 and not receipt_path.exists(),
        f"exit={proc.returncode}; stdout={proc.stdout!r}; stderr={proc.stderr!r}",
    )

sys.exit(results.finish())
