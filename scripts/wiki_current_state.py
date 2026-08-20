#!/usr/bin/env python3
"""Typed configuration and evaluation for optional current-state owners."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath


CURRENT_STATE_REGISTRY_PATH = Path("scripts/current-state-owners.json")
OWNER_PATH_RE = re.compile(
    r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*\.md\Z"
)


class CurrentStateRegistryError(ValueError):
    """The current-state registry is absent or violates its strict schema."""


@dataclass(frozen=True)
class CurrentStateOwnerRegistry:
    enabled: bool
    owners: tuple[str, ...]


@dataclass(frozen=True)
class CurrentStatePage:
    path: str
    is_source: bool
    updated: date | None
    status_date: date | None
    freshness: date | None
    references: frozenset[str]
    authority_kind: str | None
    authority_ref: str | None


@dataclass(frozen=True)
class StatusDrift:
    page: str
    owner: str
    page_freshness: date
    owner_status: date


@dataclass(frozen=True)
class OwnerSelfDrift:
    owner: str
    updated: date
    status_date: date


@dataclass(frozen=True)
class AuthorityOwnerMismatch:
    page: str
    authority_ref: str


@dataclass(frozen=True)
class CurrentStateEvaluation:
    status_drift: tuple[StatusDrift, ...]
    owner_status_missing: tuple[str, ...]
    owner_self_drift: tuple[OwnerSelfDrift, ...]
    authority_owner_mismatch: tuple[AuthorityOwnerMismatch, ...]
    owner_registry_empty: bool


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CurrentStateRegistryError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _canonical_owner_path(value: object) -> str:
    if not isinstance(value, str):
        raise CurrentStateRegistryError("every owner must be a string path")
    path = PurePosixPath(value)
    if (
        not value
        or value != path.as_posix()
        or path.is_absolute()
        or "\\" in value
        or len(path.parts) != 2
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix != ".md"
        or not OWNER_PATH_RE.fullmatch(value)
    ):
        raise CurrentStateRegistryError(
            f"owner {value!r} must be a canonical folder/name.md path relative to wiki/"
        )
    return value


def load_current_state_registry(
    path: Path = CURRENT_STATE_REGISTRY_PATH,
) -> CurrentStateOwnerRegistry:
    """Load the strict opt-in registry; absence is a configuration error."""
    if not path.is_file() or path.is_symlink():
        raise CurrentStateRegistryError("registry is missing or is not a regular file")
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except CurrentStateRegistryError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurrentStateRegistryError(f"unreadable JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise CurrentStateRegistryError("top level must be a JSON object")
    if set(raw) != {"schema_version", "enabled", "owners"}:
        raise CurrentStateRegistryError(
            "fields must be exactly schema_version, enabled, and owners"
        )
    if raw["schema_version"] != 1 or isinstance(raw["schema_version"], bool):
        raise CurrentStateRegistryError("schema_version must equal 1")
    if not isinstance(raw["enabled"], bool):
        raise CurrentStateRegistryError("enabled must be a boolean")
    owners_raw = raw["owners"]
    if not isinstance(owners_raw, list):
        raise CurrentStateRegistryError("owners must be an array")
    owners = tuple(_canonical_owner_path(value) for value in owners_raw)
    if len(set(owners)) != len(owners):
        raise CurrentStateRegistryError("owners must be unique")
    if owners != tuple(sorted(owners)):
        raise CurrentStateRegistryError("owners must be sorted")
    if not raw["enabled"] and owners:
        raise CurrentStateRegistryError("a disabled registry must have no owners")
    return CurrentStateOwnerRegistry(enabled=raw["enabled"], owners=owners)


def validate_current_state_registry(
    registry: CurrentStateOwnerRegistry,
    repo_root: Path,
) -> tuple[str, ...]:
    """Return deterministic owner-page existence and authority errors."""
    if not registry.enabled:
        return ()
    errors: list[str] = []
    for owner in registry.owners:
        path = repo_root / "wiki" / owner
        if path.is_symlink() or not path.is_file():
            errors.append(f"owner {owner!r} is missing or is not a regular file")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"owner {owner!r} is not readable UTF-8: {exc}")
            continue
        parts = text.split("---", 2)
        frontmatter = parts[1] if len(parts) == 3 and not parts[0] else ""
        if not any(
            line.strip() == "authority_freshness: current-state"
            for line in frontmatter.splitlines()
        ):
            errors.append(
                f"owner {owner!r} must declare authority_freshness: current-state"
            )
    return tuple(errors)


def evaluate_current_state(
    registry: CurrentStateOwnerRegistry,
    pages: tuple[CurrentStatePage, ...],
) -> CurrentStateEvaluation:
    """Evaluate the nonblocking drift family over one already-parsed corpus."""
    if not registry.enabled:
        return CurrentStateEvaluation((), (), (), (), False)

    by_path = {page.path: page for page in pages}
    owners = set(registry.owners)
    missing_status: list[str] = []
    self_drift: list[OwnerSelfDrift] = []
    status_drift: list[StatusDrift] = []
    mismatches: list[AuthorityOwnerMismatch] = []

    for owner_path in registry.owners:
        owner = by_path.get(owner_path)
        if owner is None:
            continue
        if owner.status_date is None:
            missing_status.append(owner_path)
        elif owner.updated is not None and owner.status_date > owner.updated:
            self_drift.append(OwnerSelfDrift(owner_path, owner.updated, owner.status_date))

    owner_statuses = {
        path: page.status_date
        for path, page in by_path.items()
        if path in owners and page.status_date is not None
    }
    for page in pages:
        if page.authority_kind == "owner-page" and page.authority_ref:
            ref = page.authority_ref.removeprefix("wiki/")
            if ref != page.path and ref not in owners:
                mismatches.append(AuthorityOwnerMismatch(page.path, page.authority_ref))
        if page.is_source or page.freshness is None:
            continue
        for owner_path in sorted(page.references & owners):
            if owner_path == page.path:
                continue
            status = owner_statuses.get(owner_path)
            if status is not None and status > page.freshness:
                status_drift.append(
                    StatusDrift(page.path, owner_path, page.freshness, status)
                )

    return CurrentStateEvaluation(
        status_drift=tuple(sorted(status_drift, key=lambda item: (item.page, item.owner))),
        owner_status_missing=tuple(sorted(missing_status)),
        owner_self_drift=tuple(sorted(self_drift, key=lambda item: item.owner)),
        authority_owner_mismatch=tuple(
            sorted(mismatches, key=lambda item: (item.page, item.authority_ref))
        ),
        owner_registry_empty=not registry.owners and bool(pages),
    )


__all__ = [
    "CURRENT_STATE_REGISTRY_PATH",
    "AuthorityOwnerMismatch",
    "CurrentStateEvaluation",
    "CurrentStateOwnerRegistry",
    "CurrentStatePage",
    "CurrentStateRegistryError",
    "OwnerSelfDrift",
    "StatusDrift",
    "evaluate_current_state",
    "load_current_state_registry",
    "validate_current_state_registry",
]
