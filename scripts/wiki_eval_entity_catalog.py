#!/usr/bin/env python3
"""Behavioral regression suite for the entity catalog and setup planner."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from eval_lib import Results, page
from wiki_entity_catalog import (
    CatalogError,
    load_entity_catalog,
    plan_wiki_setup,
    validate_configured_layout,
)


EXPECTED_FOLDER_TYPES = {
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

ORGANIZATION_TYPES = {
    "source", "concept", "decision", "person", "analysis", "product",
    "feature", "persona", "customer", "competitor", "initiative", "metric",
    "team", "system", "process", "policy", "partner", "project", "goal",
    "skill", "learning",
}
PERSONAL_TYPES = {
    "source", "concept", "decision", "person", "analysis", "project", "goal",
    "skill", "learning", "health", "investment", "property",
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


def write_domain(
    root: Path,
    *,
    status: str,
    active_types: tuple[str, ...],
    version: int | None = None,
    preset: str | None = None,
    custom_types: tuple[str, ...] | None = None,
) -> None:
    lines = ["---", f"status: {status}"]
    if version is not None:
        lines.append(f"configuration_version: {version}")
    if preset is not None:
        lines.append(f"entity_preset: {preset}")
    lines.append("entity_types_active:")
    lines.extend(f"  - {value}" for value in active_types)
    if custom_types is not None:
        lines.append("entity_types_custom:")
        lines.extend(f"  - {value}" for value in custom_types)
    lines.extend(["---", "", "# Domain", ""])
    (root / "wiki").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "domain.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    results = Results()

    catalog = load_entity_catalog()
    results.record(
        "complete-folder-type-contract",
        catalog.folder_types == EXPECTED_FOLDER_TYPES,
        f"folder_types={catalog.folder_types!r}",
    )
    results.record(
        "exact-preset-memberships",
        set(catalog.resolve_preset("organization")) == ORGANIZATION_TYPES
        and set(catalog.resolve_preset("personal")) == PERSONAL_TYPES
        and set(catalog.resolve_preset("hybrid")) == set(EXPECTED_FOLDER_TYPES.values()),
        f"organization={catalog.resolve_preset('organization')!r}; "
        f"personal={catalog.resolve_preset('personal')!r}; "
        f"hybrid={catalog.resolve_preset('hybrid')!r}",
    )
    results.record(
        "irregular-folder-mappings",
        catalog.folder_types["people"] == "person"
        and catalog.folder_types["policies"] == "policy"
        and catalog.folder_types["processes"] == "process"
        and catalog.folder_types["properties"] == "property",
        repr(catalog.folder_types),
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
        write_domain(
            root,
            status="unconfigured",
            active_types=tuple(EXPECTED_FOLDER_TYPES.values()),
            version=2,
        )
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

    with tempfile.TemporaryDirectory(prefix="wiki-setup-unknown-") as td:
        root = Path(td)
        write_domain(root, status="unconfigured", active_types=(), version=2)
        before = (root / "wiki" / "domain.md").read_bytes()
        plan = plan_wiki_setup(
            root,
            catalog,
            selected_preset="personal",
            requested_active_types=("source", "habit"),
        )
        results.record(
            "unsupported-selection-fails-before-writing",
            not plan.valid
            and plan.errors == ("unsupported active types: habit",)
            and (root / "wiki" / "domain.md").read_bytes() == before
            and not (root / "wiki" / "habits").exists(),
            repr(plan),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-setup-blocked-") as td:
        root = Path(td)
        write_domain(
            root,
            status="configured",
            active_types=("source", "concept"),
            version=2,
            preset="personal",
        )
        (root / "wiki" / "sources").mkdir()
        (root / "wiki" / "concepts").mkdir()
        (root / "wiki" / "products").mkdir()
        (root / "wiki" / "products" / "live-page.md").write_text("body\n", encoding="utf-8")
        plan = plan_wiki_setup(
            root,
            catalog,
            selected_preset="personal",
            requested_active_types=("source", "concept"),
        )
        results.record(
            "nonempty-folder-removal-is-blocked",
            not plan.valid
            and plan.blocked_removals == ("products",)
            and not plan.remove_folders,
            repr(plan),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-layout-") as td:
        root = Path(td)
        write_domain(
            root,
            status="configured",
            active_types=("source", "property"),
            version=2,
            preset="personal",
        )
        (root / "wiki" / "sources").mkdir()
        (root / "wiki" / "properties").mkdir()
        validation = validate_configured_layout(root, catalog)
        results.record(
            "configured-layout-matches-active-types",
            not validation.errors and not validation.advisories,
            repr(validation),
        )
        applied_plan = plan_wiki_setup(
            root,
            catalog,
            selected_preset="personal",
            requested_active_types=("source", "property"),
        )
        results.record(
            "applied-plan-is-idempotent",
            applied_plan.valid
            and not applied_plan.create_folders
            and not applied_plan.remove_folders
            and not applied_plan.blocked_removals,
            repr(applied_plan),
        )
        (root / "wiki" / "concepts").mkdir()
        drift = validate_configured_layout(root, catalog)
        results.record(
            "configured-layout-rejects-inactive-folder",
            drift.errors == ("inactive entity folders present: concepts",),
            repr(drift),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-layout-legacy-") as td:
        root = Path(td)
        write_domain(
            root,
            status="configured",
            active_types=("source", "concept"),
            custom_types=(),
        )
        (root / "wiki" / "sources").mkdir()
        (root / "wiki" / "concepts").mkdir()
        validation = validate_configured_layout(root, catalog)
        results.record(
            "legacy-configuration-remains-valid-with-advisory",
            not validation.errors
            and "legacy configuration has no configuration_version or entity_preset" in validation.advisories,
            repr(validation),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-layout-custom-") as td:
        root = Path(td)
        write_domain(
            root,
            status="configured",
            active_types=("source",),
            version=2,
            preset="personal",
            custom_types=(),
        )
        (root / "wiki" / "sources").mkdir()
        validation = validate_configured_layout(root, catalog)
        results.record(
            "version-two-rejects-obsolete-custom-field",
            validation.errors == (
                "configuration_version 2 rejects obsolete entity_types_custom",
            ),
            repr(validation),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-layout-custom-legacy-") as td:
        root = Path(td)
        write_domain(
            root,
            status="configured",
            active_types=("source",),
            custom_types=("habit",),
        )
        (root / "wiki" / "sources").mkdir()
        validation = validate_configured_layout(root, catalog)
        results.record(
            "populated-legacy-custom-types-require-manual-resolution",
            "legacy custom types require manual resolution: habit" in validation.errors,
            repr(validation),
        )

    with tempfile.TemporaryDirectory(prefix="wiki-catalog-pages-") as td:
        root = Path(td)
        fixture = Path(__file__).resolve().parent / "fixtures" / "wiki-lint"
        shutil.copytree(fixture / "wiki", root / "wiki")
        shutil.copytree(fixture / "scripts", root / "scripts")
        index = root / "wiki" / "index.md"
        for folder, type_name in EXPECTED_FOLDER_TYPES.items():
            entity_dir = root / "wiki" / folder
            entity_dir.mkdir(exist_ok=True)
            slug = f"catalog-{folder}"
            extra = "source_type: other\n" if type_name == "source" else (
                "agent_use_cases:\n  - catalog contract fixture\n"
            )
            body = "Catalog contract fixture.\n" if type_name == "source" else (
                "Catalog contract fixture.\n\n## Open questions / gaps\n\n"
                "- Fixture page; no real questions.\n"
            )
            (entity_dir / f"{slug}.md").write_text(
                page(
                    title=f"Catalog {folder}",
                    type=type_name,
                    sources='["experience: catalog contract fixture"]',
                    extra=extra,
                    body=body,
                ),
                encoding="utf-8",
            )
            with index.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"| [{slug}.md]({folder}/{slug}.md) | catalog contract fixture |\n"
                )
        lint = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent / "lint.py"), "--tier1"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        results.record(
            "every-catalog-folder-type-pair-passes-tier1",
            lint.returncode == 0,
            lint.stdout + lint.stderr,
        )

    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
