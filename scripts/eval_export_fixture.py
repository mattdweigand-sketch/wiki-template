"""Complete neutral backup fixtures without reading a checkout's private corpus."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from _wiki_parse import META_PAGES
from wiki_entity_catalog import load_entity_catalog


def build_export_fixture(root: Path, tooling_root: Path) -> None:
    """Copy maintained tooling and create an empty, valid synthetic corpus."""
    for name in (".gitignore", "AGENTS.md", "CLAUDE.md", "CONTEXT.md", "LICENSE", "README.md", "REFERENCES.md"):
        shutil.copy2(tooling_root / name, root / name)
    for name in ("scripts", "workflows", ".agents", ".claude", ".github"):
        shutil.copytree(
            tooling_root / name, root / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".*.lock", "backup-receipt.json", "settings.local.json", "worktrees"),
        )
    for name in META_PAGES:
        path = root / "wiki" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")
    (root / "wiki/domain.md").write_text(
        "---\ntitle: Export Fixture\ntype: domain\nstatus: configured\n---\n\n# Export Fixture\n",
        encoding="utf-8",
    )
    for folder in load_entity_catalog().folder_types:
        path = root / "wiki" / folder
        path.mkdir()
        (path / ".gitkeep").touch()
    buckets = json.loads((root / "scripts/raw-buckets.json").read_text(encoding="utf-8"))["buckets"]
    for name in buckets:
        path = root / "raw" / name
        path.mkdir(parents=True)
        (path / ".gitkeep").touch()
    (root / "raw/README.md").write_text("# Synthetic raw sources\n", encoding="utf-8")
    (root / "scripts/raw-artifacts.json").write_text('{"artifacts":[],"schema_version":1}\n', encoding="utf-8")
    (root / "scripts/lint-adjudications.json").write_text("{}\n", encoding="utf-8")
    (root / "scripts/capture-runs.jsonl").write_text(
        '{"description":"Synthetic empty capture ledger.","record_type":"schema","schema_version":1}\n',
        encoding="utf-8",
    )


__all__ = ["build_export_fixture"]
