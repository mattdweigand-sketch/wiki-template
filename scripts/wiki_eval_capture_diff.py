#!/usr/bin/env python3
"""Git-range regression checks for exact capture application records."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from capture_diff import capture_diff_problems
from eval_lib import Results

LEDGER_HEADER = json.dumps({"record_type": "schema", "schema_version": 1, "description": "Fixture capture ledger"}) + "\n"


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def commit_all(root: Path, message: str) -> str:
    git(root, "add", ".")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def initialize_repo(root: Path) -> str:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Wiki Eval")
    git(root, "config", "user.email", "wiki-eval@example.invalid")
    (root / "scripts").mkdir()
    (root / "wiki" / "analyses").mkdir(parents=True)
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "scripts" / "capture-runs.jsonl").write_text(LEDGER_HEADER, encoding="utf-8")
    (root / "wiki" / "concepts" / "existing.md").write_text(
        "# Existing\n", encoding="utf-8"
    )
    return commit_all(root, "base")


def application_record(path: str, content: bytes) -> dict[str, object]:
    return {
        "application_status": "applied",
        "applied_at": "2026-08-26T12:00:00Z",
        "authorization_digest": "a" * 64,
        "capture_boundary": "analysis-capture",
        "editable_scope": [path],
        "primary_destination": path,
        "purpose": "File a durable fixture analysis.",
        "record_type": "capture_application",
        "schema_version": 3,
        "targets": [
            {
                "path": path,
                "postimage_mode": 0o644,
                "postimage_sha256": hashlib.sha256(content).hexdigest(),
                "preimage_mode": None,
                "preimage_sha256": None,
            }
        ],
    }


def append_record(root: Path, record: dict[str, object]) -> None:
    ledger = root / "scripts" / "capture-runs.jsonl"
    ledger.write_text(
        ledger.read_text(encoding="utf-8")
        + json.dumps(record, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )


def run_case(kind: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix=f"wiki-capture-diff-{kind}-") as td:
        root = Path(td)
        base = initialize_repo(root)
        if kind == "ordinary-edit":
            (root / "wiki" / "concepts" / "existing.md").write_text(
                "# Existing\n\nUpdated.\n", encoding="utf-8"
            )
        else:
            path = "wiki/analyses/new-analysis.md"
            content = b"# New analysis\n"
            (root / path).write_bytes(content)
            if kind != "missing-record":
                record = application_record(path, content)
                if kind == "wrong-preimage":
                    record["targets"][0]["preimage_sha256"] = "b" * 64
                    record["targets"][0]["preimage_mode"] = 0o644
                elif kind == "wrong-mode":
                    record["targets"][0]["postimage_mode"] = 0o755
                elif kind == "legacy":
                    record["schema_version"] = 2
                    del record["targets"][0]["preimage_mode"]
                    del record["targets"][0]["postimage_mode"]
                elif kind == "stale-record":
                    record["targets"][0]["postimage_sha256"] = "b" * 64
                elif kind == "partial-record":
                    record["editable_scope"].append("wiki/index.md")
                elif kind == "unrelated-record":
                    record["targets"][0]["path"] = "wiki/concepts/existing.md"
                    record["editable_scope"] = ["wiki/concepts/existing.md"]
                    record["primary_destination"] = "wiki/concepts/existing.md"
                append_record(root, record)
        head = commit_all(root, kind)
        return capture_diff_problems(root, base, head)


def main() -> int:
    results = Results()
    results.record("valid-exact-application-range-passes", run_case("valid") == [])
    results.record(
        "new-analysis-without-record-fails",
        any("new analysis lacks" in problem for problem in run_case("missing-record")),
    )
    results.record(
        "stale-application-record-fails",
        any("postimage" in problem for problem in run_case("stale-record")),
    )
    results.record(
        "partial-application-record-fails",
        any("target paths" in problem for problem in run_case("partial-record")),
    )
    results.record(
        "unrelated-application-record-fails",
        any("analysis-capture primary" in problem or "not changed" in problem
            for problem in run_case("unrelated-record")),
    )
    results.record("ordinary-existing-page-edit-passes", run_case("ordinary-edit") == [])
    results.record("schema-three-wrong-preimage-rejected", any("preimage" in error for error in run_case("wrong-preimage")))
    results.record("schema-three-mode-mismatch-rejected", any("postimage" in error for error in run_case("wrong-mode")))
    results.record("legacy-schema-two-checks-bytes-without-inventing-modes", run_case("legacy") == [])
    with tempfile.TemporaryDirectory(prefix="wiki-capture-history-") as td:
        root = Path(td)
        base = initialize_repo(root)
        path = "wiki/analyses/new-analysis.md"
        content = b"# Captured analysis\n"
        (root / path).write_bytes(content)
        append_record(root, application_record(path, content))
        captured = commit_all(root, "capture")
        (root / path).write_bytes(content + b"\nLater routine correction.\n")
        updated = commit_all(root, "routine correction")
        results.record("capture-then-routine-edit-range-passes",
                       capture_diff_problems(root, base, updated) == [])
        git(root, "checkout", "-qb", "side", captured)
        (root / "wiki/concepts/existing.md").write_text("# Side edit\n")
        commit_all(root, "side edit")
        git(root, "merge", "--no-edit", updated)
        merged = git(root, "rev-parse", "HEAD")
        results.record("merge-with-inherited-capture-passes",
                       capture_diff_problems(root, base, merged) == [])
        append_record(root, application_record(path, content))
        git(root, "add", "scripts/capture-runs.jsonl")
        git(root, "commit", "--amend", "--no-edit")
        problems = capture_diff_problems(root, base, "HEAD")
        results.record("merge-cannot-invent-capture-records",
                       any("merge introduces capture records" in error for error in problems),
                       str(problems))
    with tempfile.TemporaryDirectory(prefix="wiki-capture-concealed-") as td:
        root = Path(td)
        base = initialize_repo(root)
        path = "wiki/analyses/new-analysis.md"
        content = b"# Captured analysis\n"
        (root / path).write_bytes(content)
        record = application_record(path, content)
        record["targets"][0]["postimage_sha256"] = "b" * 64
        append_record(root, record)
        commit_all(root, "invalid capture")
        (root / path).unlink()
        (root / "scripts/capture-runs.jsonl").write_text(LEDGER_HEADER)
        reverted = commit_all(root, "concealing revert")
        problems = capture_diff_problems(root, base, reverted)
        results.record("later-revert-cannot-hide-invalid-capture",
                       any("postimage" in error for error in problems)
                       and any("not append-only" in error for error in problems),
                       str(problems))
    with tempfile.TemporaryDirectory(prefix="wiki-capture-range-") as td:
        root = Path(td)
        base = initialize_repo(root)
        path = "wiki/analyses/new-analysis.md"
        content = b"# Captured analysis\n"
        (root / path).write_bytes(content)
        append_record(root, application_record(path, content))
        git(root, "add", ".")
        tree = git(root, "write-tree")
        results.record("staged-tree-checks-exact-transition", capture_diff_problems(root, base, tree) == [])
        with tempfile.TemporaryDirectory(prefix="wiki-unrelated-cwd-") as caller:
            other = Path(caller)
            (other / "wiki").symlink_to(root / "wiki", target_is_directory=True)
            previous = Path.cwd()
            try:
                os.chdir(other)
                rooted = capture_diff_problems(root, base, tree)
            finally:
                os.chdir(previous)
            results.record("capture-validation-is-rooted-independently-of-caller", rooted == [], str(rooted))
        head = commit_all(root, "capture")
        results.record("initial-zero-base-checks-root-and-capture", capture_diff_problems(root, "0" * 40, head) == [])
        results.record("invalid-revision-fails-clearly", bool(capture_diff_problems(root, "missing-revision", head)))
        results.record("nonancestral-range-refused", bool(capture_diff_problems(root, head, base)))
        git(root, "checkout", "-qb", "side", base)
        (root / "README.md").write_text("side work\n")
        commit_all(root, "side work")
        git(root, "merge", "--no-edit", head)
        results.record("imported-analysis-matches-parent", capture_diff_problems(root, base, "HEAD") == [])
        (root / path).write_bytes(content + b"unreviewed merge correction\n")
        git(root, "add", ".")
        git(root, "commit", "--amend", "--no-edit")
        results.record("merge-rewritten-imported-analysis-refused", any("exact parent" in error for error in capture_diff_problems(root, base, "HEAD")))
        with tempfile.TemporaryDirectory(prefix="wiki-capture-shallow-") as clone_dir:
            clone = Path(clone_dir) / "repo"
            git(root, "clone", "--quiet", "--depth", "1", root.as_uri(), str(clone))
            results.record("missing-history-fails", bool(capture_diff_problems(clone, base, "HEAD")))
            results.record("initial-push-cannot-hide-shallow-parents", bool(capture_diff_problems(clone, "0" * 40, "HEAD")))
    for defect in ("discard", "divergent"):
        with tempfile.TemporaryDirectory(prefix="wiki-capture-merge-ledgers-") as td:
            root = Path(td)
            base = initialize_repo(root)
            git(root, "checkout", "-qb", "left")
            path = "wiki/analyses/left.md"
            content = b"# Left capture\n"
            (root / path).write_bytes(content)
            append_record(root, application_record(path, content))
            left = commit_all(root, "left capture")
            left_ledger = (root / "scripts/capture-runs.jsonl").read_bytes()
            git(root, "checkout", "-qb", "right", base)
            if defect == "divergent":
                path = "wiki/analyses/right.md"
                content = b"# Right capture\n"
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_bytes(content)
                record = application_record(path, content)
                record["authorization_digest"] = "b" * 64
                append_record(root, record)
            else:
                (root / "README.md").write_text("right work\n")
            commit_all(root, "right work")
            subprocess.run(["git", "merge", "--no-commit", "--no-ff", left], cwd=root, capture_output=True)
            (root / "scripts/capture-runs.jsonl").write_bytes(left_ledger if defect == "divergent" else LEDGER_HEADER.encode())
            commit_all(root, "invalid merge resolution")
            errors = capture_diff_problems(root, base, "HEAD")
            results.record("merge-cannot-" + defect + "-parent-ledgers", any("discards or rewrites" in error for error in errors), str(errors))
    return results.finish()


if __name__ == "__main__":
    raise SystemExit(main())
