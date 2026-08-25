#!/usr/bin/env python3
"""Validate prompt-artifact ownership, review clocks, and removal tests."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from _strict_json import DuplicateJsonKeyError, reject_duplicate_json_keys


PROMPT_ARTIFACT_REGISTRY = Path("scripts/prompt-artifacts.json")
ROOT_PROMPT_PATHS = {
    "AGENTS.md", "CLAUDE.md", "CONTEXT.md", "README.md", "REFERENCES.md",
    "wiki/domain.md",
}
GENERATED_PROMPT_ROOTS = (Path(".agents/skills"), Path(".claude/commands"))
REVIEW_TRIGGERS = ["harness-change", "model-change"]
COLLECTION_FIELDS = {
    "artifact_id", "paths", "owner", "reason", "last_reviewed", "last_useful",
    "review_interval_days", "removal_test",
}


def expected_prompt_artifact_paths(repo_root: Path) -> list[str]:
    """Return every canonical prompt path governed by the registry."""
    paths = {path for path in ROOT_PROMPT_PATHS if (repo_root / path).is_file()}
    paths.update(
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "workflows").rglob("*.md")
        if path.is_file()
    )
    for relative_root in GENERATED_PROMPT_ROOTS:
        artifact_root = repo_root / relative_root
        if artifact_root.is_dir():
            paths.update(
                path.relative_to(repo_root).as_posix()
                for path in artifact_root.rglob("*.md")
                if path.is_file()
            )
    if (repo_root / "scripts/wiki-wrapper-contract.json").is_file():
        paths.add("scripts/wiki-wrapper-contract.json")
    return sorted(paths)


def load_prompt_artifact_registry(path: Path) -> dict[str, object]:
    """Load strict registry JSON without accepting duplicate keys."""
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        raise ValueError(f"cannot load prompt artifact registry: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("prompt artifact registry must be a JSON object")
    return value


def _iso_date(value: object, field: str, errors: list[str]) -> date | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be an ISO date")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field} must be an ISO date")
        return None


def prompt_artifact_registry_errors(
    registry: dict[str, object], *, repo_root: Path
) -> list[str]:
    """Return structural, ownership, and complete-coverage errors."""
    errors: list[str] = []
    if set(registry) != {"schema_version", "description", "review_triggers", "collections"}:
        errors.append("registry has missing or unknown fields")
    if registry.get("schema_version") != 1 or isinstance(registry.get("schema_version"), bool):
        errors.append("schema_version must equal integer 1")
    if not isinstance(registry.get("description"), str) or not registry["description"].strip():
        errors.append("description must be non-empty")
    if registry.get("review_triggers") != REVIEW_TRIGGERS:
        errors.append(f"review_triggers must equal {REVIEW_TRIGGERS}")
    collections = registry.get("collections")
    if not isinstance(collections, list) or not collections:
        return [*errors, "collections must be a non-empty list"]
    artifact_ids: list[str] = []
    governed_paths: list[str] = []
    for index, collection in enumerate(collections):
        label = f"collections[{index}]"
        if not isinstance(collection, dict) or set(collection) != COLLECTION_FIELDS:
            errors.append(f"{label} has missing or unknown fields")
            continue
        artifact_id = collection.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            errors.append(f"{label}.artifact_id must be non-empty")
        else:
            artifact_ids.append(artifact_id)
        paths = collection.get("paths")
        if (
            not isinstance(paths, list)
            or not paths
            or not all(isinstance(path, str) and path for path in paths)
            or paths != sorted(set(paths))
        ):
            errors.append(f"{label}.paths must be a sorted unique non-empty list")
            paths = []
        for relative in paths:
            governed_paths.append(relative)
            if not (repo_root / relative).is_file():
                errors.append(f"{label}.paths names a missing file: {relative}")
        owner = collection.get("owner")
        if not isinstance(owner, str) or not (repo_root / owner).is_file():
            errors.append(f"{label}.owner must name an existing file")
        for field in ("reason", "removal_test"):
            if not isinstance(collection.get(field), str) or not collection[field].strip():
                errors.append(f"{label}.{field} must be non-empty")
        _iso_date(collection.get("last_reviewed"), f"{label}.last_reviewed", errors)
        _iso_date(collection.get("last_useful"), f"{label}.last_useful", errors)
        interval = collection.get("review_interval_days")
        if not isinstance(interval, int) or isinstance(interval, bool) or interval <= 0:
            errors.append(f"{label}.review_interval_days must be a positive integer")
    if artifact_ids != sorted(set(artifact_ids)):
        errors.append("artifact_id values must be sorted and unique")
    expected = expected_prompt_artifact_paths(repo_root)
    if len(governed_paths) != len(set(governed_paths)):
        errors.append("governed prompt paths must be globally unique")
    if sorted(governed_paths) != expected:
        missing = sorted(set(expected) - set(governed_paths))
        extra = sorted(set(governed_paths) - set(expected))
        errors.append(f"prompt path coverage differs; missing={missing}; extra={extra}")
    return errors


def prompt_artifact_reviews_due(
    registry: dict[str, object], *, as_of: date
) -> list[str]:
    """Return artifact IDs whose review clock has expired."""
    due: list[str] = []
    collections = registry.get("collections")
    if not isinstance(collections, list):
        return due
    for collection in collections:
        if not isinstance(collection, dict):
            continue
        try:
            reviewed = date.fromisoformat(str(collection["last_reviewed"]))
            interval = int(collection["review_interval_days"])
            artifact_id = str(collection["artifact_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if reviewed + timedelta(days=interval) <= as_of:
            due.append(artifact_id)
    return sorted(due)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Check prompt artifact governance.")
    command.add_argument("command", choices=("check", "status"))
    command.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    command.add_argument("--as-of", default=date.today().isoformat())
    return command


def main() -> int:
    args = parser().parse_args()
    root = args.repo_root.resolve()
    try:
        registry = load_prompt_artifact_registry(root / PROMPT_ARTIFACT_REGISTRY)
        errors = prompt_artifact_registry_errors(registry, repo_root=root)
        as_of = date.fromisoformat(args.as_of)
    except ValueError as exc:
        print(f"Prompt artifact check failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"Prompt artifact check failed: {error}", file=sys.stderr)
        return 1
    if args.command == "check":
        print("Prompt artifact registry is valid and complete.")
        return 0
    due = prompt_artifact_reviews_due(registry, as_of=as_of)
    print(f"Prompt artifact reviews due as of {as_of}: {len(due)}")
    for artifact_id in due:
        print(f"  {artifact_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "expected_prompt_artifact_paths",
    "load_prompt_artifact_registry",
    "prompt_artifact_registry_errors",
    "prompt_artifact_reviews_due",
]
