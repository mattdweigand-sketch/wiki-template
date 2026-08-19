#!/usr/bin/env python3
"""Behavioral regression suite for operational-document reachability."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from check_document_reachability import document_reachability_problems
from eval_lib import Results


AUDIT_REPORT_FIELDS = (
    "Snapshot identity:",
    "Scope:",
    "Findings:",
    "Verification:",
    "Limitations:",
    "Files changed:",
)
AUDIT_IDENTITY_RULES = (
    "Git revision",
    "archive filename",
    "SHA-256",
    "cannot prove its claimed commit or clean-worktree state",
)


def audit_workflow_contract_problems(text: str) -> list[str]:
    normalized = " ".join(text.split())
    problems = [
        f"missing audit report field {field}"
        for field in AUDIT_REPORT_FIELDS
        if field not in text
    ]
    problems.extend(
        f"missing audit identity rule {rule}"
        for rule in AUDIT_IDENTITY_RULES
        if rule not in normalized
    )
    return problems


def write_fixture(root: Path, *, linked: bool) -> None:
    (root / "workflows" / "maintenance").mkdir(parents=True)
    (root / "CONTEXT.md").write_text(
        "# Root\n\n[Maintenance](workflows/maintenance/CONTEXT.md)\n"
        if linked else "# Root\n",
        encoding="utf-8",
    )
    (root / "workflows" / "maintenance" / "CONTEXT.md").write_text(
        "# Maintenance\n\n[Audit](audit.md)\n",
        encoding="utf-8",
    )
    (root / "workflows" / "maintenance" / "audit.md").write_text(
        "# Audit\n",
        encoding="utf-8",
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "document-reachability.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "description": "Fixture operational document graph.",
                "roots": ["CONTEXT.md"],
                "operational_directories": ["workflows"],
                "excluded_directories": ["archive", "scripts/fixtures"],
                "standalone_documents": [],
            }
        ),
        encoding="utf-8",
    )


def main() -> int:
    results = Results()
    with tempfile.TemporaryDirectory(prefix="wiki-doc-reachability-clean-") as td:
        root = Path(td)
        write_fixture(root, linked=True)
        results.record(
            "reachable-operational-tree-passes",
            document_reachability_problems(root) == [],
            repr(document_reachability_problems(root)),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-doc-reachability-orphan-") as td:
        root = Path(td)
        write_fixture(root, linked=True)
        orphan = root / "workflows" / "maintenance" / "legacy.md"
        orphan.write_text("# Legacy\n", encoding="utf-8")
        problems = document_reachability_problems(root)
        results.record(
            "seeded-operational-orphan-fails",
            problems == ["unreachable operational document: workflows/maintenance/legacy.md"],
            repr(problems),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-doc-reachability-route-") as td:
        root = Path(td)
        write_fixture(root, linked=False)
        problems = document_reachability_problems(root)
        results.record(
            "removed-router-link-fails",
            problems == [
                "unreachable operational document: workflows/maintenance/CONTEXT.md",
                "unreachable operational document: workflows/maintenance/audit.md",
            ],
            repr(problems),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-doc-reachability-manifest-") as td:
        root = Path(td)
        write_fixture(root, linked=True)
        manifest_path = root / "scripts" / "document-reachability.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["roots"] = ["CONTEXT.md", "CONTEXT.md"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        problems = document_reachability_problems(root)
        results.record(
            "duplicate-manifest-root-fails",
            problems == ["roots must not contain duplicates"],
            repr(problems),
        )

    repo_root = Path(__file__).resolve().parents[1]
    results.record(
        "live-operational-document-graph-passes",
        document_reachability_problems(repo_root) == [],
        repr(document_reachability_problems(repo_root)),
    )
    audit_text = (repo_root / "workflows/maintenance/audit-docs.md").read_text(
        encoding="utf-8"
    )
    results.record(
        "live-audit-report-contract-passes",
        audit_workflow_contract_problems(audit_text) == [],
        repr(audit_workflow_contract_problems(audit_text)),
    )
    weakened = audit_text.replace("Limitations:", "Constraints:", 1)
    results.record(
        "removed-audit-report-field-fails",
        audit_workflow_contract_problems(weakened)
        == ["missing audit report field Limitations:"],
        repr(audit_workflow_contract_problems(weakened)),
    )
    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
