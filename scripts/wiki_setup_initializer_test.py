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
README_IDENTITY_START = "<!-- wiki-setup:readme-identity:start -->"
README_AGENT_PROMPT_START = "<!-- wiki-setup:readme-agent-setup-prompt:start -->"
README_AGENT_PROMPT_END = "<!-- wiki-setup:readme-agent-setup-prompt:end -->"
README_CI_LINE_MARKER = "<!-- wiki-setup:readme-ci-row:line -->"


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


def run_setup_preview(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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


def replace_managed_marker_body(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + "\n\nReworded template prose that the initializer must ignore.\n" + text[end:]


def main() -> int:
    results = Results()
    temporary, root = template_clone()
    try:
        before = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, check=True,
            stdout=subprocess.PIPE, text=True,
        ).stdout
        process = run_setup_preview(root)
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
        readme_path = root / "README.md"
        original_readme = readme_path.read_text(encoding="utf-8")
        readme_path.write_text(
            original_readme.replace(README_IDENTITY_START, "", 1),
            encoding="utf-8",
        )
        missing_marker = run_setup_preview(root)
        missing_payload = json.loads(missing_marker.stdout) if missing_marker.stdout else {}
        results.record(
            "preview-rejects-missing-setup-marker",
            missing_marker.returncode != 0
            and missing_payload.get("valid") is False
            and any(
                "readme-identity" in error and "exactly one start and one end" in error
                for error in missing_payload.get("errors", [])
            ),
            f"exit={missing_marker.returncode} stdout={missing_marker.stdout!r} "
            f"stderr={missing_marker.stderr!r}",
        )
        readme_path.write_text(
            original_readme.replace(
                README_IDENTITY_START,
                README_IDENTITY_START + "\n" + README_IDENTITY_START,
                1,
            ),
            encoding="utf-8",
        )
        duplicate_marker = run_setup_preview(root)
        duplicate_payload = json.loads(duplicate_marker.stdout) if duplicate_marker.stdout else {}
        results.record(
            "preview-rejects-duplicate-setup-marker",
            duplicate_marker.returncode != 0
            and duplicate_payload.get("valid") is False
            and any(
                "readme-identity" in error and "found 2 start and 1 end" in error
                for error in duplicate_payload.get("errors", [])
            ),
            f"exit={duplicate_marker.returncode} stdout={duplicate_marker.stdout!r} "
            f"stderr={duplicate_marker.stderr!r}",
        )
        readme_path.write_text(
            original_readme
            + "\n<!-- wiki-setup:unregistered-block:start -->\n"
            + "Unregistered setup content.\n"
            + "<!-- wiki-setup:unregistered-block:end -->\n",
            encoding="utf-8",
        )
        unconsumed_marker = run_setup_preview(root)
        unconsumed_payload = (
            json.loads(unconsumed_marker.stdout) if unconsumed_marker.stdout else {}
        )
        results.record(
            "preview-rejects-unconsumed-setup-marker",
            unconsumed_marker.returncode != 0
            and unconsumed_payload.get("valid") is False
            and "unconsumed setup markers remain in: README.md"
            in unconsumed_payload.get("errors", []),
            f"exit={unconsumed_marker.returncode} stdout={unconsumed_marker.stdout!r} "
            f"stderr={unconsumed_marker.stderr!r}",
        )
        readme_path.write_text(
            original_readme.replace(README_CI_LINE_MARKER, "", 1),
            encoding="utf-8",
        )
        missing_line_marker = run_setup_preview(root)
        missing_line_payload = (
            json.loads(missing_line_marker.stdout) if missing_line_marker.stdout else {}
        )
        results.record(
            "preview-rejects-missing-setup-line-marker",
            missing_line_marker.returncode != 0
            and missing_line_payload.get("valid") is False
            and any(
                "readme-ci-row" in error and "must appear exactly once" in error
                for error in missing_line_payload.get("errors", [])
            ),
            f"exit={missing_line_marker.returncode} "
            f"stdout={missing_line_marker.stdout!r} stderr={missing_line_marker.stderr!r}",
        )
        readme_path.write_text(original_readme, encoding="utf-8")
        (root / "wiki/teams/user-page.md").write_text("user content\n", encoding="utf-8")
        blocked = run_setup_preview(root)
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
        readme_path = root / "README.md"
        readme_path.write_text(
            replace_managed_marker_body(
                readme_path.read_text(encoding="utf-8"),
                README_AGENT_PROMPT_START,
                README_AGENT_PROMPT_END,
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "reword setup-managed prose"],
            cwd=root,
            check=True,
        )
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
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        context = (root / "CONTEXT.md").read_text(encoding="utf-8")
        domain = (root / "wiki/domain.md").read_text(encoding="utf-8")
        raw_readme = (root / "raw/README.md").read_text(encoding="utf-8")
        raw_registry = json.loads((root / "scripts/raw-buckets.json").read_text(encoding="utf-8"))
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
        live_readme = (root / "README.md").read_text(encoding="utf-8")
        results.record(
            "managed-prose-change-does-not-break-apply",
            process.returncode == 0
            and "Reworded template prose that the initializer must ignore." not in live_readme,
            f"exit={process.returncode} stdout={process.stdout!r} stderr={process.stderr!r}",
        )
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
            and "unconfigured template" not in agents
            and agents.startswith("# Matt's Wiki\n")
            and live_readme.startswith("# Matt's Wiki\n")
            and context.startswith("# Matt's Wiki - Task Router\n")
            and "Matt's Wiki Wiki" not in agents + live_readme + context
            and "Source artifacts stay local and must never be committed" in raw_readme
            and "exact path, size, and SHA-256 manifest" in raw_readme
            and raw_registry.get("policy")
            == "Raw source artifacts are immutable, local-only, and never tracked by Git."
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
