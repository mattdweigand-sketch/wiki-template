#!/usr/bin/env python3
"""Behavior checks for the disposable one-time wiki initializer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from eval_lib import Results


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
PERSONAL_TYPES = [
    "analysis", "concept", "decision", "goal", "health", "investment",
    "learning", "person", "project", "property", "skill", "source",
]
SETUP_DELETE_PATHS = [
    "SETUP.md", "scripts/finalize_wiki_setup.py",
    "scripts/wiki_setup_initializer_test.py",
    "scripts/wiki-setup-presets.json",
    "scripts/wiki_setup_initializer.py",
    "tmp/wiki-setup-answers.json",
]


def canonical_answers() -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "context_name": "Matt's Wiki",
            "domain": "Personal knowledge and durable context",
            "preset": "personal",
            "active_types": PERSONAL_TYPES,
            "raw_buckets": {
                "documents": "Documents and notes",
                "media": "Audio, images, and video",
            },
            "example_queries": [
                "What decisions have I made?",
                "What am I working on?",
                "What have I learned?",
            ],
            "privacy_acknowledged": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"


def template_clone() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory(prefix="wiki-setup-preview-")
    root = Path(temporary.name) / "repo"
    shutil.copytree(
        REPO_ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", "deliverables", "tmp", "__pycache__", "*.pyc"),
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "setup-test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Setup Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "template fixture"], cwd=root, check=True)
    (root / "tmp").mkdir()
    (root / "tmp/wiki-setup-answers.json").write_bytes(canonical_answers())
    return temporary, root


def main() -> int:
    results = Results()
    temporary, root = template_clone()
    try:
        before = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True,
            stdout=subprocess.PIPE, text=True,
        ).stdout
        process = subprocess.run(
            [
                PYTHON, "scripts/finalize_wiki_setup.py", "preview",
                "--answers", "tmp/wiki-setup-answers.json",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        after = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True,
            stdout=subprocess.PIPE, text=True,
        ).stdout
        payload = json.loads(process.stdout) if process.stdout else {}
        results.record(
            "preview-is-read-only-and-shows-one-way-finalization",
            process.returncode == 0
            and before == after == ""
            and payload.get("valid") is True
            and payload.get("active_types") == PERSONAL_TYPES
            and payload.get("create_raw_folders") == ["raw/documents", "raw/media"]
            and "archive/setup/answers.json" in payload.get("write_paths", [])
            and payload.get("remove_folders") == [
                "competitors", "customers", "features", "initiatives", "metrics",
                "partners", "personas", "policies", "processes", "products",
                "systems", "teams",
            ]
            and payload.get("delete_paths") == SETUP_DELETE_PATHS,
            f"exit={process.returncode} stdout={process.stdout!r} stderr={process.stderr!r} status={after!r}",
        )
        unapproved = subprocess.run(
            [
                PYTHON, "scripts/finalize_wiki_setup.py", "apply",
                "--answers", "tmp/wiki-setup-answers.json",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        results.record(
            "apply-requires-explicit-approval",
            unapproved.returncode != 0
            and subprocess.run(
                ["git", "status", "--porcelain"], cwd=root, check=True,
                stdout=subprocess.PIPE, text=True,
            ).stdout == ""
            and (root / "tmp/wiki-setup-answers.json").exists(),
            f"exit={unapproved.returncode} stderr={unapproved.stderr!r}",
        )
        (root / "wiki/teams/user-page.md").write_text("user content\n", encoding="utf-8")
        blocked = subprocess.run(
            [
                PYTHON, "scripts/finalize_wiki_setup.py", "preview",
                "--answers", "tmp/wiki-setup-answers.json",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        blocked_payload = json.loads(blocked.stdout) if blocked.stdout else {}
        results.record(
            "preview-blocks-nonempty-inactive-folder",
            blocked.returncode != 0
            and blocked_payload.get("valid") is False
            and blocked_payload.get("blocked_removals") == ["teams"]
            and (root / "wiki/teams/user-page.md").read_text(encoding="utf-8") == "user content\n",
            f"exit={blocked.returncode} stdout={blocked.stdout!r} stderr={blocked.stderr!r}",
        )
    finally:
        temporary.cleanup()

    temporary, root = template_clone()
    try:
        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            stdout=subprocess.PIPE, text=True,
        ).stdout.strip()
        process = subprocess.run(
            [
                PYTHON, "scripts/finalize_wiki_setup.py", "apply",
                "--answers", "tmp/wiki-setup-answers.json", "--approve",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        payload = json.loads(process.stdout) if process.stdout else {}
        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            stdout=subprocess.PIPE, text=True,
        ).stdout.strip()
        domain = (root / "wiki/domain.md").read_text(encoding="utf-8")
        archived_answers = root / "archive/setup/answers.json"
        receipt = root / "archive/setup/finalization-receipt.json"
        setup_residue = [path for path in SETUP_DELETE_PATHS if (root / path).exists()]
        live_documents = (
            ".github/workflows/wiki-ci.yml", "AGENTS.md", "CONTEXT.md", "README.md",
            "REFERENCES.md", "raw/README.md", "wiki/design-notes.md", "wiki/domain.md",
            "wiki/index.md", "wiki/log.md", "wiki/primer.md", "workflows/ingest/CONTEXT.md",
            "workflows/maintenance/lint.md",
        )
        forbidden_live_terms = (
            "SETUP.md", "finalize_wiki_setup", "wiki_setup_initializer",
            "wiki-setup-presets", "plan_wiki_setup", "configuration_migration",
            "entity_preset", "raw_taxonomy", "reconfigur",
        )
        live_residue = {
            relative: term
            for relative in live_documents
            for term in forbidden_live_terms
            if term in (root / relative).read_text(encoding="utf-8")
        }
        active_setup_references = {
            path.relative_to(root).as_posix(): term
            for path in root.rglob("*")
            if path.is_file()
            and ".git" not in path.relative_to(root).parts
            and path.relative_to(root).parts[:2] != ("archive", "setup")
            and path.suffix in {".json", ".md", ".py", ".yaml", ".yml"}
            for term in ("SETUP.md", "finalize_wiki_setup", "wiki_setup_initializer", "wiki-setup-presets")
            if term in path.read_text(encoding="utf-8")
        }
        results.record(
            "approved-apply-produces-live-wiki-and-removes-initializer",
            process.returncode == 0
            and payload.get("valid") is True
            and payload.get("transaction") == "working-tree-changes"
            and head_before == head_after
            and not setup_residue
            and not live_residue
            and not active_setup_references
            and archived_answers.read_bytes() == canonical_answers()
            and set(json.loads(receipt.read_text(encoding="utf-8"))) == {
                "schema_version", "template_commit", "finalized_on",
                "context_name", "answers_sha256", "history_preserved",
            }
            and "status: configured" in domain
            and "entity_preset" not in domain
            and "configuration_version" not in domain
            and "raw_taxonomy" not in domain
            and all((root / "wiki" / folder).is_dir() for folder in (
                "analyses", "concepts", "decisions", "goals", "health",
                "investments", "learnings", "people", "projects", "properties",
                "skills", "sources",
            ))
            and all(not (root / "wiki" / folder).exists() for folder in (
                "competitors", "customers", "features", "initiatives", "metrics",
                "partners", "personas", "policies", "processes", "products",
                "systems", "teams",
            )),
            f"exit={process.returncode} stdout={process.stdout!r} stderr={process.stderr!r} "
            f"residue={setup_residue} live_residue={live_residue} "
            f"active_setup_references={active_setup_references} "
            f"head={head_before}/{head_after}",
        )
    finally:
        temporary.cleanup()
    return results.finish()


if __name__ == "__main__":
    raise SystemExit(main())
