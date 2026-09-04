#!/usr/bin/env python3
"""Interface evals for serialized newest-first wiki log records."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from eval_lib import Results
from wiki_log import WikiLogError, record_wiki_log_entry, render_wiki_log_postimage


REPO_ROOT = Path(__file__).resolve().parents[1]
WIKI_LOG_SCRIPT = REPO_ROOT / "scripts" / "wiki_log.py"

LOG_PREAMBLE = (
    "---\n"
    "title: Activity Log\n"
    "type: log\n"
    "created: 2026-01-01\n"
    "updated: 2026-01-01\n"
    "---\n\n"
    "# Activity Log\n\n"
    "Append-only, newest first.\n\n"
    "---\n\n"
)
OLD_ENTRY = "## [2026-01-01] ingest | Old\n\nVerification command: old.\n"
ENTRY_A = "## [2026-01-02] workflow | Alpha\n\nVerification command: alpha.\n"
ENTRY_B = "## [2026-01-03] workflow | Beta\n\nVerification command: beta.\n"


def make_repo(root: Path) -> None:
    (root / "wiki").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "wiki/log.md").write_text(LOG_PREAMBLE + OLD_ENTRY, encoding="utf-8")


def run_cli(root: Path, entry_path: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(WIKI_LOG_SCRIPT), "record", "--entry-file", str(entry_path)],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


results = Results()

rendered = render_wiki_log_postimage(
    (LOG_PREAMBLE + OLD_ENTRY).encode(),
    ENTRY_A.encode(),
)
results.record(
    "log-render-inserts-before-newest-entry",
    rendered.decode().startswith(LOG_PREAMBLE + ENTRY_A + "\n" + OLD_ENTRY),
)

for name, entry, fragment in (
    ("malformed-header-rejected", b"## Yesterday workflow\n", "recognized"),
    ("multiple-headers-rejected", (ENTRY_A + "\n" + ENTRY_B).encode(), "exactly one"),
    ("invalid-entry-utf8-rejected", b"## [2026-01-02] workflow | Bad\n\xff", "UTF-8"),
):
    try:
        render_wiki_log_postimage((LOG_PREAMBLE + OLD_ENTRY).encode(), entry)
    except WikiLogError as exc:
        rejected = fragment in str(exc)
    else:
        rejected = False
    results.record(name, rejected)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    make_repo(root)
    (root / "wiki/log.md").chmod(0o640)
    first = record_wiki_log_entry(root, ENTRY_A.encode())
    second = record_wiki_log_entry(root, ENTRY_A.encode())
    installed = (root / "wiki/log.md").read_text(encoding="utf-8")
    results.record(
        "record-is-installed-and-exact-retry-is-no-op",
        first.result_code == "RECORDED"
        and second.result_code == "ALREADY_RECORDED"
        and installed.count(ENTRY_A.strip()) == 1
        and OLD_ENTRY in installed
        and stat.S_IMODE((root / "wiki/log.md").stat().st_mode) == 0o640,
    )

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    make_repo(root)
    entry_a = root / "entry-a.md"
    entry_b = root / "entry-b.md"
    entry_a.write_text(ENTRY_A, encoding="utf-8")
    entry_b.write_text(ENTRY_B, encoding="utf-8")
    processes = [run_cli(root, entry_a), run_cli(root, entry_b)]
    completed = [process.communicate(timeout=20) + (process.returncode,) for process in processes]
    installed = (root / "wiki/log.md").read_text(encoding="utf-8")
    results.record(
        "concurrent-records-lose-no-entry",
        all(returncode == 0 for _stdout, _stderr, returncode in completed)
        and installed.count("workflow | Alpha") == 1
        and installed.count("workflow | Beta") == 1,
        repr(completed),
    )

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    make_repo(root)
    original = (root / "wiki/log.md").read_bytes()

    def fail_before_replace(stage: str) -> None:
        if stage == "before_replace":
            raise OSError("seeded write failure")

    try:
        record_wiki_log_entry(root, ENTRY_A.encode(), fault=fail_before_replace)
    except WikiLogError as exc:
        failed_cleanly = "seeded write failure" in str(exc)
    else:
        failed_cleanly = False
    results.record(
        "write-failure-preserves-old-log",
        failed_cleanly and (root / "wiki/log.md").read_bytes() == original,
    )

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    make_repo(root)
    real_log = root / "wiki/real-log.md"
    (root / "wiki/log.md").replace(real_log)
    os.symlink(real_log.name, root / "wiki/log.md")
    try:
        record_wiki_log_entry(root, ENTRY_A.encode())
    except WikiLogError as exc:
        unsafe_rejected = "symlink" in str(exc)
    else:
        unsafe_rejected = False
    results.record("symlinked-log-is-rejected", unsafe_rejected)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    make_repo(root)
    changed = (LOG_PREAMBLE + OLD_ENTRY + "External correction.\n").encode()

    def concurrent_edit(stage: str) -> None:
        if stage == "after_file_fsync":
            (root / "wiki/log.md").write_bytes(changed)

    try:
        record_wiki_log_entry(root, ENTRY_A.encode(), fault=concurrent_edit)
    except WikiLogError:
        rejected = True
    else:
        rejected = False
    results.record("exact-preimage-check-preserves-concurrent-edit",
                   rejected and (root / "wiki/log.md").read_bytes() == changed)

sys.exit(results.finish())
