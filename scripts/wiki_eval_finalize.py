#!/usr/bin/env python3
"""Exercise routine finishes and complete approved staging on real fixture trees."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from finalize_wiki_update import finalize_routine_wiki_update

from capture_gate import (CaptureProposalError, apply_capture_proposal, canonical_capture_proposal_bytes,
                          prepare_capture_proposal)
from capture_staging import CaptureStagingError, stage_capture_proposal
from eval_lib import Results
from eval_lint_fixture import copy_lint_fixture, seed_retired_claim, write_registered_raw_fixture

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
    copy_lint_fixture(root)
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
        receipt = root / "tmp/finalization.json"
        state = json.loads(receipt.read_text())
        results.record("success-record-binds-exact-entry-and-checkpoints", state["status"] == "passed"
                       and state["log_entry_sha256"] == hashlib.sha256(ENTRY.encode()).hexdigest()
                       and state["completed_steps"] == ["input-validation", "preflight", "backlinks", "log", "lint"])
        bad_page = root / "wiki/concepts/alpha.md"
        original = bad_page.read_bytes()
        bad_page.write_bytes(original.replace(b"confidence: medium", b"confidence: invalid"))
        failed = run(root, *command)
        state = json.loads(receipt.read_text())
        results.record("failed-lint-replaces-prior-success-after-log", failed.returncode != 0
                       and state["status"] == "failed" and state["completed_steps"][-1] == "log"
                       and "lint.py" in state["error"] and ENTRY.strip() in (root / "wiki/log.md").read_text())
        bad_page.write_bytes(original)
        repaired = run(root, *command)
        results.record("retry-repairs-failed-receipt", repaired.returncode == 0 and json.loads(receipt.read_text())["status"] == "passed")
        with patch("finalize_wiki_update.subprocess.run", side_effect=KeyboardInterrupt):
            try:
                finalize_routine_wiki_update(root, "tmp/entry.md")
            except KeyboardInterrupt:
                pass
        results.record("interrupt-invalidates-earlier-success", json.loads(receipt.read_text())["status"] == "running")
        for reserved in ("finalization.json", ".finalization.lock", "FINALIZATION.JSON", ".FINALIZATION.LOCK"):
            if not (root / "tmp" / reserved).exists():
                (root / "tmp" / reserved).write_text(ENTRY)
            preserved = (root / "tmp" / reserved).read_bytes()
            result = run(root, "finalize_wiki_update.py", "--log-entry", "tmp/" + reserved)
            results.record("reject-reserved-" + reserved, result.returncode != 0 and "reserved" in result.stderr
                           and (root / "tmp" / reserved).read_bytes() == preserved)
        for unsafe in ("finalization.json", ".finalization.lock"):
            path = root / "tmp" / unsafe
            path.unlink()
            target = root / "tmp/unrelated.txt"
            target.write_text("preserve")
            for kind in ("symlink", "fifo", "hardlink"):
                if kind == "symlink":
                    path.symlink_to(target)
                elif kind == "fifo":
                    os.mkfifo(path)
                else:
                    os.link(target, path)
                result = run(root, *command)
                results.record("reject-" + kind + "-" + unsafe, result.returncode != 0 and target.read_text() == "preserve")
                path.unlink()
            run(root, *command)
        (root / "tmp/real").mkdir()
        (root / "tmp/alias").symlink_to(root / "tmp/real", target_is_directory=True)
        (root / "tmp/real/entry.md").write_text(ENTRY)
        result = run(root, "finalize_wiki_update.py", "--log-entry", "tmp/alias/entry.md")
        results.record("reject-symlinked-run-directory", result.returncode != 0 and not (root / "tmp/real/finalization.json").exists())
        from _durable_files import atomic_replace_bytes
        writes = []
        def fail_second_record(path, content, **kwargs):
            writes.append(path)
            if len(writes) > 1:
                raise OSError("cannot record result")
            return atomic_replace_bytes(path, content, **kwargs)
        with patch("finalize_wiki_update.atomic_replace_bytes", side_effect=fail_second_record), patch("finalize_wiki_update._validate_finalization_input", side_effect=ValueError("original input error")):
            try:
                finalize_routine_wiki_update(root, "tmp/entry.md")
            except ValueError as exc:
                results.record("recording-failure-preserves-original-error", str(exc) == "original input error")
            else:
                results.record("recording-failure-preserves-original-error", False)
        processes = [subprocess.Popen([sys.executable, str(SCRIPTS / command[0]), *command[1:]], cwd=root,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        outputs = [process.communicate(timeout=30) for process in processes]
        state = json.loads(receipt.read_text())
        results.record("concurrent-finalizers-serialize-and-log-once", all(p.returncode == 0 for p in processes)
                       and state["status"] == "passed" and (root / "wiki/log.md").read_text().count(ENTRY.strip()) == 1, repr(outputs))
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
            results.record(defect + "-refused-before-writes", result.returncode != 0 and snapshot(root) == unchanged
                           and json.loads(receipt.read_text())["status"] == "failed",
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

    with tempfile.TemporaryDirectory(prefix="wiki-routine-refresh-") as directory:
        root = Path(directory)
        fixture(root)
        initial_rebuild = run(root, "rebuild_referenced_by.py")
        if initial_rebuild.returncode:
            raise RuntimeError(initial_rebuild.stderr)
        history = root / "wiki/sources/gamma.md"
        history.write_text(history.read_text() + "\nRetired fixture wording\n")
        history_before = history.read_bytes()
        raw_before = (root / "raw/notes/source.txt").read_bytes()
        seed_retired_claim(root)
        command = ("finalize_wiki_update.py", "--log-entry", "tmp/entry.md")
        first = run(root, *command)
        accepted = snapshot(root)
        second = run(root, *command)
        results.record("routine-refresh-retires-active-wording-and-preserves-history", first.returncode == second.returncode == 0
                       and snapshot(root) == accepted and history.read_bytes() == history_before
                       and (root / "raw/notes/source.txt").read_bytes() == raw_before
                       and json.loads((root / "tmp/finalization.json").read_text())["status"] == "passed"
                       and (root / "wiki/log.md").read_text().count(ENTRY.strip()) == 1,
                       first.stdout + first.stderr + second.stderr)

    with tempfile.TemporaryDirectory(prefix="wiki-complete-staging-") as directory:
        root = Path(directory)
        fixture(root)
        alpha = root / "wiki/concepts/alpha.md"
        preserved_modes = {
            "wiki/concepts/alpha.md": 0o600,
            "wiki/concepts/beta.md": 0o640,
            "wiki/index.md": 0o600,
            "wiki/log.md": 0o640,
            "scripts/capture-mode-fixture.py": 0o755,
        }
        (root / "scripts/capture-mode-fixture.py").write_text("print('before')\n")
        (root / "tmp/capture-mode-fixture.py").write_text("print('after')\n")
        for relative, mode in preserved_modes.items():
            (root / relative).chmod(mode)
        # Build neutral reviewed refresh drafts; leave all durable preimages untouched.
        refresh_paths = ("wiki/concepts/alpha.md", "scripts/current-state-owners.json", "scripts/retired-claims.json")
        refresh_preimages = {relative: (root / relative).read_bytes() for relative in refresh_paths}
        seed_retired_claim(root)
        refresh_drafts = {relative: (root / relative).read_bytes() for relative in refresh_paths}
        for relative, content in refresh_preimages.items():
            (root / relative).write_bytes(content)
        (root / "tmp/alpha.md").write_bytes(refresh_drafts["wiki/concepts/alpha.md"] + b"\n- [[beta]]\n")
        for filename in ("current-state-owners.json", "retired-claims.json"):
            (root / "tmp" / filename).write_bytes(refresh_drafts["scripts/" + filename])
        (root / "tmp/index.md").write_text((root / "wiki/index.md").read_text().replace("Test concept alpha", "Updated concept alpha"))
        (root / "tmp/entry.md").write_text("## [2026-09-03] promotion | Complete fixture\n\nVerification: exact apply and full lint.\n")
        request = {
            "schema_version": 1, "capture_boundary": "artifact-promotion",
            "purpose": "Promote a neutral fixture", "primary_destination": "wiki/concepts/alpha.md",
            "authored_targets": [{"destination": "wiki/concepts/alpha.md", "staged_path": "tmp/alpha.md"},
                                 {"destination": "wiki/index.md", "staged_path": "tmp/index.md"},
                                 {"destination": "scripts/capture-mode-fixture.py", "staged_path": "tmp/capture-mode-fixture.py"},
                                 {"destination": "scripts/current-state-owners.json", "staged_path": "tmp/current-state-owners.json"},
                                 {"destination": "scripts/retired-claims.json", "staged_path": "tmp/retired-claims.json"}],
            "log_entry_path": "tmp/entry.md", "rebuild_referenced_by": True,
        }
        (root / "tmp/request.json").write_bytes(canonical_capture_proposal_bytes(request))
        before = snapshot(root)
        canonical_request = canonical_capture_proposal_bytes(request).decode()
        invalid_requests = {
            "duplicate-top-level-key": '{"schema_version":1,' + canonical_request[1:],
            "duplicate-nested-key": canonical_request.replace('"destination":', '"destination":"wiki/index.md","destination":', 1),
            "unknown-field": json.dumps({**request, "unknown": True}),
            "boolean-schema": json.dumps({**request, "schema_version": True}),
        }
        for label, invalid_request in invalid_requests.items():
            (root / "tmp/invalid-request.json").write_text(invalid_request)
            try:
                stage_capture_proposal(root, "tmp/invalid-request.json", "tmp/invalid-output")
            except CaptureStagingError:
                rejected = True
            else:
                rejected = False
            results.record("staging-rejects-" + label, rejected and snapshot(root) == before
                           and not (root / "tmp/invalid-output").exists())
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
        results.record("staging-preserves-authored-generated-and-executable-modes",
                       all(target["postimage_mode"] == before[target["destination"]][1]
                           and stat.S_IMODE((root / target["staged_path"]).stat().st_mode) == target["postimage_mode"]
                           for target in proposal["targets"])
                       and all(stat.S_IMODE((root / "tmp/staged" / name).stat().st_mode) == 0o644
                               for name in ("proposal.json", "staging-result.json")),
                       repr([(target["destination"], target["postimage_mode"],
                              stat.S_IMODE((root / target["staged_path"]).stat().st_mode))
                             for target in proposal["targets"]]))
        for label, formatted_request in (
            ("pretty-json", json.dumps(request, indent=2)),
            ("reordered-spaced-json", json.dumps(dict(reversed(list(request.items()))))),
            ("crlf-json", json.dumps(request, indent=2).replace("\n", "\r\n") + "\r\n"),
        ):
            (root / "tmp/request.json").write_bytes(formatted_request.encode())
            retry = stage_capture_proposal(root, "tmp/request.json", "tmp/staged")
            results.record("staging-accepts-" + label, retry.result_code == "ALREADY_STAGED"
                           and (root / staged.proposal_path).read_bytes() == canonical_capture_proposal_bytes(proposal)
                           and snapshot(root) == before)
        alpha_staged = next(target["staged_path"] for target in proposal["targets"]
                            if target["destination"] == "wiki/concepts/alpha.md")
        for label, relative, altered_mode, planned_mode in (
            ("payload", alpha_staged, 0o644, 0o600),
            ("metadata", staged.proposal_path, 0o600, 0o644),
        ):
            path = root / relative
            path.chmod(altered_mode)
            try:
                stage_capture_proposal(root, "tmp/request.json", "tmp/staged")
            except CaptureStagingError:
                rejected = True
            else:
                rejected = False
            results.record("staging-retry-rejects-" + label + "-mode-drift", rejected
                           and stat.S_IMODE(path.stat().st_mode) == altered_mode and snapshot(root) == before)
            path.chmod(planned_mode)
        prepared = prepare_capture_proposal(root, staged.proposal_path)
        results.record("guarded-refresh-stages-pages-registries-index-backlinks-and-log", {
            "wiki/concepts/alpha.md", "wiki/concepts/beta.md", "wiki/index.md", "wiki/log.md",
            "scripts/current-state-owners.json", "scripts/retired-claims.json",
        } <= set(staged.target_paths))
        for label, path in (("registry-preimage", root / "scripts/retired-claims.json"),
                            ("staged-owner-draft", root / alpha_staged)):
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            changed_snapshot = snapshot(root)
            try:
                apply_capture_proposal(root, staged.proposal_path, str(prepared["authorization_digest"]))
            except CaptureProposalError:
                refused = True
            else:
                refused = False
            results.record("guarded-refresh-refuses-" + label + "-drift", refused and snapshot(root) == changed_snapshot)
            path.write_bytes(original)
        apply_capture_proposal(root, staged.proposal_path, str(prepared["authorization_digest"]))
        approved = snapshot(root)
        checks = [run(root, "validate_capture_runs.py"), run(root, "lint.py")]
        retried = apply_capture_proposal(root, staged.proposal_path, str(prepared["authorization_digest"]))
        results.record("staged-approval-installs-preserved-file-modes", all(
            stat.S_IMODE((root / relative).stat().st_mode) == mode
            for relative, mode in preserved_modes.items()))
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
