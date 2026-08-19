#!/usr/bin/env python3
"""Persistent adjudication parsing and suppression views for wiki lint."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Union

from wiki_lint_contract import GLOSSARY_BULLET_ENTRY_RE, WIKI_ROOT
from wiki_lint_repository_checks import read_adjudications


AdjudicationValue = Union[str, frozenset[str], tuple[str, str]]
Adjudications = dict[str, set[AdjudicationValue]]


def normalize_quote(text: str) -> str:
    """Lowercase, straighten curly quotes, collapse whitespace and punctuation
    that survives transcription differences, so verbatim matching is honest
    but not brittle."""
    text = text.lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", " ").replace("–", " ")
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def glossary_entry_lines() -> Iterator[tuple[str, str]]:
    """Yield (term, line) for every non-fenced body line of each glossary entry.

    The template's starter glossary uses bold bullet entries, while the durable
    entry template uses `### Term` headings. Support both so the lint signal
    protects current starter content and future configured entries.
    """
    path = WIKI_ROOT / "glossary.md"
    if not path.exists():
        return
    term = None
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("### "):
            term = line[4:].strip()
            continue
        bullet = GLOSSARY_BULLET_ENTRY_RE.match(line)
        if bullet:
            yield bullet.group("term").strip(), bullet.group("body")
            continue
        if term is not None:
            yield term, line


def load_adjudications() -> Adjudications:
    """Settled Tier-2 judgments, held as data so lint stops re-surfacing them.

    Returns a dict of plain sets/pair-sets; empty when the file is absent so
    lint stays fully operable without it.
    """
    empty: Adjudications = {
        "orphans": set(), "hubs": set(), "pairs": set(),
        "confidence": set(), "duplicates": set(), "quotes": set(),
        "recompile": set(), "authority_missing": set(),
        "glossary_volatile": set(),
        "unconsumed_sources": set(),
    }
    raw, err = read_adjudications()
    if not raw:
        # absent file or invalid file: suppress nothing; tier1 reports the error
        return empty
    return {
        "orphans": {e["page"] for e in raw.get("accepted_orphans", [])},
        "hubs": {e["page"] for e in raw.get("hub_pages", [])},
        "pairs": {frozenset(e["pair"]) for e in raw.get("skipped_crossref_pairs", [])},
        "confidence": {e["page"] for e in raw.get("reviewed_confidence_low", [])},
        "duplicates": {frozenset(e["pair"]) for e in raw.get("reviewed_near_duplicates", [])},
        "quotes": {(e["page"], normalize_quote(e["quote"]))
                   for e in raw.get("reviewed_quotes", [])},
        "recompile": {(e["pair"][0], e["pair"][1])
                      for e in raw.get("reviewed_recompile_candidates", [])},
        "authority_missing": {e["page"] for e in raw.get("reviewed_authority_missing", [])},
        "glossary_volatile": {(e["term"], e["phrase"].lower())
                              for e in raw.get("reviewed_glossary_volatile", [])},
        "unconsumed_sources": {e["page"]
                               for e in raw.get("reviewed_unconsumed_sources", [])},
    }



__all__ = [
    "Adjudications",
    "glossary_entry_lines",
    "load_adjudications",
    "normalize_quote",
]
