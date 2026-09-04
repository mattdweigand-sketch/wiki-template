#!/usr/bin/env python3
"""Exercise routine finishes and complete approved staging on real fixture trees."""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from capture_gate import (apply_capture_proposal, canonical_capture_proposal_bytes,
                          prepare_capture_proposal)
from capture_staging import CaptureStagingError, stage_capture_proposal
from eval_lib import Results
from eval_lint_fixture import copy_fixture, write_registered_raw_fixture

SCRIPTS = Path(__file__).resolve().parent
ENTRY = "## [2026-09-03] workflow | Routine fixture\n\nVerification: final full lint.\n"
LEDGER = canonical_capture_proposal_bytes({
    "record_type": "schema", "schema_version": 1, "description": "Fixture ledger",
})


def run(root: Path, script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=root,
                          capture_output=True, text=True)


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {path.relative_to(root).as_posix(): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            for folder in ("wiki", "scripts", "raw") for path in (root / folder).rglob("*")
            if path.is_file() and path.name != ".wiki-log.lock"}


def fixture(root: Path) -> None:
    copy_fixture(root)
    (root / "scripts/capture-runs.jsonl").write_bytes(LEDGER)
    (root / "wiki/log.md").write_text("# Activity Log\n\n")
    (root / ".gitignore").write_text("raw/\ntmp/\n.wiki-transactions/\nscripts/.wiki-log.lock\n")
    write_registered_raw_fixture(root, "raw/notes/source.txt", "Captured source evidence.\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "complete fixture"], cwd=root, check=True)
    (root / "tmp").mkdir()
    (root / "tmp/entry.md").write_text(ENTRY)


def main() -> int:
    results = Results()
    with tempfile.TemporaryDirectory(prefix="wiki-finalize-") as directory:
        root = Path(directory)
        fixture(root)
        command = ("finalize_wiki_update.py", "--log-entry", "tmp/entry.md")
        first = run(root, *command)
        before = snapshot(root)
        second = run(root, *command)
        results.record("routine-real-checks-once-and-exact-retry", first.returncode == second.returncode == 0
                       and snapshot(root) == before and first.stdout.count("TIER 1  ") == 1
                       and first.stdout.count("TIER 2  ") == 1
                       and (root / "wiki/log.md").read_text().count(ENTRY.strip()) == 1,
                       first.stdout + first.stderr + second.stderr)
        for defect in ("pending-capture", "new-analysis", "ignored-analysis", "malformed-log", "missing-raw", "corrupt-raw", "transaction"):
            ledger = root / "scripts/capture-runs.jsonl"
            raw = root / "raw/notes/source.txt"
            if defect == "pending-capture":
                ledger.write_bytes(LEDGER + b"pending application\n")
            elif defect in {"new-analysis", "ignored-analysis"}:
                (root / "wiki/analyses/new.md").write_text("# Ungated analysis\n")
                if defect == "ignored-analysis":
                    (root / ".git/info/exclude").write_text("wiki/analyses/new.md\n")
            elif defect == "malformed-log":
                (root / "tmp/entry.md").write_text("not an entry\n")
            elif defect == "missing-raw":
                raw.unlink()
            elif defect == "corrupt-raw":
                raw.write_bytes(b"corrupt\n")
            else:
                (root / ".wiki-transactions").mkdir(exist_ok=True)
                (root / ".wiki-transactions/unknown").write_text("preserve conflict")
            unchanged = snapshot(root)
            result = run(root, *command)
            results.record(defect + "-refused-before-writes", result.returncode != 0 and snapshot(root) == unchanged,
                           result.stdout + result.stderr)
            ledger.write_bytes(LEDGER)
            (root / "wiki/analyses/new.md").unlink(missing_ok=True)
            (root / ".git/info/exclude").write_text("")
            raw.write_text("Captured source evidence.\n")
            (root / "tmp/entry.md").write_text(ENTRY)
            if defect == "transaction":
                results.record("transaction-conflict-preserved", (root / ".wiki-transactions/unknown").read_text() == "preserve conflict")
                shutil.rmtree(root / ".wiki-transactions")  # Disposable injected fixture only.
        for mode in ("git", "archive"):
            with tempfile.TemporaryDirectory(prefix="wiki-finalize-mode-") as extracted:
                tree = root if mode == "git" else Path(extracted)
                if mode == "archive":
                    shutil.copytree(root, tree, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
                    result = run(tree, *command)
                    results.record("complete-archive-full-lint", result.returncode == 0 and "TIER 2  " in result.stdout,
                                   result.stdout + result.stderr)
                for header in ("## [2026-09-03] promotion | Guarded", "## 2026-09-03 | analysis-capture | Guarded",
                               "## [2026-09-03] artifact-promotion | Guarded", "## 2026-09-03 synthesis promotion | Guarded",
                               "## [2026-09-03] synthesis-promotion | Guarded"):
                    (tree / "tmp/entry.md").write_text(header + "\n")
                    unchanged = snapshot(tree)
                    result = run(tree, *command)
                    results.record(mode + "-refuses-" + header, result.returncode != 0
                                   and "exact staging" in result.stderr and snapshot(tree) == unchanged)
                (tree / "tmp/entry.md").write_text(ENTRY)
                if mode == "archive":
                    raw = tree / "raw/notes/source.txt"
                    raw.unlink()
                    unchanged = snapshot(tree)
                    result = run(tree, *command)
                    results.record("archive-missing-private-evidence-refused", result.returncode != 0 and snapshot(tree) == unchanged)
                    raw.write_bytes(b"corrupt\n")
                    result = run(tree, *command)
                    results.record("archive-corrupt-private-evidence-refused", result.returncode != 0)
                    raw.write_text("Captured source evidence.\n")
                    # An unrelated parent repository does not turn an archive into a Git checkout.
                    parent = tree / "nested"
                    shutil.copytree(tree, parent, ignore=shutil.ignore_patterns("nested", ".git"))
                    subprocess.run(["git", "init", "-q"], cwd=tree, check=True)
                    result = run(parent, *command)
                    results.record("archive-ignores-unrelated-parent-git", result.returncode == 0, result.stdout + result.stderr)
                    (parent / ".git").write_text("gitdir: /nonexistent/wiki-eval-git\n")
                    unchanged = snapshot(parent)
                    result = run(parent, *command)
                    results.record("broken-local-git-is-not-an-archive", result.returncode != 0 and snapshot(parent) == unchanged)

    with tempfile.TemporaryDirectory(prefix="wiki-complete-staging-") as directory:
        root = Path(directory)
        fixture(root)
        alpha = root / "wiki/concepts/alpha.md"
        (root / "tmp/alpha.md").write_text(alpha.read_text() + "\n- [[beta]]\n")
        (root / "tmp/index.md").write_text((root / "wiki/index.md").read_text().replace("Test concept alpha", "Updated concept alpha"))
        (root / "tmp/entry.md").write_text("## [2026-09-03] promotion | Complete fixture\n\nVerification: exact apply and full lint.\n")
        request = {
            "schema_version": 1, "capture_boundary": "artifact-promotion",
            "purpose": "Promote a neutral fixture", "primary_destination": "wiki/concepts/alpha.md",
            "authored_targets": [{"destination": "wiki/concepts/alpha.md", "staged_path": "tmp/alpha.md"},
                                 {"destination": "wiki/index.md", "staged_path": "tmp/index.md"}],
            "log_entry_path": "tmp/entry.md", "rebuild_referenced_by": True,
        }
        (root / "tmp/request.json").write_bytes(canonical_capture_proposal_bytes(request))
        before = snapshot(root)
        (root / "tmp/unsafe").mkdir()
        (root / "tmp/unsafe/postimages").symlink_to(root / "wiki", target_is_directory=True)
        try:
            stage_capture_proposal(root, "tmp/request.json", "tmp/unsafe")
        except CaptureStagingError:
            rejected = True
        else:
            rejected = False
        results.record("staging-cannot-write-through-redirected-output", rejected and snapshot(root) == before)
        (root / "tmp/unsafe/postimages").unlink()
        staged = stage_capture_proposal(root, "tmp/request.json", "tmp/staged")
        retry = stage_capture_proposal(root, "tmp/request.json", "tmp/staged")
        results.record("complete-staging-only-writes-scratch", snapshot(root) == before
                       and {"wiki/index.md", "wiki/log.md", "wiki/concepts/beta.md"} <= set(staged.target_paths)
                       and retry.result_code == "ALREADY_STAGED", str(staged))
        proposal = json.loads((root / staged.proposal_path).read_text())
        results.record("staging-keeps-template-proposal-schema", proposal["schema_version"] == 2 and "qualification" not in proposal)
        prepared = prepare_capture_proposal(root, staged.proposal_path)
        apply_capture_proposal(root, staged.proposal_path, str(prepared["authorization_digest"]))
        approved = snapshot(root)
        checks = [run(root, "validate_capture_runs.py"), run(root, "lint.py")]
        retried = apply_capture_proposal(root, staged.proposal_path, str(prepared["authorization_digest"]))
        results.record("approved-finish-is-validation-only-and-byte-mode-exact", snapshot(root) == approved
                       and all(check.returncode == 0 for check in checks) and retried["result_code"] == "ALREADY_APPLIED",
                       "\n".join(check.stdout + check.stderr for check in checks))
        (root / "tmp/alpha.md").write_text("changed desired postimage\n")
        try:
            stage_capture_proposal(root, "tmp/request.json", "tmp/staged")
        except CaptureStagingError:
            rejected = True
        else:
            rejected = False
        results.record("changed-postimage-needs-new-staging", rejected and snapshot(root) == approved)
    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
