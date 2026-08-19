#!/usr/bin/env python3
"""Validated entity catalog and read-only setup planning interface.

Callers use the typed catalog and plan objects exported here; the JSON shape,
folder inspection, normalization, and fail-closed validation stay private to
this module. Planning never writes to the repository.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CATALOG_PATH = Path(__file__).with_name("entity-catalog.json")
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATALOG_FIELDS = {"schema_version", "description", "presets", "types"}
TYPE_FIELDS = {
    "folder",
    "type",
    "purpose",
    "presets",
    "review_date",
    "authority_freshness",
    "verification",
}
REVIEW_DATE_VALUES = {"expected", "optional"}
AUTHORITY_FRESHNESS_VALUES = {
    "contextual",
    "current-state",
    "immutable-source",
    "stable-meaning",
}
VERIFICATION_VALUES = {
    "before-consequential-action",
    "when-authority-requires",
}


class CatalogError(ValueError):
    """The governed entity catalog is missing, unreadable, or invalid."""


@dataclass(frozen=True)
class EntityTypeSpec:
    folder: str
    type_name: str
    purpose: str
    presets: tuple[str, ...]
    review_date: str
    authority_freshness: str
    verification: str


@dataclass(frozen=True)
class EntityCatalog:
    description: str
    presets: tuple[str, ...]
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

    def resolve_preset(self, preset: str) -> tuple[str, ...]:
        if preset not in self.presets:
            raise CatalogError(f"unknown preset {preset!r}")
        return tuple(
            entry.type_name for entry in self.entries if preset in entry.presets
        )


@dataclass(frozen=True)
class WikiSetupPlan:
    selected_preset: str
    active_types: tuple[str, ...]
    create_folders: tuple[str, ...]
    remove_folders: tuple[str, ...]
    blocked_removals: tuple[str, ...]
    advisories: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors and not self.blocked_removals


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{label} must be a nonempty string")
    return value.strip()


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CatalogError(f"{label} must be a nonempty string list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise CatalogError(f"{label} must contain only nonempty strings")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise CatalogError(f"{label} must not contain duplicates")
    return normalized


def _enum(value: object, label: str, allowed: set[str]) -> str:
    normalized = _nonempty_string(value, label)
    if normalized not in allowed:
        raise CatalogError(
            f"{label} must be one of {', '.join(sorted(allowed))}; got {normalized!r}"
        )
    return normalized


def _parse_entry(
    value: object,
    index: int,
    known_presets: tuple[str, ...],
) -> EntityTypeSpec:
    label = f"types[{index}]"
    if not isinstance(value, dict):
        raise CatalogError(f"{label} must be an object")
    if set(value) != TYPE_FIELDS:
        raise CatalogError(f"{label} fields differ from the catalog contract")
    folder = _nonempty_string(value.get("folder"), f"{label}.folder")
    type_name = _nonempty_string(value.get("type"), f"{label}.type")
    if not KEBAB_RE.fullmatch(folder):
        raise CatalogError(f"{label}.folder is not kebab-case: {folder!r}")
    if not KEBAB_RE.fullmatch(type_name):
        raise CatalogError(f"{label}.type is not kebab-case: {type_name!r}")
    presets = _string_list(value.get("presets"), f"{label}.presets")
    unknown_presets = sorted(set(presets) - set(known_presets))
    if unknown_presets:
        raise CatalogError(
            f"{label}.presets contains unknown values: {', '.join(unknown_presets)}"
        )
    return EntityTypeSpec(
        folder=folder,
        type_name=type_name,
        purpose=_nonempty_string(value.get("purpose"), f"{label}.purpose"),
        presets=presets,
        review_date=_enum(
            value.get("review_date"), f"{label}.review_date", REVIEW_DATE_VALUES
        ),
        authority_freshness=_enum(
            value.get("authority_freshness"),
            f"{label}.authority_freshness",
            AUTHORITY_FRESHNESS_VALUES,
        ),
        verification=_enum(
            value.get("verification"),
            f"{label}.verification",
            VERIFICATION_VALUES,
        ),
    )


def load_entity_catalog(path: Optional[Path] = None) -> EntityCatalog:
    catalog_path = CATALOG_PATH if path is None else path
    try:
        raw = json.loads(
            catalog_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except CatalogError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"cannot read entity catalog: {exc}") from exc
    if not isinstance(raw, dict):
        raise CatalogError("catalog top level must be an object")
    if set(raw) != CATALOG_FIELDS:
        raise CatalogError("catalog top-level fields differ from the contract")
    if raw.get("schema_version") != 1 or isinstance(raw.get("schema_version"), bool):
        raise CatalogError("catalog schema_version must be integer 1")
    presets = _string_list(raw.get("presets"), "presets")
    if any(not KEBAB_RE.fullmatch(preset) for preset in presets):
        raise CatalogError("preset names must be kebab-case")
    values = raw.get("types")
    if not isinstance(values, list) or not values:
        raise CatalogError("types must be a nonempty list")
    entries = tuple(_parse_entry(value, index, presets) for index, value in enumerate(values))
    folders = [entry.folder for entry in entries]
    type_names = [entry.type_name for entry in entries]
    duplicate_folders = sorted({folder for folder in folders if folders.count(folder) > 1})
    duplicate_types = sorted({name for name in type_names if type_names.count(name) > 1})
    if duplicate_folders:
        raise CatalogError(f"duplicate folder {duplicate_folders[0]!r}")
    if duplicate_types:
        raise CatalogError(f"duplicate type {duplicate_types[0]!r}")
    for preset in presets:
        if not any(preset in entry.presets for entry in entries):
            raise CatalogError(f"preset {preset!r} has no entity types")
    return EntityCatalog(
        description=_nonempty_string(raw.get("description"), "description"),
        presets=presets,
        entries=entries,
    )


def _placeholder_only(folder: Path) -> bool:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return False
    if not entries:
        return True
    return len(entries) == 1 and entries[0].name == ".gitkeep" and entries[0].is_file()


def plan_wiki_setup(
    repo_root: Path,
    catalog: EntityCatalog,
    *,
    selected_preset: str,
    requested_active_types: tuple[str, ...],
) -> WikiSetupPlan:
    errors: list[str] = []
    try:
        preset_types = catalog.resolve_preset(selected_preset)
    except CatalogError as exc:
        preset_types = ()
        errors.append(str(exc))

    requested = tuple(dict.fromkeys(value.strip() for value in requested_active_types if value.strip()))
    active_types = requested or preset_types
    unknown_types = sorted(set(active_types) - set(catalog.type_folders))
    if unknown_types:
        errors.append("unsupported active types: " + ", ".join(unknown_types))
    active_types = tuple(
        entry.type_name for entry in catalog.entries if entry.type_name in active_types
    )
    active_folders = {catalog.type_folders[type_name] for type_name in active_types}
    wiki_root = repo_root / "wiki"
    existing_folders = {
        path.name
        for path in wiki_root.iterdir()
        if path.is_dir() and path.name in catalog.folder_types
    } if wiki_root.exists() else set()
    unknown_folders = sorted(
        path.name
        for path in wiki_root.iterdir()
        if path.is_dir() and path.name not in catalog.folder_types
    ) if wiki_root.exists() else []
    if unknown_folders:
        errors.append("unsupported entity folders: " + ", ".join(unknown_folders))
    inactive = sorted(existing_folders - active_folders)
    remove_folders = tuple(
        folder for folder in inactive if _placeholder_only(wiki_root / folder)
    )
    blocked_removals = tuple(
        folder for folder in inactive if not _placeholder_only(wiki_root / folder)
    )
    return WikiSetupPlan(
        selected_preset=selected_preset,
        active_types=active_types,
        create_folders=tuple(sorted(active_folders - existing_folders)),
        remove_folders=remove_folders,
        blocked_removals=blocked_removals,
        advisories=(),
        errors=tuple(errors),
    )


__all__ = [
    "CatalogError",
    "EntityCatalog",
    "EntityTypeSpec",
    "WikiSetupPlan",
    "load_entity_catalog",
    "plan_wiki_setup",
]
