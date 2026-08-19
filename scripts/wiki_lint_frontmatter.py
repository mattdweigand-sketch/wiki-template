#!/usr/bin/env python3
"""Frontmatter and repository-reference parsing for wiki lint."""

from __future__ import annotations

import re
from pathlib import Path

from _repo_paths import HTTP_URL_RE, EXISTING_FILE, RepoPathError, is_http_url, resolve_repo_path
from _wiki_parse import FrontmatterError, LINK_RE, frontmatter_block, split_frontmatter, split_quoted_csv, strip_body_sections
from wiki_lint_contract import RAW_REPO_TOKEN_RE, STOPWORDS, WIKI_REPO_TOKEN_RE


RepositoryReference = tuple[str, str]
RepositoryReferenceResult = tuple[list[RepositoryReference], list[str]]


def block_list_has_items(fm_text: str, key: str) -> bool:
    """True if a YAML key carries a real value: an inline scalar/list, or at
    least one indented '- item' before the next top-level key. split_frontmatter
    flattens block lists to '', so the required-keys check alone cannot tell a
    populated agent_use_cases from a bare 'agent_use_cases:' header."""
    lines = fm_text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(rf"^{re.escape(key)}:\s*(.*)$", line)
        if not m:
            continue
        inline = m.group(1).strip()
        if inline and inline != "[]":
            return True
        for nxt in lines[i + 1:]:
            if re.match(r"^\s+-\s+\S", nxt):
                return True
            if re.match(r"^\S", nxt):  # next top-level key
                break
        return False
    return False


def authored_body(body: str) -> str:
    """Body with generated and curated link sections removed."""
    return strip_body_sections(body, "Referenced by", "Related pages")


def nonblocking_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    """Tier-2 parse view; Tier 1 reports malformed leading frontmatter."""
    try:
        return split_frontmatter(text)
    except FrontmatterError:
        return None, ""


def nonblocking_frontmatter_block(text: str) -> str:
    """Raw Tier-2 frontmatter view without duplicating a malformed error."""
    try:
        return frontmatter_block(text)
    except FrontmatterError:
        return ""


def tokens(text: str) -> set[str]:
    text = LINK_RE.sub(" ", text)
    text = re.sub(r"[`*#|>_\-\[\]()]", " ", text)
    out = set()
    for w in re.findall(r"[a-z][a-z0-9']+", text.lower()):
        if len(w) >= 4 and w not in STOPWORDS:
            out.add(w)
    return out


# Tokens in a sources: value that are not provenance slugs to existence-check:
# raw/ paths are checked separately, and free-text provenance (experience,
# web research, deliverable, an explicit URL) is prose, not a page reference.
# The prefix word must be followed by a colon or space so a kebab slug that
# merely STARTS with one of these words (e.g. web-agents-2026) stays checked.
SOURCE_NONSLUG_PREFIX_RE = re.compile(r"^(experience|web|deliverable|source)[:\s]", re.I)


def source_items(fm_block: str) -> list[str]:
    """Split each sources: line in a frontmatter block into its list items.
    Inline values use the shared split_quoted_csv grammar; block-style lists
    (indented '- item' lines under a bare sources: key) are walked the same
    way block_list_has_items walks agent_use_cases, so block-sourced pages get
    the same provenance checks as inline-sourced ones."""
    items = []
    lines = fm_block.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*sources?:\s*(.*)$", line)
        if not m:
            continue
        inline = m.group(1).strip()
        if inline:
            items.extend(split_quoted_csv(inline))
            continue
        for nxt in lines[i + 1:]:
            im = re.match(r"^\s+-\s+(.*)$", nxt)
            if im:
                item = im.group(1).strip().strip("\"'").strip()
                if item:
                    items.append(item)
            elif re.match(r"^\S", nxt):  # next top-level key
                break
    return items


def _mask_http_urls(text):
    chars = list(text)
    for match in HTTP_URL_RE.finditer(text):
        for index in range(*match.span()):
            chars[index] = "\x00"
    return "".join(chars)


def _unsafe_source_path_expressions(item, safe_spans):
    """Path-shaped raw/wiki expressions not accepted by the canonical regexes."""
    scan = _mask_http_urls(item)
    out = []
    for match in re.finditer(r"(?:raw|wiki)[\\/]", scan, re.IGNORECASE):
        if any(start <= match.start() < end for start, end in safe_spans):
            continue
        start = match.start()
        while start > 0 and not scan[start - 1].isspace() and scan[start - 1] not in ",])}|":
            start -= 1
        end = match.end()
        while end < len(scan) and not scan[end].isspace() and scan[end] not in ",])}|":
            end += 1
        expression = item[start:end].strip("([{<\"'")
        entry = (match.group(0)[0:3].lower() if match.group(0).lower().startswith("raw") else "wiki",
                 expression)
        if expression and entry not in out:
            out.append(entry)
    return out


def source_repo_references(
    item: str,
    *,
    repo_root: Path | str | None = None,
) -> RepositoryReferenceResult:
    """Resolve canonical raw/wiki refs in one sources: item.

    Returns ``(references, errors)`` where references are ``(kind, path)``
    tuples. The same classifier feeds Tier 1 existence checks and Tier 2 quote
    haystacks, so a path rejected by the guard can never be read as evidence.
    """
    root = Path.cwd() if repo_root is None else Path(repo_root)
    if SOURCE_NONSLUG_PREFIX_RE.match(item) or is_http_url(item):
        return [], []

    raw_matches = list(RAW_REPO_TOKEN_RE.finditer(item))
    wiki_matches = list(WIKI_REPO_TOKEN_RE.finditer(item))
    safe_spans = [match.span() for match in (*raw_matches, *wiki_matches)]
    errors = [
        f"unsafe {family} repository path expression: {expression!r}"
        for family, expression in _unsafe_source_path_expressions(item, safe_spans)
    ]
    if not raw_matches and not wiki_matches and not errors and (
        "/" in item
        or "\\" in item
        or item.startswith((".", "~"))
        or (not any(char.isspace() for char in item) and Path(item).suffix)
    ):
        errors.append(f"unsafe provenance path expression: {item!r}")
    references = []
    for match in raw_matches:
        raw_ref = match.group(0).rstrip(".,:")
        canonical_input = raw_ref[:-1] if raw_ref.endswith("/") else raw_ref
        try:
            canonical = resolve_repo_path(
                canonical_input,
                repo_root=root,
                allowed_prefixes=("raw",),
                mode=EXISTING_FILE,
                require_regular_file=False,
            )
        except RepoPathError:
            errors.append(f"'{raw_ref}' does not exist or is unsafe")
        else:
            references.append(("raw", canonical))
    for match in wiki_matches:
        wiki_ref = match.group(0)
        try:
            canonical = resolve_repo_path(
                wiki_ref,
                repo_root=root,
                allowed_prefixes=("wiki",),
                mode=EXISTING_FILE,
            )
        except RepoPathError:
            errors.append(f"'{wiki_ref}' does not exist or is unsafe")
        else:
            references.append(("wiki", canonical))
    return references, errors


def fm_scalar(value: str | None) -> str:
    """Normalize one scalar frontmatter value for deterministic lint checks."""
    if value is None:
        return ""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value



__all__ = [
    "authored_body",
    "block_list_has_items",
    "fm_scalar",
    "nonblocking_frontmatter",
    "nonblocking_frontmatter_block",
    "source_items",
    "source_repo_references",
    "tokens",
]
