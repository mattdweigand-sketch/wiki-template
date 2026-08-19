#!/usr/bin/env python3
"""Stable vocabulary and parsed page context shared by wiki lint layers."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Collection

from _wiki_parse import FrontmatterError, META_PAGES, frontmatter_block, split_frontmatter


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

# folder name -> expected frontmatter type value
FOLDER_TYPE = {
    "sources": "source",
    "products": "product",
    "features": "feature",
    "personas": "persona",
    "customers": "customer",
    "competitors": "competitor",
    "concepts": "concept",
    "initiatives": "initiative",
    "decisions": "decision",
    "metrics": "metric",
    "people": "person",
    "analyses": "analysis",
}
ROOT_ALLOWED_FILES = {
    ".gitignore", "AGENTS.md", "CLAUDE.md", "CONTEXT.md", "LICENSE",
    "README.md", "REFERENCES.md", "SETUP.md",
}
ROOT_ALLOWED_DIRS = {
    ".claude", ".codex", ".github", ".git", ".wiki-transactions", "archive", "deliverables", "raw",
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

MARKDOWN_MD_LINK_RE = re.compile(r"\]\(([^)]+?\.md(?:[?#][^)]*)?)\)")
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
REVIEW_BY_REQUIRED_FOLDERS = ("decisions",)
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

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

    def __init__(self, path, text, valid_slugs, source_slugs):
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



__all__ = [
    "ADJUDICATIONS_PATH",
    "FOLDER_TYPE",
    "GLOSSARY_BULLET_ENTRY_RE",
    "LintFailure",
    "LintFailures",
    "LOG_ROTATION_WARN_LINES",
    "PageContext",
    "REVIEW_BY_REQUIRED_FOLDERS",
    "STATUS_RE",
    "STOPWORDS",
    "VOLATILE_STATUS_RE",
    "WIKI_ROOT",
]
