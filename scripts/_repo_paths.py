#!/usr/bin/env python3
"""Strict repository-relative path validation shared by wiki tooling.

The resolver accepts only canonical POSIX strings. It validates the raw input
before ``Path`` can normalize away traversal, duplicate separators, or dot
components, then proves both repository and caller-supplied root containment.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Iterable, Literal


PathMode = Literal["existing_file", "may_create_file"]
EXISTING_FILE: PathMode = "existing_file"
MAY_CREATE_FILE: PathMode = "may_create_file"

URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
HTTP_URL_RE = re.compile(r"https?://[^\s\])}>\"']+", re.IGNORECASE)


class RepoPathError(ValueError):
    """A repository path failed lexical, scope, or filesystem validation."""


def is_http_url(value: object) -> bool:
    """True only when the whole string is one HTTP(S) URL token."""
    return isinstance(value, str) and HTTP_URL_RE.fullmatch(value) is not None


def _canonical_root(root: Path) -> Path:
    try:
        resolved = Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepoPathError(f"repository root is not readable: {root}") from exc
    if not resolved.is_dir():
        raise RepoPathError(f"repository root is not a directory: {root}")
    return resolved


def _validate_raw(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise RepoPathError("path must be a nonempty string")
    if "\x00" in value:
        raise RepoPathError("path must not contain NUL")
    if "\\" in value:
        raise RepoPathError("path must use POSIX separators")
    if URI_SCHEME_RE.match(value):
        raise RepoPathError("URI-like values are not repository paths")
    if value.startswith("/"):
        raise RepoPathError("path must be repository-relative")
    components = value.split("/")
    if any(component == "" for component in components):
        raise RepoPathError("path must not contain empty components")
    if any(component in {".", ".."} for component in components):
        raise RepoPathError("path must not contain '.' or '..' components")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix() != value:
        raise RepoPathError("path must be canonical POSIX repository-relative form")
    return value


def _validated_scopes(
    allowed_prefixes: Iterable[str], allowed_root_files: Iterable[str]
) -> tuple[tuple[str, ...], frozenset[str]]:
    prefixes: list[str] = []
    for prefix in allowed_prefixes:
        canonical = _validate_raw(prefix)
        if canonical in prefixes:
            raise RepoPathError(f"duplicate allowed prefix: {canonical}")
        prefixes.append(canonical)
    files = frozenset(_validate_raw(path) for path in allowed_root_files)
    return tuple(prefixes), files


def _lexical_scope(
    value: str, prefixes: tuple[str, ...], root_files: frozenset[str]
) -> str | None:
    if value in root_files:
        return None
    for prefix in prefixes:
        if value.startswith(prefix + "/"):
            return prefix
    raise RepoPathError(f"path is outside allowed repository roots: {value}")


def validate_repo_path_syntax(
    value: object,
    *,
    allowed_prefixes: Iterable[str] = (),
    allowed_root_files: Iterable[str] = (),
) -> str:
    """Validate canonical syntax and scope without reading the filesystem."""
    canonical = _validate_raw(value)
    prefixes, root_files = _validated_scopes(allowed_prefixes, allowed_root_files)
    _lexical_scope(canonical, prefixes, root_files)
    return canonical


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and not candidate.is_symlink():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepoPathError(f"nearest existing parent is not resolvable: {candidate}") from exc
    if not resolved.is_dir():
        raise RepoPathError(f"nearest existing parent is not a directory: {candidate}")
    return resolved


def resolve_repo_path(
    value: object,
    *,
    repo_root: Path,
    allowed_prefixes: Iterable[str] = (),
    allowed_root_files: Iterable[str] = (),
    mode: PathMode = EXISTING_FILE,
    require_regular_file: bool = True,
) -> str:
    """Return a canonical repo-relative file path or raise ``RepoPathError``.

    ``existing_file`` requires an existing target and, by default, a regular
    file. ``may_create_file`` accepts a missing target only after resolving its
    nearest existing parent. Create-mode directory targets are rejected.
    """

    if mode not in {EXISTING_FILE, MAY_CREATE_FILE}:
        raise RepoPathError(f"unsupported path existence mode: {mode!r}")
    prefix_values = tuple(allowed_prefixes)
    root_file_values = tuple(allowed_root_files)
    canonical = validate_repo_path_syntax(
        value,
        allowed_prefixes=prefix_values,
        allowed_root_files=root_file_values,
    )
    prefixes, root_files = _validated_scopes(prefix_values, root_file_values)
    matched_prefix = _lexical_scope(canonical, prefixes, root_files)
    root = _canonical_root(Path(repo_root))
    candidate = root.joinpath(*canonical.split("/"))

    # Exact root files are authority surfaces, not aliases. Letting one be a
    # symlink would allow an allowed name such as AGENTS.md to launder a file
    # from a disallowed tree such as raw/.
    if canonical in root_files and candidate.is_symlink():
        raise RepoPathError(f"allowed root file must not be a symlink: {canonical}")

    if mode == EXISTING_FILE:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RepoPathError(f"path is not an existing file: {canonical}") from exc
        if require_regular_file and not resolved.is_file():
            raise RepoPathError(f"path is not an existing regular file: {canonical}")
        containment_target = resolved
    else:
        if candidate.exists() or candidate.is_symlink():
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise RepoPathError(f"path target is not resolvable: {canonical}") from exc
            if resolved.is_dir():
                raise RepoPathError(f"path target is a directory: {canonical}")
            if require_regular_file and not resolved.is_file():
                raise RepoPathError(f"path target is not a regular file: {canonical}")
            containment_target = resolved
        else:
            containment_target = _nearest_existing_parent(candidate.parent)

    if not _is_within(containment_target, root):
        raise RepoPathError(f"path escapes repository root: {canonical}")

    if matched_prefix is not None:
        scope_path = root.joinpath(*matched_prefix.split("/"))
        cursor = root
        for component in matched_prefix.split("/"):
            cursor /= component
            if cursor.is_symlink():
                raise RepoPathError(f"allowed root must not be a symlink: {matched_prefix}")
            if cursor.exists() and not cursor.is_dir():
                raise RepoPathError(f"allowed root is not a directory: {matched_prefix}")
            if not cursor.exists():
                break
        # When the configured root already exists, require the resolved target
        # (or create parent) to remain under its real path. This blocks both
        # external escapes and cross-root symlink laundering.
        if scope_path.exists() or scope_path.is_symlink():
            try:
                scope_anchor = scope_path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise RepoPathError(f"allowed root is not resolvable: {matched_prefix}") from exc
            if not scope_anchor.is_dir():
                raise RepoPathError(f"allowed root is not a directory: {matched_prefix}")
            if not _is_within(containment_target, scope_anchor):
                raise RepoPathError(
                    f"path escapes allowed repository root {matched_prefix}: {canonical}"
                )

    return canonical
