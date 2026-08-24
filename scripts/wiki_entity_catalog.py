#!/usr/bin/env python3
"""Validated entity vocabulary and live active-folder contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from _wiki_parse import FrontmatterError, frontmatter_block


CATALOG_PATH = Path(__file__).with_name("entity-catalog.json")
KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATALOG_FIELDS = {"schema_version", "description", "types"}
TYPE_FIELDS = {
    "folder", "type", "purpose", "review_date", "authority_freshness",
    "verification",
}
REVIEW_DATE_VALUES = {"expected", "optional"}
AUTHORITY_FRESHNESS_VALUES = {
    "contextual", "current-state", "immutable-source", "stable-meaning",
}
VERIFICATION_VALUES = {
    "before-consequential-action", "when-authority-requires",
}


class CatalogError(ValueError):
    """The permanent entity catalog or domain declaration is invalid."""


@dataclass(frozen=True)
class EntityTypeSpec:
    """One governed live wiki folder and its authoring semantics."""

    folder: str
    type_name: str
    purpose: str
    review_date: str
    authority_freshness: str
    verification: str


@dataclass(frozen=True)
class EntityCatalog:
    """Permanent collection of supported live wiki entity types."""

    description: str
    entries: tuple[EntityTypeSpec, ...]

    @property
    def folder_types(self) -> dict[str, str]:
        return {entry.folder: entry.type_name for entry in self.entries}

    @property
    def type_folders(self) -> dict[str, str]:
        return {entry.type_name: entry.folder for entry in self.entries}

    @property
    def review_date_expected_folders(self) -> tuple[str, ...]:
        return tuple(
            entry.folder for entry in self.entries if entry.review_date == "expected"
        )


@dataclass(frozen=True)
class DomainConfiguration:
    """Live domain state required by repository validation."""

    status: str


@dataclass(frozen=True)
class ConfiguredLayoutValidation:
    """Deterministic folder-layout errors for a template or configured wiki."""

    errors: tuple[str, ...]


def _reject_duplicate_catalog_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"duplicate catalog key {key!r}")
        result[key] = value
    return result


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CatalogError(f"{label} must be a nonempty trimmed string")
    return value


def _catalog_enum(value: object, label: str, allowed: set[str]) -> str:
    normalized = _nonempty_string(value, label)
    if normalized not in allowed:
        raise CatalogError(f"{label} must be one of {', '.join(sorted(allowed))}")
    return normalized


def _parse_entity_type(value: object, index: int) -> EntityTypeSpec:
    label = f"types[{index}]"
    if not isinstance(value, dict) or set(value) != TYPE_FIELDS:
        raise CatalogError(f"{label} fields differ from the live catalog contract")
    folder = _nonempty_string(value.get("folder"), f"{label}.folder")
    type_name = _nonempty_string(value.get("type"), f"{label}.type")
    if not KEBAB_CASE_RE.fullmatch(folder) or not KEBAB_CASE_RE.fullmatch(type_name):
        raise CatalogError(f"{label} folder and type must be kebab-case")
    return EntityTypeSpec(
        folder=folder,
        type_name=type_name,
        purpose=_nonempty_string(value.get("purpose"), f"{label}.purpose"),
        review_date=_catalog_enum(
            value.get("review_date"), f"{label}.review_date", REVIEW_DATE_VALUES
        ),
        authority_freshness=_catalog_enum(
            value.get("authority_freshness"),
            f"{label}.authority_freshness",
            AUTHORITY_FRESHNESS_VALUES,
        ),
        verification=_catalog_enum(
            value.get("verification"), f"{label}.verification", VERIFICATION_VALUES
        ),
    )


def load_entity_catalog(path: Optional[Path] = None) -> EntityCatalog:
    """Load the permanent catalog of always-available entity types."""
    catalog_path = CATALOG_PATH if path is None else path
    try:
        raw = json.loads(
            catalog_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_catalog_keys,
        )
    except CatalogError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read entity catalog: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != CATALOG_FIELDS:
        raise CatalogError("catalog fields differ from the live contract")
    if raw.get("schema_version") != 2 or isinstance(raw.get("schema_version"), bool):
        raise CatalogError("catalog schema_version must be integer 2")
    values = raw.get("types")
    if not isinstance(values, list) or not values:
        raise CatalogError("types must be a nonempty list")
    entries = tuple(_parse_entity_type(value, index) for index, value in enumerate(values))
    folders = [entry.folder for entry in entries]
    type_names = [entry.type_name for entry in entries]
    if len(set(folders)) != len(folders):
        raise CatalogError("catalog contains a duplicate folder")
    if len(set(type_names)) != len(type_names):
        raise CatalogError("catalog contains a duplicate type")
    if "property" in type_names and entries[type_names.index("property")].folder != "properties":
        raise CatalogError("property must map to properties")
    return EntityCatalog(
        description=_nonempty_string(raw.get("description"), "description"),
        entries=entries,
    )


def _field_lines(block: str, field: str) -> tuple[Optional[str], list[str]]:
    lines = block.splitlines()
    prefix = f"{field}:"
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        scalar = line[len(prefix):].strip()
        nested: list[str] = []
        for following in lines[index + 1:]:
            if following.startswith("  - "):
                nested.append(following[4:].strip().strip("\"'"))
                continue
            break
        return scalar, nested
    return None, []


def read_domain_configuration(repo_root: Path) -> DomainConfiguration:
    """Require the ready-to-use domain state used by live validation."""
    try:
        block = frontmatter_block(
            (repo_root / "wiki/domain.md").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, FrontmatterError) as exc:
        raise CatalogError(f"cannot read wiki/domain.md configuration: {exc}") from exc
    if not block:
        raise CatalogError("wiki/domain.md has no frontmatter configuration")
    status_value, _ = _field_lines(block, "status")
    status = (status_value or "").strip("\"'")
    if status not in {"configured", "unconfigured"}:
        raise CatalogError("wiki/domain.md status must be configured or unconfigured")
    return DomainConfiguration(status=status)


def validate_configured_layout(
    repo_root: Path,
    catalog: EntityCatalog,
) -> ConfiguredLayoutValidation:
    """Validate that a live wiki contains every governed entity folder."""
    try:
        configuration = read_domain_configuration(repo_root)
    except CatalogError as exc:
        return ConfiguredLayoutValidation((str(exc),))
    wiki_root = repo_root / "wiki"
    actual_folders = {
        path.name for path in wiki_root.iterdir()
        if path.is_dir() and path.name in catalog.folder_types
    }
    unknown_folders = sorted(
        path.name for path in wiki_root.iterdir()
        if path.is_dir() and path.name not in catalog.folder_types
    )
    errors: list[str] = []
    if unknown_folders:
        errors.append("unsupported entity folders: " + ", ".join(unknown_folders))
    # Legacy fixture state remains readable so isolated tooling evals do not
    # need a full Git-backed wiki. The shipped repository is always configured.
    if configuration.status == "unconfigured":
        return ConfiguredLayoutValidation(tuple(errors))
    expected_folders = set(catalog.folder_types)
    missing = sorted(expected_folders - actual_folders)
    if missing:
        errors.append("governed entity folders missing: " + ", ".join(missing))
    return ConfiguredLayoutValidation(tuple(errors))


__all__ = [
    "CatalogError", "ConfiguredLayoutValidation", "DomainConfiguration",
    "EntityCatalog", "EntityTypeSpec", "load_entity_catalog",
    "read_domain_configuration", "validate_configured_layout",
]
