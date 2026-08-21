#!/usr/bin/env python3
"""Stable vocabulary and parsed page context shared by wiki lint layers."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from datetime import date
from pathlib import Path

from _wiki_parse import FrontmatterError, META_PAGES, frontmatter_block, split_frontmatter
from wiki_entity_catalog import load_entity_catalog


LintFailure = tuple[str, str, str]
LintFailures = list[LintFailure]

WIKI_ROOT = Path("wiki")
ADJUDICATIONS_PATH = Path("scripts/lint-adjudications.json")
LOG_ROTATION_WARN_LINES = 2500
# Date-only log entries before this cutoff predate the structured stale-text
# sweep proof template. Do not rewrite old history just to satisfy this check.
STALE_SWEEP_PROOF_REQUIRED_FROM = date(2026, 7, 5)

# META_PAGES is shared with rebuild_referenced_by.py via _wiki_parse, so the
# corpus enumeration cannot drift between linter and rebuild.

ENTITY_CATALOG = load_entity_catalog()
# Stable compatibility mapping derived from the governed catalog. Callers do
# not read entity-catalog.json directly.
FOLDER_TYPE = ENTITY_CATALOG.folder_types
ROOT_ALLOWED_FILES = {
    ".gitignore", "AGENTS.md", "CLAUDE.md", "CONTEXT.md", "LICENSE",
    "README.md", "REFERENCES.md",
# wiki-setup:lint-contract-setup-root:start
    "SETUP.md",
# wiki-setup:lint-contract-setup-root:end
}
ROOT_ALLOWED_DIRS = {
    ".agents", ".claude", ".codex", ".github", ".git", ".wiki-transactions", "archive", "deliverables", "raw",
    "scripts", "tmp", "wiki", "workflows",
}
WIKI_ALLOWED_FILES = {f"{name}.md" for name in META_PAGES}
WIKI_ALLOWED_DIRS = set(FOLDER_TYPE)
RAW_ALLOWED_FILES = {".gitkeep", "README.md"}
VALID_CONFIDENCE = {"high", "medium", "low", "contested"}
VALID_SOURCE_TYPE = {
    "help-doc", "slack-thread", "call-transcript", "exec-memo", "deck",
    "crm-export", "strategy-doc", "release-note", "press", "analyst-report",
    "competitor-collateral", "sales-battlecard", "product-spec", "board-doc",
    "synthesis", "other",
}
VALID_AUTHORITY_KIND = {
    "raw-source", "source-page", "owner-page", "external-url",
    "local-resource", "mixed", "none",
}
VALID_AUTHORITY_FRESHNESS = {
    "immutable-source", "stable-meaning", "current-state", "event-log",
    "predictive", "deprecated",
}
AUTHORITY_ANCHOR_FIELDS = (
    "authority_ref", "authority_freshness", "verify_before_action",
    "last_verified",
)
AUTHORITY_METADATA_FIELDS = ("authority_kind",) + AUTHORITY_ANCHOR_FIELDS
BASE_KEYS = {"title", "type", "created", "updated", "sources", "tags", "confidence"}
RELATED_LABELS = {"Supports", "Contradicts", "Depends on", "Derived from", "Part of", "Related"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUS_RE = re.compile(r"\*\*Status(?: note)?\s*\((\d{4}-\d{2}-\d{2})\)")
# Volatile status language in glossary entries. Glossary definitions are
# durable by design; live status belongs on owner pages. File-level updated:
# dates are too coarse to catch a single glossary entry that silently rots.
VOLATILE_STATUS_RE = re.compile(
    r"\b(still (?:missing|open|pending|owed|outstanding)|remains? open"
    r"|not yet|tentative(?:ly)?|awaiting|in progress|up in the air"
    r"|yet to be|to be determined|unresolved|pending)\b",
    re.IGNORECASE,
)
GLOSSARY_BULLET_ENTRY_RE = re.compile(r"^-\s+\*\*(?P<term>[^*]+)\*\*\s+[-:]\s+(?P<body>.*)$")
SOURCING_QUEUE_COUNT_MARKER_RE = re.compile(r"<!--\s*lint:entity-count\b(?P<attrs>.*?)-->")
SOURCING_QUEUE_COUNT_MARKER_INTENT_RE = re.compile(
    r"<!--(?=[^>]*\blint\s*:\s*entity-counts?\b)[\s\S]*?-->"
)
SOURCING_QUEUE_COUNT_ATTR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)=([^\s]+)")
RAW_REPO_TOKEN_RE = re.compile(
    r"(?<![-A-Za-z0-9_./:\x00\x5c])raw/[^\s,\]\"')]+"
)
WIKI_REPO_TOKEN_RE = re.compile(
    r"(?<![-A-Za-z0-9_./:\x00\x5c])"
    r"wiki/[^\s,\])]+?\.md(?=$|[\s,\])}>\"'|]|[.;:](?=$|\s))"
)
# Entity classes required to enroll in the review_by outcome-review loop. The
# template makes decisions mandatory because they carry choices that should be
# revisited; analyses stay opt-in because many are reusable models rather than
# dated predictions.
REVIEW_BY_REQUIRED_FOLDERS = ENTITY_CATALOG.review_date_expected_folders
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "into", "your", "you",
    "are", "for", "not", "but", "what", "when", "where", "which", "they",
    "them", "then", "than", "have", "has", "had", "was", "were", "will",
    "would", "can", "could", "should", "its", "it's", "their", "these",
    "those", "there", "here", "page", "pages", "wiki", "type", "tags",
}


class PageContext:
    """Everything a Tier-1 per-page check needs about one entity page.

    Built once per page in the run_tier1_lint() loop and passed to each registered check,
    so the checks share parsing work (read, split_frontmatter, frontmatter_block)
    instead of each re-deriving it."""

    __slots__ = ("path", "rel", "stem", "folder", "text", "fm", "fm_block",
                 "frontmatter_error",
                 "valid_slugs", "source_slugs")

    path: Path
    rel: str
    stem: str
    folder: str | None
    text: str
    fm: dict[str, str] | None
    fm_block: str
    frontmatter_error: str | None
    valid_slugs: Collection[str]
    source_slugs: Collection[str]

    def __init__(
        self,
        path: Path,
        text: str,
        valid_slugs: Collection[str],
        source_slugs: Collection[str],
    ) -> None:
        self.path = path
        self.rel = str(path.relative_to(WIKI_ROOT))
        self.stem = path.stem
        self.folder = path.parent.name if path.parent != WIKI_ROOT else None
        self.text = text
        self.frontmatter_error = None
        try:
            self.fm, _ = split_frontmatter(text)
            self.fm_block = frontmatter_block(text)
        except FrontmatterError as exc:
            self.fm = None
            self.fm_block = ""
            self.frontmatter_error = str(exc)
        self.valid_slugs = valid_slugs
        self.source_slugs = source_slugs


Tier1Check = Callable[[PageContext], LintFailures]



__all__ = [
    "ADJUDICATIONS_PATH",
    "AUTHORITY_ANCHOR_FIELDS",
    "AUTHORITY_METADATA_FIELDS",
    "BASE_KEYS",
    "DATE_PREFIX_RE",
    "DATE_RE",
    "ENTITY_CATALOG",
    "FOLDER_TYPE",
    "GLOSSARY_BULLET_ENTRY_RE",
    "KEBAB_RE",
    "LintFailure",
    "LintFailures",
    "LOG_ROTATION_WARN_LINES",
    "PageContext",
    "RAW_ALLOWED_FILES",
    "RAW_REPO_TOKEN_RE",
    "RELATED_LABELS",
    "REVIEW_BY_REQUIRED_FOLDERS",
    "ROOT_ALLOWED_DIRS",
    "ROOT_ALLOWED_FILES",
    "SOURCING_QUEUE_COUNT_ATTR_RE",
    "SOURCING_QUEUE_COUNT_MARKER_INTENT_RE",
    "SOURCING_QUEUE_COUNT_MARKER_RE",
    "STALE_SWEEP_PROOF_REQUIRED_FROM",
    "STATUS_RE",
    "STOPWORDS",
    "Tier1Check",
    "VALID_AUTHORITY_FRESHNESS",
    "VALID_AUTHORITY_KIND",
    "VALID_CONFIDENCE",
    "VALID_SOURCE_TYPE",
    "VOLATILE_STATUS_RE",
    "WIKI_ALLOWED_DIRS",
    "WIKI_ALLOWED_FILES",
    "WIKI_REPO_TOKEN_RE",
    "WIKI_ROOT",
]
