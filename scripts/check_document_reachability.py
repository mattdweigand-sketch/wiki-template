#!/usr/bin/env python3
"""Verify every operational Markdown document is routed from a declared root."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional


MANIFEST_PATH = Path("scripts/document-reachability.json")
MANIFEST_FIELDS = {
    "schema_version",
    "description",
    "roots",
    "operational_directories",
    "excluded_directories",
    "standalone_documents",
}
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


class ReachabilityError(ValueError):
    """The reachability manifest is missing, unreadable, or invalid."""


@dataclass(frozen=True)
class ReachabilityManifest:
    roots: tuple[str, ...]
    operational_directories: tuple[str, ...]
    excluded_directories: tuple[str, ...]
    standalone_documents: tuple[str, ...]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReachabilityError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _path_list(value: object, label: str, *, markdown: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ReachabilityError(f"{label} must be a string list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ReachabilityError(f"{label} must contain only nonempty strings")
    paths = tuple(value)
    if len(set(paths)) != len(paths):
        raise ReachabilityError(f"{label} must not contain duplicates")
    for value_path in paths:
        path = PurePosixPath(value_path)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value_path:
            raise ReachabilityError(f"{label} contains noncanonical path {value_path!r}")
        if markdown and path.suffix.lower() != ".md":
            raise ReachabilityError(f"{label} path must end in .md: {value_path!r}")
    return paths


def load_reachability_manifest(
    repo_root: Path,
    path: Optional[Path] = None,
) -> ReachabilityManifest:
    manifest_path = repo_root / MANIFEST_PATH if path is None else path
    try:
        raw = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ReachabilityError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReachabilityError(f"cannot read document reachability manifest: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != MANIFEST_FIELDS:
        raise ReachabilityError("reachability manifest fields differ from the contract")
    if raw.get("schema_version") != 1 or isinstance(raw.get("schema_version"), bool):
        raise ReachabilityError("reachability schema_version must be integer 1")
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ReachabilityError("reachability description must be a nonempty string")
    roots = _path_list(raw.get("roots"), "roots", markdown=True)
    if not roots:
        raise ReachabilityError("roots must not be empty")
    operational = _path_list(
        raw.get("operational_directories"),
        "operational_directories",
        markdown=False,
    )
    if not operational:
        raise ReachabilityError("operational_directories must not be empty")
    return ReachabilityManifest(
        roots=roots,
        operational_directories=operational,
        excluded_directories=_path_list(
            raw.get("excluded_directories"), "excluded_directories", markdown=False
        ),
        standalone_documents=_path_list(
            raw.get("standalone_documents"), "standalone_documents", markdown=True
        ),
    )


def _under(relative: str, directories: tuple[str, ...]) -> bool:
    path = PurePosixPath(relative)
    return any(path == PurePosixPath(directory) or PurePosixPath(directory) in path.parents
               for directory in directories)


def _linked_markdown_paths(repo_root: Path, source: Path) -> tuple[list[str], list[str]]:
    linked: list[str] = []
    problems: list[str] = []
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"cannot read routed document {source.relative_to(repo_root)}: {exc}"]
    for match in MARKDOWN_LINK_RE.finditer(text):
        raw = match.group(1).strip()
        target = raw.split()[0].strip("<>") if raw else ""
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        without_anchor = target.split("#", 1)[0]
        if not without_anchor:
            continue
        candidate = (source.parent / without_anchor).resolve()
        try:
            relative = candidate.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            problems.append(
                f"local Markdown target escapes repository: "
                f"{source.relative_to(repo_root).as_posix()} -> {target}"
            )
            continue
        if candidate.suffix.lower() != ".md":
            continue
        if not candidate.is_file():
            problems.append(
                f"missing local Markdown target: "
                f"{source.relative_to(repo_root).as_posix()} -> {target}"
            )
            continue
        linked.append(relative)
    return linked, problems


def document_reachability_problems(repo_root: Path) -> list[str]:
    try:
        manifest = load_reachability_manifest(repo_root)
    except ReachabilityError as exc:
        return [str(exc)]
    problems: list[str] = []
    seeds = manifest.roots + manifest.standalone_documents
    for relative in seeds:
        if not (repo_root / relative).is_file():
            problems.append(f"declared document is missing: {relative}")
    for directory in manifest.operational_directories:
        if not (repo_root / directory).is_dir():
            problems.append(f"operational directory is missing: {directory}")
    if problems:
        return sorted(problems)

    reachable: set[str] = set()
    queue = list(seeds)
    while queue:
        relative = queue.pop(0)
        if relative in reachable or _under(relative, manifest.excluded_directories):
            continue
        reachable.add(relative)
        linked, link_problems = _linked_markdown_paths(repo_root, repo_root / relative)
        problems.extend(link_problems)
        queue.extend(path for path in linked if path not in reachable)

    operational: set[str] = set()
    for directory in manifest.operational_directories:
        for path in (repo_root / directory).rglob("*.md"):
            relative = path.relative_to(repo_root).as_posix()
            if not _under(relative, manifest.excluded_directories):
                operational.add(relative)
    for relative in sorted(operational - reachable - set(manifest.standalone_documents)):
        problems.append(f"unreachable operational document: {relative}")
    return sorted(set(problems))


def main() -> int:
    problems = document_reachability_problems(Path.cwd().resolve())
    if problems:
        print("Document reachability failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("Operational Markdown documents are reachable from declared entry points.")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "ReachabilityError",
    "ReachabilityManifest",
    "document_reachability_problems",
    "load_reachability_manifest",
]
