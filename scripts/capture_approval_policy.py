#!/usr/bin/env python3
"""Path confinement and route policy for explicit capture approval."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from typing import NewType

from _repo_paths import MAY_CREATE_FILE, resolve_repo_path
from ledger_common import ALLOWED_ROOT_FILES, ALLOWED_ROOTS, split_scope


ANALYSES_PREFIX = "wiki/analyses/"
APPROVAL_ROUTES = {"analysis-capture", "promotion-audit"}
PROMOTION_TRIGGERS = (
    "reusable_distinction",
    "ranking_or_framework",
    "open_question_resolution",
    "future_agent_behavior",
    "existing_page_update",
)
ACTION_LABELS = {
    "analysis-capture": "File a substantial research answer as an analysis page.",
    "promotion-audit": "Apply an artifact promotion to the wiki.",
}
TRIGGER_LABELS = {
    "reusable_distinction": "reusable distinction",
    "ranking_or_framework": "ranking or framework",
    "open_question_resolution": "open-question resolution",
    "future_agent_behavior": "future-agent behavior",
    "existing_page_update": "existing page update",
}

DraftSha256 = NewType("DraftSha256", str)


def contains_approval_path_placeholder(path: str) -> bool:
    """Return whether a declared path still contains template delimiters."""
    return "<" in path or ">" in path


def is_analyses_path(path: str) -> bool:
    """Case-insensitive (the repo lives on case-insensitive APFS, so a
    case-variant spelling must not slip past the analyses rules) and
    directory-aware: normpath turns 'wiki/analyses/' into the bare
    'wiki/analyses', which is still the analyses folder."""
    lowered = path.lower()
    return lowered.startswith(ANALYSES_PREFIX) or lowered == ANALYSES_PREFIX.rstrip("/")


def normalize_path(path: str) -> str:
    """Validate without normalizing unsafe spellings into safe-looking paths."""
    value = path.strip()
    return resolve_repo_path(
        value,
        repo_root=Path.cwd(),
        allowed_prefixes=(prefix.rstrip("/") for prefix in ALLOWED_ROOTS),
        allowed_root_files=ALLOWED_ROOT_FILES,
        mode=MAY_CREATE_FILE,
    )


def real_destinations(home: str, pages_touched: str) -> list[str]:
    """Concrete declared destination paths, normalized."""
    out: list[str] = []
    for path in [home, *split_scope(pages_touched)]:
        path = path.strip()
        if not path or path == "none" or contains_approval_path_placeholder(path):
            continue
        out.append(normalize_path(path))
    return out


def measure_draft(path: str) -> tuple[int, DraftSha256, str] | None:
    """Measure count and exact hash, retaining decoded text from one read."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = p.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return (
        len(re.findall(r"\w+", text)),
        DraftSha256(hashlib.sha256(data).hexdigest()),
        text,
    )


def classify_accepted(args: argparse.Namespace, word_count: int) -> tuple[str, str, str]:
    """Derive the route for --phase accepted, the only phase that can require
    approval. word_count is the measured count from --path (0 when no path)."""
    qualifies_analysis = (
        args.synthesized_pages >= 3 and word_count > 300 and args.domain_context
    )
    if qualifies_analysis:
        return (
            "analysis-capture",
            args.primary_home or "wiki/analyses/<slug>.md",
            "Matches the research analysis criteria: 3+ pages, >300 words, domain-context question.",
        )

    if args.trigger:
        trigger_labels = [TRIGGER_LABELS[trigger] for trigger in args.trigger]
        return (
            "promotion-audit",
            args.primary_home or "wiki/<page>.md",
            "Promotion trigger present: " + ", ".join(trigger_labels) + ".",
        )

    return (
        "chat-only",
        "none",
        "Does not meet analysis-capture criteria and has no promotion trigger.",
    )


def scope_with_home(home: str, pages_touched: str) -> list[str]:
    """pages_touched as a normalized, deduplicated list, guaranteeing a
    concrete primary_home is included."""
    scope = list(dict.fromkeys(normalize_path(p) for p in split_scope(pages_touched)))
    home = home.strip()
    if home and home != "none" and not contains_approval_path_placeholder(home) and home not in scope:
        scope.insert(0, home)
    return scope


def approval_guard(args: argparse.Namespace, route: str, home: str) -> str | None:
    """Block reasons for approval-required capture routes."""
    if not args.artifact.strip():
        return ("--artifact must be a non-empty description; the gate will not "
                "write an approval record its own validator would reject.")
    if contains_approval_path_placeholder(home) or not home or home == "none":
        return (f"{route} requires a concrete --primary-home path "
                "(no placeholder); name the real durable destination.")
    placeholders = [p for p in split_scope(args.pages_touched) if contains_approval_path_placeholder(p)]
    if placeholders:
        return (f"approval scope must name concrete paths, not placeholders: "
                f"{placeholders}")
    if any(p == "none" for p in split_scope(args.pages_touched)):
        return ("approval scope must name real files; drop the 'none' entries "
                "from --pages-touched.")
    analyses_targets = [d for d in real_destinations(home, args.pages_touched)
                        if is_analyses_path(d)]
    if route == "analysis-capture" or analyses_targets:
        if not args.path:
            target = analyses_targets[0] if analyses_targets else home
            return (f"{route} targeting {target} requires --path to the drafted "
                    "artifact so its word count is measured, not declared; any "
                    f"{ANALYSES_PREFIX} destination in the scope triggers this.")
    return None


__all__ = [
    "ACTION_LABELS",
    "ANALYSES_PREFIX",
    "APPROVAL_ROUTES",
    "DraftSha256",
    "PROMOTION_TRIGGERS",
    "approval_guard",
    "classify_accepted",
    "contains_approval_path_placeholder",
    "is_analyses_path",
    "measure_draft",
    "normalize_path",
    "real_destinations",
    "scope_with_home",
]
