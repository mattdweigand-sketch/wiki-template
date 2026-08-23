#!/usr/bin/env python3
"""Validate immutable raw artifacts across live, staged, and CI Git views."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

from _repo_paths import RepoPathError, validate_repo_path_syntax
from _wiki_parse import FrontmatterError, frontmatter_block, split_frontmatter
from wiki_lint_contract import RAW_REPO_TOKEN_RE
from wiki_lint_frontmatter import source_items


MANIFEST_PATH = "scripts/raw-artifacts.json"
RAW_BUCKETS_PATH = "scripts/raw-buckets.json"
MANIFEST_FIELDS = {"artifacts", "schema_version"}
ARTIFACT_FIELDS = {"captured_at", "files", "source_slug"}
FILE_FIELDS = {"path", "sha256", "size"}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TRACKED_RAW_EXCEPTIONS = frozenset({"raw/.gitkeep", "raw/README.md"})


class _DuplicateJsonKey(ValueError):
    pass


@dataclass(frozen=True)
class _RepositoryView:
    files: Mapping[str, bytes]
    modes: Mapping[str, str]
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class RawClosureFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class RawSourceClosure:
    source_slug: str
    source_path: str
    source_sha256: str
    files: tuple[RawClosureFile, ...]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey(key)
        value[key] = item
    return value


def _strict_json(content: bytes, label: str) -> tuple[Optional[object], list[str]]:
    try:
        text = content.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateJsonKey as exc:
        return None, [f"{label}: duplicate JSON key {exc.args[0]!r}"]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"{label}: invalid JSON: {exc}"]
    return value, []


def _git(repo_root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *arguments], cwd=repo_root,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )


def _relevant_path(path: str) -> bool:
    return (
        path in {MANIFEST_PATH, RAW_BUCKETS_PATH}
        or path.startswith("wiki/sources/")
        or path.casefold().startswith("raw/")
    )


def _read_blob(repo_root: Path, object_id: str) -> bytes:
    result = _git(repo_root, ("cat-file", "blob", object_id))
    if result.returncode != 0:
        raise ValueError(f"Git blob {object_id} is unreadable")
    return result.stdout


def _revision_view(repo_root: Path, revision: str) -> _RepositoryView:
    resolved = _git(repo_root, ("rev-parse", "--verify", f"{revision}^{{commit}}"))
    if resolved.returncode != 0:
        raise ValueError(f"Git revision {revision!r} is unavailable")
    tree = _git(repo_root, ("ls-tree", "-r", "-z", "--full-tree", revision))
    if tree.returncode != 0:
        raise ValueError(f"Git tree {revision!r} is unreadable")
    files: dict[str, bytes] = {}
    modes: dict[str, str] = {}
    issues: list[str] = []
    for raw_entry in tree.stdout.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split(" ", 2)
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            issues.append("Git tree contains a non-UTF-8 path")
            continue
        if not _relevant_path(path):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            issues.append(f"{path}: not a regular Git file")
            continue
        files[path] = _read_blob(repo_root, object_id)
        modes[path] = mode
    return _RepositoryView(files, modes, tuple(issues))


def _index_view(repo_root: Path) -> _RepositoryView:
    index = _git(repo_root, ("ls-files", "--stage", "-z"))
    if index.returncode != 0:
        raise ValueError("Git index is unreadable")
    files: dict[str, bytes] = {}
    modes: dict[str, str] = {}
    issues: list[str] = []
    for raw_entry in index.stdout.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        mode, object_id, stage = metadata.decode("ascii").split(" ", 2)
        try:
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            issues.append("Git index contains a non-UTF-8 path")
            continue
        if not _relevant_path(path):
            continue
        if stage != "0" or mode not in {"100644", "100755"}:
            issues.append(f"{path}: not a regular stage-zero Git file")
            continue
        files[path] = _read_blob(repo_root, object_id)
        modes[path] = mode
    return _RepositoryView(files, modes, tuple(issues))


def _live_view(repo_root: Path) -> _RepositoryView:
    files: dict[str, bytes] = {}
    modes: dict[str, str] = {}
    issues: list[str] = []
    candidates = [repo_root / MANIFEST_PATH, repo_root / RAW_BUCKETS_PATH]
    source_root = repo_root / "wiki/sources"
    if source_root.is_dir() and not source_root.is_symlink():
        candidates.extend(sorted(source_root.glob("*.md")))
    raw_root = repo_root / "raw"
    if raw_root.is_dir() and not raw_root.is_symlink():
        for directory, folder_names, file_names in os.walk(raw_root, followlinks=False):
            folder_names.sort()
            file_names.sort()
            for folder_name in list(folder_names):
                folder = Path(directory) / folder_name
                if folder.is_symlink():
                    issues.append(f"{folder.relative_to(repo_root).as_posix()}: symlink is unsafe")
                    folder_names.remove(folder_name)
            candidates.extend(Path(directory) / name for name in file_names)
    for candidate in candidates:
        relative = candidate.relative_to(repo_root).as_posix()
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            issues.append(f"{relative}: must be a regular file with one link")
            continue
        try:
            files[relative] = candidate.read_bytes()
        except OSError as exc:
            issues.append(f"{relative}: unreadable: {exc}")
            continue
        modes[relative] = "100755" if metadata.st_mode & stat.S_IXUSR else "100644"
    return _RepositoryView(files, modes, tuple(issues))


def _selected_raw_buckets(view: _RepositoryView) -> tuple[set[str], list[str]]:
    content = view.files.get(RAW_BUCKETS_PATH)
    if content is None:
        return set(), [f"{RAW_BUCKETS_PATH}: missing"]
    value, issues = _strict_json(content, RAW_BUCKETS_PATH)
    if issues:
        return set(), issues
    if not isinstance(value, dict) or not isinstance(value.get("buckets"), dict):
        return set(), [f"{RAW_BUCKETS_PATH}: missing buckets object"]
    buckets = value["buckets"]
    if not all(isinstance(key, str) for key in buckets):
        return set(), [f"{RAW_BUCKETS_PATH}: bucket names must be strings"]
    return set(buckets), []


def _safe_raw_path(path: str, buckets: set[str]) -> bool:
    try:
        canonical = validate_repo_path_syntax(path, allowed_prefixes=("raw",))
    except RepoPathError:
        return False
    pure = PurePosixPath(canonical)
    return len(pure.parts) >= 3 and pure.parts[1] in buckets


def _parse_manifest(
    view: _RepositoryView, *, allow_missing: bool,
) -> tuple[list[dict[str, object]], list[str]]:
    content = view.files.get(MANIFEST_PATH)
    if content is None:
        if allow_missing:
            return [], []
        return [], [f"{MANIFEST_PATH}: missing"]
    value, issues = _strict_json(content, MANIFEST_PATH)
    if issues:
        return [], issues
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8") + b"\n"
    if content != canonical:
        issues.append(f"{MANIFEST_PATH}: JSON is not canonical")
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        return [], issues + [f"{MANIFEST_PATH}: fields must be artifacts and schema_version"]
    if value.get("schema_version") != 1 or isinstance(value.get("schema_version"), bool):
        issues.append(f"{MANIFEST_PATH}: schema_version must be integer 1")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list):
        return [], issues + [f"{MANIFEST_PATH}: artifacts must be a list"]
    return artifacts, issues


def _source_raw_paths(content: bytes, source_path: str) -> tuple[set[str], list[str]]:
    try:
        text = content.decode("utf-8")
        fields, _body = split_frontmatter(text)
        block = frontmatter_block(text)
    except (UnicodeDecodeError, FrontmatterError) as exc:
        return set(), [f"{source_path}: invalid frontmatter: {exc}"]
    if fields is None or fields.get("type", "").strip("\"'") != "source":
        return set(), [f"{source_path}: type must be source"]
    paths: set[str] = set()
    issues: list[str] = []
    for item in source_items(block):
        matches = [match.group(0).rstrip(".,:") for match in RAW_REPO_TOKEN_RE.finditer(item)]
        if "raw/" in item and not matches:
            issues.append(f"{source_path}: unsafe raw path in sources")
        paths.update(matches)
    return paths, issues


def _validate_view(
    view: _RepositoryView,
    *,
    allow_missing_manifest: bool,
    require_raw_bytes: bool,
) -> tuple[list[dict[str, object]], tuple[str, ...]]:
    issues = list(view.issues)
    buckets, bucket_issues = _selected_raw_buckets(view)
    issues.extend(bucket_issues)
    artifacts, manifest_issues = _parse_manifest(view, allow_missing=allow_missing_manifest)
    issues.extend(manifest_issues)
    source_slugs: set[str] = set()
    raw_paths: set[str] = set()
    previous_slug = ""
    parsed: list[dict[str, object]] = []
    for index, artifact in enumerate(artifacts):
        label = f"artifacts[{index}]"
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_FIELDS:
            issues.append(f"{label}: fields differ from the manifest contract")
            continue
        source_slug = artifact.get("source_slug")
        captured_at = artifact.get("captured_at")
        members = artifact.get("files")
        if not isinstance(source_slug, str) or not SLUG_RE.fullmatch(source_slug):
            issues.append(f"{label}.source_slug: must be kebab-case")
            continue
        if source_slug in source_slugs:
            issues.append(f"{label}.source_slug: duplicate {source_slug}")
        if previous_slug and source_slug <= previous_slug:
            issues.append(f"{label}: artifacts are not sorted by source_slug")
        previous_slug = source_slug
        source_slugs.add(source_slug)
        try:
            if not isinstance(captured_at, str) or date.fromisoformat(captured_at).isoformat() != captured_at:
                raise ValueError
        except ValueError:
            issues.append(f"{label}.captured_at: must be YYYY-MM-DD")
        if not isinstance(members, list) or not members:
            issues.append(f"{label}.files: must be a nonempty list")
            continue
        member_paths: list[str] = []
        for member_index, member in enumerate(members):
            member_label = f"{label}.files[{member_index}]"
            if not isinstance(member, dict) or set(member) != FILE_FIELDS:
                issues.append(f"{member_label}: fields differ from the file contract")
                continue
            path = member.get("path")
            size = member.get("size")
            digest = member.get("sha256")
            if not isinstance(path, str) or not _safe_raw_path(path, buckets):
                issues.append(f"{member_label}.path: unsafe or outside a selected raw bucket")
                continue
            if path in raw_paths:
                issues.append(f"{member_label}.path: duplicate {path}")
            raw_paths.add(path)
            member_paths.append(path)
            content = view.files.get(path)
            if require_raw_bytes and content is None:
                issues.append(f"{path}: missing")
                continue
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                issues.append(f"{member_label}.size: must be a nonnegative integer")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                issues.append(f"{member_label}.sha256: must be lowercase SHA-256")
            if require_raw_bytes and content is not None:
                if view.modes.get(path) not in {"100644", "100755"}:
                    issues.append(f"{path}: not a regular file")
                if isinstance(size, int) and not isinstance(size, bool) and size != len(content):
                    issues.append(f"{member_label}.size: does not match {path}")
                actual_digest = hashlib.sha256(content).hexdigest()
                if isinstance(digest, str) and SHA256_RE.fullmatch(digest) and digest != actual_digest:
                    issues.append(f"{member_label}.sha256: does not match {path}")
        if member_paths != sorted(member_paths):
            issues.append(f"{label}.files: paths are not sorted")
        source_path = f"wiki/sources/{source_slug}.md"
        source_content = view.files.get(source_path)
        if source_content is None:
            issues.append(f"{source_path}: missing")
        else:
            source_paths, source_issues = _source_raw_paths(source_content, source_path)
            issues.extend(source_issues)
            if source_paths != set(member_paths):
                issues.append(f"{source_path}: raw sources do not equal manifest files")
        parsed.append(artifact)
    present_raw = {
        path for path in view.files
        if path.startswith("raw/") and not path.endswith("/.gitkeep") and path != "raw/README.md"
    }
    if require_raw_bytes and not allow_missing_manifest:
        for path in sorted(present_raw - raw_paths):
            issues.append(f"{path}: raw file is absent from {MANIFEST_PATH}")
    return parsed, tuple(dict.fromkeys(issues))


def _tracked_raw_issues(view: _RepositoryView) -> tuple[str, ...]:
    return tuple(
        f"{path}: raw source artifacts must not be tracked by Git"
        for path in sorted(view.files)
        if path.casefold().startswith("raw/") and path not in TRACKED_RAW_EXCEPTIONS
    )


def _accepted_identity_issues(
    baseline_artifacts: list[dict[str, object]],
    proposed_artifacts: list[dict[str, object]],
) -> tuple[str, ...]:
    proposed = {
        artifact["source_slug"]: artifact
        for artifact in proposed_artifacts
        if isinstance(artifact, dict) and isinstance(artifact.get("source_slug"), str)
    }
    issues: list[str] = []
    for accepted in baseline_artifacts:
        if not isinstance(accepted, dict) or not isinstance(accepted.get("source_slug"), str):
            continue
        slug = accepted["source_slug"]
        if slug not in proposed:
            issues.append(f"{slug}: accepted raw artifact was deleted")
        elif proposed[slug] != accepted:
            issues.append(f"{slug}: accepted raw artifact was changed or rebound")
    return tuple(issues)


def _validate_against_baseline(
    proposed: _RepositoryView,
    baseline: _RepositoryView,
    *,
    proposed_has_raw_bytes: bool,
    baseline_has_raw_bytes: bool,
    proposed_is_git_view: bool,
    baseline_is_git_view: bool,
) -> tuple[str, ...]:
    proposed_artifacts, proposed_issues = _validate_view(
        proposed,
        allow_missing_manifest=False,
        require_raw_bytes=proposed_has_raw_bytes,
    )
    baseline_artifacts, baseline_issues = _validate_view(
        baseline,
        allow_missing_manifest=True,
        require_raw_bytes=baseline_has_raw_bytes,
    )
    tracking_issues = (
        *(_tracked_raw_issues(proposed) if proposed_is_git_view else ()),
        *(_tracked_raw_issues(baseline) if baseline_is_git_view else ()),
    )
    return tuple(dict.fromkeys(
        (*proposed_issues, *baseline_issues, *tracking_issues,
         *_accepted_identity_issues(baseline_artifacts, proposed_artifacts))
    ))


def validate_live_provenance(repo_root: Path) -> tuple[str, ...]:
    """Validate live raw identities against the exact current HEAD."""
    root = repo_root.resolve()
    try:
        return _validate_against_baseline(
            _live_view(root),
            _revision_view(root, "HEAD"),
            proposed_has_raw_bytes=True,
            baseline_has_raw_bytes=False,
            proposed_is_git_view=False,
            baseline_is_git_view=True,
        )
    except (OSError, ValueError) as exc:
        return (f"provenance validation failed: {exc}",)


def validate_restored_provenance(repo_root: Path) -> tuple[str, ...]:
    """Validate one restored tree's complete raw/source closure without Git history."""
    try:
        _artifacts, issues = _validate_view(
            _live_view(repo_root.resolve()),
            allow_missing_manifest=False,
            require_raw_bytes=True,
        )
        return issues
    except (OSError, ValueError) as exc:
        return (f"restored provenance validation failed: {exc}",)


def validate_staged_provenance(repo_root: Path) -> tuple[str, ...]:
    """Validate index-only raw identities against the exact current HEAD."""
    root = repo_root.resolve()
    try:
        proposed = _index_view(root)
        try:
            baseline = _revision_view(root, "HEAD")
        except ValueError:
            baseline = _RepositoryView(
                {RAW_BUCKETS_PATH: proposed.files.get(RAW_BUCKETS_PATH, b"")},
                {RAW_BUCKETS_PATH: "100644"},
            )
        return _validate_against_baseline(
            proposed,
            baseline,
            proposed_has_raw_bytes=False,
            baseline_has_raw_bytes=False,
            proposed_is_git_view=True,
            baseline_is_git_view=True,
        )
    except (OSError, ValueError) as exc:
        return (f"provenance validation failed: {exc}",)


def validate_ci_provenance(repo_root: Path, trusted_base: str) -> tuple[str, ...]:
    """Validate HEAD against one explicit trusted base without replaying history."""
    root = repo_root.resolve()
    ancestry = _git(root, ("merge-base", "--is-ancestor", trusted_base, "HEAD"))
    if ancestry.returncode != 0:
        return (f"trusted base {trusted_base!r} is not an ancestor of HEAD",)
    try:
        return _validate_against_baseline(
            _revision_view(root, "HEAD"),
            _revision_view(root, trusted_base),
            proposed_has_raw_bytes=False,
            baseline_has_raw_bytes=False,
            proposed_is_git_view=True,
            baseline_is_git_view=True,
        )
    except (OSError, ValueError) as exc:
        return (f"provenance validation failed: {exc}",)


def _resolve_source_closure(
    repo_root: Path,
    source_slug: str,
    provenance_issues: tuple[str, ...],
) -> RawSourceClosure:
    if not SLUG_RE.fullmatch(source_slug):
        raise ValueError(f"invalid source slug {source_slug!r}")
    if provenance_issues:
        raise ValueError("; ".join(provenance_issues))
    view = _live_view(repo_root.resolve())
    artifacts, manifest_issues = _parse_manifest(view, allow_missing=False)
    if manifest_issues:
        raise ValueError("; ".join(manifest_issues))
    artifact = next(
        (
            item for item in artifacts
            if isinstance(item, dict) and item.get("source_slug") == source_slug
        ),
        None,
    )
    if artifact is None:
        raise ValueError(f"source slug {source_slug!r} has no raw artifact record")
    source_path = f"wiki/sources/{source_slug}.md"
    source_content = view.files.get(source_path)
    if source_content is None:
        raise ValueError(f"source page {source_path!r} is missing")
    members = artifact.get("files")
    if not isinstance(members, list):
        raise ValueError(f"source slug {source_slug!r} has invalid files")
    return RawSourceClosure(
        source_slug=source_slug,
        source_path=source_path,
        source_sha256=hashlib.sha256(source_content).hexdigest(),
        files=tuple(
            RawClosureFile(
                path=member["path"], size=member["size"], sha256=member["sha256"]
            )
            for member in members
            if isinstance(member, dict)
            and isinstance(member.get("path"), str)
            and isinstance(member.get("size"), int)
            and isinstance(member.get("sha256"), str)
        ),
    )


def resolve_live_source_closure(repo_root: Path, source_slug: str) -> RawSourceClosure:
    """Resolve a live source closure after checking local bytes and Git metadata."""
    return _resolve_source_closure(
        repo_root, source_slug, validate_live_provenance(repo_root)
    )


def resolve_restored_source_closure(repo_root: Path, source_slug: str) -> RawSourceClosure:
    """Resolve a restored source closure after offline consistency validation."""
    return _resolve_source_closure(
        repo_root, source_slug, validate_restored_provenance(repo_root)
    )


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser(description="Validate raw artifact provenance.")
    command_parser.add_argument("view", choices=("live", "staged", "ci"))
    command_parser.add_argument("--trusted-base")
    return command_parser


def main() -> int:
    args = parser().parse_args()
    if args.view == "live":
        issues = validate_live_provenance(Path.cwd())
    elif args.view == "staged":
        issues = validate_staged_provenance(Path.cwd())
    elif not args.trusted_base:
        parser().error("ci view requires --trusted-base")
    else:
        issues = validate_ci_provenance(Path.cwd(), args.trusted_base)
    for issue in issues:
        print(f"provenance: {issue}", file=sys.stderr)
    return 1 if issues else 0


__all__ = [
    "MANIFEST_PATH",
    "TRACKED_RAW_EXCEPTIONS",
    "RawClosureFile",
    "RawSourceClosure",
    "resolve_live_source_closure",
    "resolve_restored_source_closure",
    "validate_ci_provenance",
    "validate_live_provenance",
    "validate_restored_provenance",
    "validate_staged_provenance",
]


if __name__ == "__main__":
    raise SystemExit(main())
