#!/usr/bin/env python3
"""Strict retired-messaging policy for active wiki knowledge pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from _durable_files import read_regular_bytes
from _repo_paths import EXISTING_FILE, resolve_repo_path
from _strict_json import reject_duplicate_json_keys
from wiki_entity_catalog import load_entity_catalog
from wiki_current_state import CurrentStateOwnerRegistry, current_state_page_path


RETIRED_CLAIMS_PATH = Path("scripts/retired-claims.json")
REFRESH_PROFILE_DIRECTORY = Path("workflows/maintenance/refresh/profiles")
ACTIVE_WIKI_META_PAGES = ("domain", "index", "glossary", "overview", "primer", "synthesis")
CLAIM_ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
REPLACEMENT_REF_RE = re.compile(
    r"wiki/[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*\.md\Z"
)
TOP_LEVEL_FIELDS = frozenset({"schema_version", "description", "profiles", "claims"})
CLAIM_FIELDS = frozenset(
    {
        "id",
        "profile",
        "retired_on",
        "phrases",
        "replacement",
        "replacement_ref",
        "reason",
    }
)


class RetiredClaimRegistryError(ValueError):
    """The retired-claim registry is missing or violates its strict schema."""


@dataclass(frozen=True)
class RetiredClaim:
    claim_id: str
    profile: str
    retired_on: date
    phrases: tuple[str, ...]
    replacement: str
    replacement_ref: str
    reason: str


@dataclass(frozen=True)
class RetiredClaimRegistry:
    description: str
    profiles: tuple[str, ...]
    claims: tuple[RetiredClaim, ...]


@dataclass(frozen=True)
class RetiredClaimMention:
    claim_id: str
    phrase: str
    path: str
    line: int


def _one_line_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "\n" in value
        or "\r" in value
    ):
        raise RetiredClaimRegistryError(f"{label} must be one nonempty trimmed line")
    return value


def _calendar_date(value: object, label: str) -> date:
    text = _one_line_text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise RetiredClaimRegistryError(f"{label} must be a real YYYY-MM-DD date") from exc
    if parsed.isoformat() != text:
        raise RetiredClaimRegistryError(f"{label} must be a real YYYY-MM-DD date")
    return parsed


def _replacement_ref(value: object, label: str) -> str:
    text = _one_line_text(value, label)
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or path.as_posix() != text
        or ".." in path.parts
        or not REPLACEMENT_REF_RE.fullmatch(text)
        or len(path.parts) != 3
        or path.parts[1] == "sources"
    ):
        raise RetiredClaimRegistryError(
            f"{label} must be a canonical non-source wiki/folder/name.md path"
        )
    return text


def load_retired_claim_registry(
    path: Path = RETIRED_CLAIMS_PATH,
) -> RetiredClaimRegistry:
    """Load the strict registry without consulting the wiki filesystem."""
    if not path.is_file() or path.is_symlink():
        raise RetiredClaimRegistryError("registry is missing or is not a regular file")
    try:
        raw = json.loads(
            read_regular_bytes(path)[0].decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys
        )
    except RetiredClaimRegistryError:
        raise
    except (OSError, ValueError) as exc:
        raise RetiredClaimRegistryError(f"unreadable JSON: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != TOP_LEVEL_FIELDS:
        raise RetiredClaimRegistryError(
            "fields must be exactly schema_version, description, profiles, and claims"
        )
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise RetiredClaimRegistryError("schema_version must equal 1")
    description = _one_line_text(raw["description"], "description")
    profiles_raw = raw["profiles"]
    if not isinstance(profiles_raw, list) or not profiles_raw:
        raise RetiredClaimRegistryError("profiles must be a nonempty array")
    profiles = tuple(
        _one_line_text(value, f"profiles[{index}]")
        for index, value in enumerate(profiles_raw)
    )
    if any(not CLAIM_ID_RE.fullmatch(profile) for profile in profiles):
        raise RetiredClaimRegistryError("profiles must contain only kebab-case ids")
    if len(set(profiles)) != len(profiles):
        raise RetiredClaimRegistryError("profiles must be unique")
    if profiles != tuple(sorted(profiles)):
        raise RetiredClaimRegistryError("profiles must be sorted")
    claims_raw = raw["claims"]
    if not isinstance(claims_raw, list):
        raise RetiredClaimRegistryError("claims must be an array")

    claims: list[RetiredClaim] = []
    for index, record in enumerate(claims_raw):
        label = f"claims[{index}]"
        if not isinstance(record, dict) or set(record) != CLAIM_FIELDS:
            raise RetiredClaimRegistryError(f"{label} fields differ from the contract")
        claim_id = _one_line_text(record["id"], f"{label}.id")
        if not CLAIM_ID_RE.fullmatch(claim_id):
            raise RetiredClaimRegistryError(f"{label}.id must be kebab-case")
        profile = _one_line_text(record["profile"], f"{label}.profile")
        if profile not in profiles:
            raise RetiredClaimRegistryError(
                f"{label}.profile must name a supported wiki-refresh profile"
            )
        phrases_raw = record["phrases"]
        if not isinstance(phrases_raw, list) or not phrases_raw:
            raise RetiredClaimRegistryError(f"{label}.phrases must be a nonempty array")
        phrases = tuple(
            _one_line_text(value, f"{label}.phrases[{phrase_index}]")
            for phrase_index, value in enumerate(phrases_raw)
        )
        folded = tuple(phrase.casefold() for phrase in phrases)
        if len(set(folded)) != len(folded):
            raise RetiredClaimRegistryError(
                f"{label}.phrases must be unique ignoring case"
            )
        if folded != tuple(sorted(folded)):
            raise RetiredClaimRegistryError(
                f"{label}.phrases must be sorted ignoring case"
            )
        claims.append(
            RetiredClaim(
                claim_id=claim_id,
                profile=profile,
                retired_on=_calendar_date(record["retired_on"], f"{label}.retired_on"),
                phrases=phrases,
                replacement=_one_line_text(record["replacement"], f"{label}.replacement"),
                replacement_ref=_replacement_ref(
                    record["replacement_ref"], f"{label}.replacement_ref"
                ),
                reason=_one_line_text(record["reason"], f"{label}.reason"),
            )
        )
    claim_ids = tuple(claim.claim_id for claim in claims)
    if len(set(claim_ids)) != len(claim_ids):
        raise RetiredClaimRegistryError("claim ids must be unique")
    if claim_ids != tuple(sorted(claim_ids)):
        raise RetiredClaimRegistryError("claims must be sorted by id")
    phrase_owners: dict[str, str] = {}
    for claim in claims:
        for phrase in claim.phrases:
            folded_phrase = phrase.casefold()
            prior_claim = phrase_owners.get(folded_phrase)
            if prior_claim is not None:
                raise RetiredClaimRegistryError(
                    f"phrase {phrase!r} appears in claims {prior_claim!r} and "
                    f"{claim.claim_id!r}"
                )
            phrase_owners[folded_phrase] = claim.claim_id
    return RetiredClaimRegistry(
        description=description, profiles=profiles, claims=tuple(claims)
    )


def validate_retired_claim_registry(
    registry: RetiredClaimRegistry,
    repo_root: Path,
    current_state_registry: CurrentStateOwnerRegistry,
) -> tuple[str, ...]:
    """Validate every replacement against an enrolled current-state owner page."""
    errors: list[str] = []
    profile_directory = repo_root / REFRESH_PROFILE_DIRECTORY
    try:
        cursor = repo_root
        for part in REFRESH_PROFILE_DIRECTORY.parts:
            cursor /= part
            if cursor.is_symlink() or not cursor.is_dir():
                raise ValueError("profile directory is missing or unsafe")
        documented_profiles = tuple(sorted(path.stem for path in profile_directory.glob("*.md")))
        if documented_profiles != registry.profiles:
            raise ValueError("profile ids differ from workflows/maintenance/refresh/profiles/*.md")
        for profile in registry.profiles:
            read_regular_bytes(profile_directory / f"{profile}.md")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    owners = {f"wiki/{owner}" for owner in current_state_registry.owners}
    for claim in registry.claims:
        try:
            path = current_state_page_path(repo_root, claim.replacement_ref.removeprefix("wiki/"))
            read_regular_bytes(path)
        except (OSError, ValueError) as exc:
            errors.append(f"claim {claim.claim_id!r} replacement_ref: {exc}")
        if not current_state_registry.enabled or claim.replacement_ref not in owners:
            errors.append(
                f"claim {claim.claim_id!r} replacement_ref must be enrolled in "
                "scripts/current-state-owners.json"
            )
    return tuple(errors)


def find_retired_claim_mentions(
    registry: RetiredClaimRegistry,
    repo_root: Path,
) -> tuple[RetiredClaimMention, ...]:
    """Find literal retired phrases in active knowledge, excluding historical records."""
    if not registry.claims:
        return ()
    wiki_root = repo_root / "wiki"
    if wiki_root.is_symlink() or not wiki_root.is_dir():
        raise RetiredClaimRegistryError("active wiki root is missing or unsafe")
    paths: list[Path] = []
    for folder in load_entity_catalog().folder_types:
        if folder == "sources":
            continue
        directory = wiki_root / folder
        if directory.is_symlink() or not directory.is_dir():
            raise RetiredClaimRegistryError(f"active entity directory is missing or unsafe: {directory}")
        for path in sorted(directory.glob("*.md")):
            paths.append(current_state_page_path(repo_root, f"{folder}/{path.name}"))
    for name in ACTIVE_WIKI_META_PAGES:
        relative = f"wiki/{name}.md"
        path = repo_root / relative
        if not path.exists() and not path.is_symlink():
            continue  # Optional meta pages need not exist in a configured wiki.
        resolve_repo_path(relative, repo_root=repo_root, allowed_root_files=(relative,), mode=EXISTING_FILE)
        paths.append(path)
    mentions: list[RetiredClaimMention] = []
    for path in paths:
        relative = path.relative_to(wiki_root)
        content, _ = read_regular_bytes(path)
        lines = content.decode("utf-8").splitlines()
        for line_number, line in enumerate(lines, 1):
            folded_line = line.casefold()
            for claim in registry.claims:
                for phrase in claim.phrases:
                    if phrase.casefold() in folded_line:
                        mentions.append(
                            RetiredClaimMention(
                                claim_id=claim.claim_id,
                                phrase=phrase,
                                path=f"wiki/{relative.as_posix()}",
                                line=line_number,
                            )
                        )
    return tuple(
        sorted(
            mentions,
            key=lambda item: (item.path, item.line, item.claim_id, item.phrase.casefold()),
        )
    )


__all__ = [
    "RETIRED_CLAIMS_PATH",
    "RetiredClaim",
    "RetiredClaimMention",
    "RetiredClaimRegistry",
    "RetiredClaimRegistryError",
    "find_retired_claim_mentions",
    "load_retired_claim_registry",
    "validate_retired_claim_registry",
]
