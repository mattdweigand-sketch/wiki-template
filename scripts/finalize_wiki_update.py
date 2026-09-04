#!/usr/bin/env python3
"""Finalize routine authored edits with a fixed rebuild, log, and validation sequence."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _durable_files import read_regular_bytes
from _repo_paths import EXISTING_FILE, resolve_repo_path
from _wiki_parse import parse_log_entry_type
from capture_ledger import CAPTURE_APPLICATION_BOUNDARIES
from wiki_provenance import validate_live_provenance, validate_restored_provenance
from wiki_log import record_wiki_log_entry, render_wiki_log_postimage


class WikiFinalizationError(RuntimeError):
    """Routine finalization cannot safely continue or did not pass validation."""


def _run_wiki_check(root: Path, script: str, *args: str) -> None:
    command = [sys.executable, str(Path(__file__).with_name(script)), *args]
    result = subprocess.run(command, cwd=root, check=False)
    if result.returncode:
        raise WikiFinalizationError(f"{script} exited {result.returncode}; fix the cause and retry the same entry")


def _guard_routine_update(root: Path) -> bool:
    # Extracted trees have no baseline for Git history checks.
    git_metadata = root / ".git"
    if not git_metadata.exists() and not git_metadata.is_symlink():
        return False
    # Pending applications must be committed exactly before routine finalization.
    baseline = subprocess.run(["git", "show", "HEAD:scripts/capture-runs.jsonl"], cwd=root, capture_output=True)
    ledger, _ = read_regular_bytes(root / "scripts/capture-runs.jsonl")
    if baseline.returncode or baseline.stdout != ledger:
        raise WikiFinalizationError("routine finalization requires a committed, unchanged capture ledger")
    tracked = subprocess.run(["git", "diff", "--name-only", "--no-renames", "--diff-filter=A", "HEAD", "--", "wiki/analyses/"], cwd=root, capture_output=True)
    untracked = subprocess.run(["git", "ls-files", "--others", "--", "wiki/analyses/"], cwd=root, capture_output=True)
    if tracked.returncode or untracked.returncode or tracked.stdout or untracked.stdout:
        raise WikiFinalizationError("new analyses must use exact analysis capture")
    return True


def finalize_routine_wiki_update(repo_root: Path, log_entry_path: str) -> None:
    """Finish routine edits only; guarded applications have a validation-only exit."""
    root = repo_root.resolve()
    relative = resolve_repo_path(log_entry_path, repo_root=root, allowed_prefixes=("tmp",), mode=EXISTING_FILE)
    entry, _ = read_regular_bytes(root / relative)
    log, _ = read_regular_bytes(root / "wiki/log.md")
    assert entry is not None and log is not None
    render_wiki_log_postimage(log, entry)  # Validate the input before any write.
    action = parse_log_entry_type(entry.decode().splitlines()[0])
    if action in CAPTURE_APPLICATION_BOUNDARIES | {"promotion", "synthesis"}:
        raise WikiFinalizationError("promotion entries belong in the exact staging workflow")
    git_checkout = _guard_routine_update(root)
    _run_wiki_check(root, "wiki_transactions.py", "status", "--quiet")
    # This preflight checks old identities before any generated page is changed.
    problems = (validate_live_provenance(root) if git_checkout
                else validate_restored_provenance(root))
    if problems:
        raise WikiFinalizationError("; ".join(problems))
    _run_wiki_check(root, "rebuild_referenced_by.py")
    record_wiki_log_entry(root, entry)
    _run_wiki_check(root, "lint.py", *([] if git_checkout else ["--restored-tree"]))
    print("Routine wiki update finalized; no further durable edits.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-entry", required=True)
    args = parser.parse_args()
    try:
        finalize_routine_wiki_update(Path.cwd(), args.log_entry)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"wiki finalization failed: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = ["WikiFinalizationError", "finalize_routine_wiki_update"]


if __name__ == "__main__":
    raise SystemExit(main())
