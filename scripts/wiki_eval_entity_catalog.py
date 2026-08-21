#!/usr/bin/env python3
"""Behavior checks for the permanent entity catalog and live folder validation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from eval_lib import Results
from wiki_entity_catalog import CatalogError, load_entity_catalog, validate_configured_layout


CATALOG_PATH = Path(__file__).with_name("entity-catalog.json")
EXPECTED_ENTITY_FOLDER_TYPES = {
    "analyses": "analysis",
    "competitors": "competitor",
    "concepts": "concept",
    "customers": "customer",
    "decisions": "decision",
    "features": "feature",
    "goals": "goal",
    "health": "health",
    "initiatives": "initiative",
    "investments": "investment",
    "learnings": "learning",
    "metrics": "metric",
    "partners": "partner",
    "people": "person",
    "personas": "persona",
    "policies": "policy",
    "processes": "process",
    "products": "product",
    "projects": "project",
    "properties": "property",
    "skills": "skill",
    "sources": "source",
    "systems": "system",
    "teams": "team",
}


def main() -> int:
    results = Results()
    catalog = load_entity_catalog()
    results.record(
        "live-catalog-matches-exact-governed-folder-type-contract",
        catalog.folder_types == EXPECTED_ENTITY_FOLDER_TYPES
        and catalog.type_folders
        == {type_name: folder for folder, type_name in EXPECTED_ENTITY_FOLDER_TYPES.items()},
        repr(catalog),
    )
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    results.record(
        "live-catalog-contains-no-setup-presets",
        "presets" not in raw and all("presets" not in value for value in raw["types"]),
        repr(raw),
    )

    with tempfile.TemporaryDirectory(prefix="wiki-live-layout-") as temporary:
        root = Path(temporary)
        (root / "wiki/sources").mkdir(parents=True)
        (root / "wiki/concepts").mkdir()
        (root / "wiki/domain.md").write_text(
            "---\ntitle: Domain\ntype: domain\ncreated: 2026-08-20\nupdated: 2026-08-20\n"
            "status: configured\norg: Example\ndomain: Example knowledge\n"
            "entity_types_active:\n  - concept\n  - source\n"
            "raw_buckets:\n  - documents\nexample_queries:\n  - One?\n  - Two?\n  - Three?\n"
            "---\n\n# Domain\n",
            encoding="utf-8",
        )
        validation = validate_configured_layout(root, catalog)
        results.record("configured-live-folder-layout-passes", not validation.errors, repr(validation))
        (root / "wiki/teams").mkdir()
        drift = validate_configured_layout(root, catalog)
        results.record(
            "inactive-live-folder-fails",
            "inactive entity folders present: teams" in drift.errors,
            repr(drift),
        )
        (root / "wiki/teams").rmdir()
        domain_path = root / "wiki/domain.md"
        domain_path.write_text(
            domain_path.read_text(encoding="utf-8").replace(
                "  - concept\n  - source\n",
                "  - concept\n  - concept\n  - source\n",
            ),
            encoding="utf-8",
        )
        duplicate = validate_configured_layout(root, catalog)
        results.record(
            "duplicate-live-active-type-fails",
            "configured wiki active entity types must not contain duplicates"
            in duplicate.errors,
            repr(duplicate),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-catalog-invalid-") as temporary:
        path = Path(temporary) / "catalog.json"
        invalid = dict(raw)
        invalid["presets"] = ["personal"]
        path.write_text(json.dumps(invalid), encoding="utf-8")
        try:
            load_entity_catalog(path)
        except CatalogError:
            rejected = True
        else:
            rejected = False
        results.record("setup-preset-field-is-rejected-by-live-catalog", rejected)
    return results.finish()


if __name__ == "__main__":
    raise SystemExit(main())
