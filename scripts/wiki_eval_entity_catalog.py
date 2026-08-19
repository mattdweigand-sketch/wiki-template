#!/usr/bin/env python3
"""Behavioral regression suite for the entity catalog and setup planner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from eval_lib import Results
from wiki_entity_catalog import CatalogError, load_entity_catalog, plan_wiki_setup


BASELINE_FOLDER_TYPES = {
    "analyses": "analysis",
    "competitors": "competitor",
    "concepts": "concept",
    "customers": "customer",
    "decisions": "decision",
    "features": "feature",
    "initiatives": "initiative",
    "metrics": "metric",
    "people": "person",
    "personas": "persona",
    "products": "product",
    "sources": "source",
}


def write_catalog(path: Path, types: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "description": "Fixture entity catalog.",
                "presets": ["organization"],
                "types": types,
            }
        ),
        encoding="utf-8",
    )


def baseline_type(folder: str, type_name: str) -> dict[str, object]:
    return {
        "folder": folder,
        "type": type_name,
        "purpose": f"Fixture purpose for {type_name}.",
        "presets": ["organization"],
        "review_date": "expected" if type_name == "decision" else "optional",
        "authority_freshness": "contextual",
        "verification": "when-authority-requires",
    }


def main() -> int:
    results = Results()

    catalog = load_entity_catalog()
    results.record(
        "baseline-folder-type-contract",
        catalog.folder_types == BASELINE_FOLDER_TYPES,
        f"folder_types={catalog.folder_types!r}",
    )
    results.record(
        "baseline-organization-preset",
        catalog.resolve_preset("organization") == tuple(BASELINE_FOLDER_TYPES.values()),
        f"types={catalog.resolve_preset('organization')!r}",
    )

    with tempfile.TemporaryDirectory(prefix="wiki-catalog-duplicate-") as td:
        root = Path(td)
        path = root / "entity-catalog.json"
        write_catalog(
            path,
            [baseline_type("concepts", "concept"), baseline_type("concepts", "idea")],
        )
        try:
            load_entity_catalog(path)
        except CatalogError as exc:
            duplicate_rejected = "duplicate folder 'concepts'" in str(exc)
        else:
            duplicate_rejected = False
        results.record(
            "duplicate-folder-rejected",
            duplicate_rejected,
            "catalog accepted duplicate folder ownership",
        )

    with tempfile.TemporaryDirectory(prefix="wiki-setup-plan-") as td:
        root = Path(td)
        (root / "wiki" / "concepts").mkdir(parents=True)
        (root / "wiki" / "concepts" / ".gitkeep").write_text("", encoding="utf-8")
        (root / "wiki" / "products").mkdir()
        (root / "wiki" / "products" / ".gitkeep").write_text("", encoding="utf-8")
        before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
        plan = plan_wiki_setup(
            root,
            catalog,
            selected_preset="organization",
            requested_active_types=("source", "concept"),
        )
        after = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
        results.record(
            "planner-is-read-only",
            before == after,
            f"before={before!r}; after={after!r}",
        )
        results.record(
            "planner-reports-folder-delta",
            plan.create_folders == ("sources",)
            and plan.remove_folders == ("products",)
            and not plan.blocked_removals
            and not plan.errors,
            repr(plan),
        )
        cli = subprocess.run(
            [
                sys.executable,
                "scripts/plan_wiki_setup.py",
                "--repo-root",
                str(root),
                "--preset",
                "organization",
                "--active",
                "source,concept",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )
        try:
            cli_plan = json.loads(cli.stdout)
        except json.JSONDecodeError:
            cli_plan = {}
        results.record(
            "planner-cli-renders-deterministic-json",
            cli.returncode == 0
            and cli_plan.get("valid") is True
            and cli_plan.get("create_folders") == ["sources"]
            and cli_plan.get("remove_folders") == ["products"],
            f"exit={cli.returncode}; stdout={cli.stdout!r}; stderr={cli.stderr!r}",
        )

    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
