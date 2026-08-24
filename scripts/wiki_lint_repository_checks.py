#!/usr/bin/env python3
"""Repository-wide deterministic checks for wiki lint."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from _file_transactions import transaction_status
from _wiki_parse import META_PAGES, get_entity_pages, parse_log_entry_date
from wiki_lint_contract import (
    ADJUDICATIONS_PATH,
    FOLDER_TYPE,
    KEBAB_RE,
    LintFailures,
    RAW_ALLOWED_FILES,
    ROOT_ALLOWED_DIRS,
    ROOT_ALLOWED_FILES,
    SOURCING_QUEUE_COUNT_ATTR_RE,
    SOURCING_QUEUE_COUNT_MARKER_INTENT_RE,
    SOURCING_QUEUE_COUNT_MARKER_RE,
    WIKI_ALLOWED_DIRS,
    WIKI_ALLOWED_FILES,
    WIKI_ROOT,
)
from wiki_lint_frontmatter import fm_scalar
from wiki_entity_catalog import load_entity_catalog, validate_configured_layout


RawBucketRegistry = tuple[Optional[set[str]], Optional[str]]
SourcingQueueMarker = tuple[str, int, int]
SourcingQueueMarkers = tuple[list[SourcingQueueMarker], LintFailures]
AdjudicationDocument = dict[str, object]
TRACKED_RAW_EXCEPTIONS = frozenset({"raw/.gitkeep", "raw/README.md"})


def check_no_tracked_raw_artifacts() -> LintFailures:
    """Reject Git-tracked source artifacts under raw/, case-insensitively."""
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        if Path(".git").exists():
            return [("raw-tracked", "raw/", f"could not inspect Git tracking: {exc}")]
        return []
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        if Path(".git").exists():
            return [("raw-tracked", "raw/", "could not inspect Git tracking")]
        return []
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        return [("raw-tracked", "raw/", f"could not inspect Git tracking: {exc}")]
    if tracked.returncode != 0:
        detail = tracked.stderr.decode("utf-8", errors="replace").strip()
        return [("raw-tracked", "raw/", detail or "git ls-files failed")]
    failures: LintFailures = []
    for raw_path in tracked.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if path.lower().startswith("raw/") and path not in TRACKED_RAW_EXCEPTIONS:
            failures.append((
                "raw-tracked",
                path,
                "raw source artifacts must remain local and untracked",
            ))
    return failures


def read_raw_buckets_registry() -> RawBucketRegistry:
    """Load the governed raw-folder taxonomy, even when raw/ is absent.

    A malformed or empty registry must not disable membership checks by making
    the raw tree temporarily empty. Returns ``(bucket_names, error)``.
    """
    path = Path("scripts/raw-buckets.json")
    if not path.exists():
        return None, "raw bucket taxonomy file is missing"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"unreadable JSON: {exc}"
    if not isinstance(raw, dict):
        return None, "top level must be a JSON object"
    description = raw.get("description")
    if not isinstance(description, str) or not fm_scalar(description):
        return None, "must contain a nonempty string 'description'"
    buckets = raw.get("buckets")
    if not isinstance(buckets, dict):
        return None, "must contain a 'buckets' object"
    if not buckets:
        return None, "'buckets' must be a nonempty object"
    for key, value in buckets.items():
        if not isinstance(key, str) or not KEBAB_RE.fullmatch(key):
            return None, f"bucket key {key!r} is not kebab-case"
        if not isinstance(value, str) or not fm_scalar(value):
            return None, f"bucket {key!r} needs a nonempty string description"
    return set(buckets), None


def check_meta_utf8() -> LintFailures:
    """Read every present governed wiki-root Markdown page as UTF-8."""
    fails = []
    for name in sorted(META_PAGES):
        path = WIKI_ROOT / f"{name}.md"
        if not path.exists():
            continue
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            fails.append(("meta-encoding", str(path), f"not valid UTF-8: {exc}"))
        except OSError as exc:
            fails.append(("meta-encoding", str(path), f"could not read: {exc}"))
    return fails


def check_configured_entity_layout() -> LintFailures:
    """Configured wikis contain exactly their declared active entity folders."""
    validation = validate_configured_layout(Path.cwd().resolve(), load_entity_catalog())
    return [
        ("entity-configuration", "wiki/domain.md", problem)
        for problem in validation.errors
    ]


# --------------------------- Tier 1 ---------------------------


def check_folder_structure() -> LintFailures:
    """Repo-level structure rules that should never require judgment."""
    fails = []

    for p in sorted(Path(".").rglob(".DS_Store")):
        if ".git" in p.parts:
            continue
        fails.append(("os-metadata", str(p), "remove Finder metadata file"))

    for p in sorted(Path(".").iterdir()):
        name = p.name
        if p.is_dir():
            if name not in ROOT_ALLOWED_DIRS:
                fails.append(("repo-structure", name, "unexpected top-level directory"))
        elif p.is_file():
            if name not in ROOT_ALLOWED_FILES:
                fails.append(("repo-structure", name, "unexpected top-level file"))
        else:
            fails.append(("repo-structure", name, "unexpected top-level entry type"))

    if WIKI_ROOT.exists():
        for p in sorted(WIKI_ROOT.iterdir()):
            name = p.name
            rel = str(p)
            if p.is_dir():
                if name not in WIKI_ALLOWED_DIRS:
                    fails.append(("wiki-structure", rel, "unexpected wiki/ folder"))
                else:
                    # Entity pages are exactly one level deep. Report a direct
                    # bad entry once; descendants of an already-invalid direct
                    # directory add no useful information.
                    for entry in sorted(p.iterdir()):
                        entry_rel = str(entry)
                        if entry.is_symlink():
                            fails.append(("wiki-structure", entry_rel,
                                          "unexpected direct special entry in entity folder"))
                        elif entry.is_dir():
                            fails.append(("wiki-structure", entry_rel,
                                          "direct directory in entity folder; pages must be direct .md files"))
                        elif entry.is_file() and entry.name == ".gitkeep":
                            # Fresh template clones retain empty entity folders
                            # with tracked placeholders until setup creates pages.
                            continue
                        elif entry.is_file() and entry.suffix != ".md":
                            fails.append(("wiki-structure", entry_rel,
                                          "direct non-.md file in entity folder"))
                        elif not entry.is_file():
                            fails.append(("wiki-structure", entry_rel,
                                          "unexpected direct special entry in entity folder"))
            elif p.is_file():
                if name not in WIKI_ALLOWED_FILES:
                    fails.append(("wiki-structure", rel, "unexpected wiki/ root file"))
            else:
                fails.append(("wiki-structure", rel, "unexpected wiki/ entry type"))

    raw_buckets_path = Path("scripts/raw-buckets.json")
    raw_allowed_dirs, raw_registry_error = read_raw_buckets_registry()
    if raw_registry_error:
        fails.append(("raw-buckets", str(raw_buckets_path), raw_registry_error))

    raw_root = Path("raw")
    if raw_root.exists():
        for p in sorted(raw_root.iterdir()):
            name = p.name
            rel = str(p)
            if p.is_dir():
                if not KEBAB_RE.match(name):
                    fails.append(("raw-structure", rel, "raw/ folder is not kebab-case"))
                if raw_allowed_dirs is not None and name not in raw_allowed_dirs:
                    fails.append(("raw-structure", rel, "raw/ folder missing from scripts/raw-buckets.json"))
            elif p.is_file():
                if name not in RAW_ALLOWED_FILES:
                    fails.append(("raw-structure", rel, "loose raw/ file; place source artifacts in a typed subfolder"))
            else:
                fails.append(("raw-structure", rel, "unexpected raw/ entry type"))

    deliverables_root = Path("deliverables")
    if deliverables_root.exists():
        for p in sorted(deliverables_root.iterdir()):
            rel = str(p)
            if p.is_dir():
                if not KEBAB_RE.match(p.name):
                    fails.append(("deliverables-structure", rel, "deliverables/ subfolder is not kebab-case"))
            elif p.name == ".gitkeep":
                # The tracked placeholder (mirroring raw/.gitkeep) that ships
                # the folder with a fresh clone; not a loose deliverable.
                continue
            else:
                fails.append(("deliverables-structure", rel, "loose deliverable; move it into a clearly labeled subfolder"))

    # tmp/ is intentionally disposable scratch space. Lint does not govern
    # its contents; the maintenance workflow may empty it at the end of a run.
    transactions_clean, transaction_reports = transaction_status(Path.cwd().resolve())
    if not transactions_clean:
        for detail in transaction_reports:
            fails.append(("transaction-state", ".wiki-transactions/", detail))
    return fails


# Stray agent tool-call artifacts that leak into a page when an ingest Write/Edit
# call's own closing/opening tags get pasted into the content. </content> and
# </invoke> are closing tags matched exactly; <parameter ... > is an opening tag
# matched by prefix (it carries attributes). Each is matched only as a standalone
# line (the whole stripped line is the artifact), so a legitimate prose mention
# of a tag inside a sentence does not fire. This has recurred (a prior cleanup is
# logged in wiki/log.md), so it gets a deterministic guard.
STRAY_TAG_EXACT = {"</content>", "</invoke>"}


def check_stray_tool_tags() -> LintFailures:
    """Fail Tier-1 on stray agent tool-call tag lines committed into wiki/ pages.

    Scans every wiki/ Markdown file, meta pages included, because ingest writes
    touch both entity and meta pages. A line fires only when its stripped form
    equals </content> or </invoke>, or starts with <parameter; a sentence that
    merely mentions the tag does not."""
    fails = []
    if not WIKI_ROOT.exists():
        return fails
    pages = set(get_entity_pages(WIKI_ROOT))
    pages.update(
        WIKI_ROOT / f"{name}.md"
        for name in META_PAGES
        if (WIKI_ROOT / f"{name}.md").exists()
    )
    for p in sorted(pages):
        # check_folder_structure reports symlinks, directories, FIFOs, and
        # other direct entity specials. This content scan must not dereference
        # or open them before the structural failure can be reported.
        if p.is_symlink() or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # the per-page UTF-8 check reports encoding failures
        except OSError:
            continue  # the owning path/meta read reports regular-file errors
        rel = str(p.relative_to(WIKI_ROOT))
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped in STRAY_TAG_EXACT or stripped.startswith("<parameter"):
                fails.append(("stray-tag", rel,
                              f"line {i}: stray tool-call artifact '{stripped}'"))
    return fails


def parse_sourcing_queue_count_markers() -> SourcingQueueMarkers:
    """Read explicit entity-count markers from wiki/sourcing-queue.md.

    The sourcing queue is prose, so lint does not infer counts from wording.
    Only comments like `<!-- lint:entity-count folder=people count=6 -->` are
    executable. Malformed markers are Tier-1 failures; valid markers feed the
    Tier-2 drift signal.
    """
    path = WIKI_ROOT / "sourcing-queue.md"
    if not path.exists():
        return [], []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [], [("sourcing-queue-count-marker", str(path), f"not valid UTF-8: {e}")]

    markers = []
    fails = []
    seen_folders = set()
    strict_spans = set()
    for match in SOURCING_QUEUE_COUNT_MARKER_RE.finditer(text):
        strict_spans.add(match.span())

    for match in SOURCING_QUEUE_COUNT_MARKER_INTENT_RE.finditer(text):
        if match.span() in strict_spans:
            continue
        line = text.count("\n", 0, match.start()) + 1
        fails.append(("sourcing-queue-count-marker", str(path),
                      f"line {line}: malformed entity-count marker"))

    for match in SOURCING_QUEUE_COUNT_MARKER_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        attrs_text = match.group("attrs")
        attr_matches = list(SOURCING_QUEUE_COUNT_ATTR_RE.finditer(attrs_text))
        pairs = [(item.group(1), item.group(2)) for item in attr_matches]
        valid = True

        cursor = 0
        for item in attr_matches:
            if attrs_text[cursor:item.start()].strip():
                valid = False
            cursor = item.end()
        if attrs_text[cursor:].strip():
            valid = False
        if not valid:
            fails.append(("sourcing-queue-count-marker", str(path),
                          f"line {line}: malformed attribute text"))

        values = {}
        for key, value in pairs:
            if key not in {"folder", "count"}:
                fails.append(("sourcing-queue-count-marker", str(path),
                              f"line {line}: unknown attribute '{key}'"))
                valid = False
            elif key in values:
                fails.append(("sourcing-queue-count-marker", str(path),
                              f"line {line}: duplicate attribute '{key}'"))
                valid = False
            else:
                values[key] = value

        folder = values.get("folder")
        count_text = values.get("count")

        if not folder:
            fails.append(("sourcing-queue-count-marker", str(path),
                          f"line {line}: missing folder"))
            valid = False
        elif folder not in FOLDER_TYPE:
            fails.append(("sourcing-queue-count-marker", str(path),
                          f"line {line}: unknown folder '{folder}'"))
            valid = False
        elif folder in seen_folders:
            fails.append(("sourcing-queue-count-marker", str(path),
                          f"line {line}: duplicate folder '{folder}'"))
            valid = False

        if count_text is None:
            fails.append(("sourcing-queue-count-marker", str(path),
                          f"line {line}: missing count"))
            valid = False
            count = None
        else:
            try:
                count = int(count_text)
            except ValueError:
                fails.append(("sourcing-queue-count-marker", str(path),
                              f"line {line}: count '{count_text}' is not an integer"))
                valid = False
                count = None
            else:
                if count < 0:
                    fails.append(("sourcing-queue-count-marker", str(path),
                                  f"line {line}: count must be non-negative"))
                    valid = False

        if valid:
            seen_folders.add(folder)
            markers.append((folder, count, line))
    return markers, fails


def check_sourcing_queue_count_markers() -> LintFailures:
    """Fail Tier-1 on malformed sourcing-queue entity-count markers."""
    _markers, fails = parse_sourcing_queue_count_markers()
    return fails


def check_log_entry_headers() -> LintFailures:
    """Every "## " line in wiki/log.md must be a recognized entry header
    ("## [YYYY-MM-DD] ..." or "## YYYY-MM-DD ..."), and no "## " line may sit
    inside a fenced code block at all. rotate_log.py cuts the log only at
    recognized headers and is deliberately fence-unaware, so a nonconforming
    header would be silently merged into the previous entry's archive block,
    and a fenced example that LOOKS like a header would become a bogus cut
    point. The grammar is the shared LOG_ENTRY_HEADER_RE in _wiki_parse."""
    fails = []
    path = WIKI_ROOT / "log.md"
    if not path.exists():
        return fails
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        # An undecodable log must fail loudly here: silently returning would
        # disarm the rotate_log cut-point guard for the whole file.
        return [("log-entry-header", str(path), f"not valid UTF-8: {e}")]
    in_fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not line.startswith("## "):
            continue
        if in_fence:
            fails.append(("log-entry-header", str(path),
                          f"line {i}: fenced '## ' line; rotate_log.py cuts are "
                          f"fence-unaware, so reword the example: {line.strip()!r}"))
        elif parse_log_entry_date(line) is None:
            fails.append(("log-entry-header", str(path),
                          f"line {i}: '## ' line is not a recognized log entry "
                          f"header (\"## [YYYY-MM-DD] ...\"): {line.strip()!r}"))
    return fails


def read_adjudications() -> tuple[AdjudicationDocument, str | None]:
    """Parse and shape-validate the adjudication file.

    Returns (raw_dict, error). raw is {} when the file is absent or invalid;
    error is a human-readable string only when the file exists but is bad,
    so Tier-1 can fail loudly instead of suppression silently turning off.
    """
    if not ADJUDICATIONS_PATH.exists():
        return {}, None
    try:
        raw = json.loads(ADJUDICATIONS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return {}, f"unreadable JSON: {e}"
    if not isinstance(raw, dict):
        return {}, "top level must be a JSON object"
    # A suppression filed under a misspelled or retired category key would
    # silently detach; unknown keys fail loudly instead (REFERENCES.md rule).
    # Underscore-prefixed keys are documentation metadata (e.g. _description),
    # never suppression lists.
    known_keys = {
        "accepted_orphans", "reviewed_quotes", "reviewed_recompile_candidates",
        "reviewed_authority_missing", "reviewed_glossary_volatile",
        "reviewed_unconsumed_sources",
    }
    unknown = sorted(k for k in set(raw) - known_keys if not k.startswith("_"))
    if unknown:
        return {}, ("unknown top-level category key(s): " + ", ".join(unknown)
                    + "; suppression entries under an unrecognized key would "
                      "silently detach")
    for key in ("accepted_orphans", "reviewed_authority_missing",
                "reviewed_unconsumed_sources"):
        for e in raw.get(key, []):
            if not isinstance(e, dict) or not isinstance(e.get("page"), str):
                return {}, f"every '{key}' entry needs a string 'page' field"
    for key in ("reviewed_recompile_candidates",):
        for e in raw.get(key, []):
            pair = e.get("pair") if isinstance(e, dict) else None
            if not (isinstance(pair, list) and len(pair) == 2
                    and all(isinstance(x, str) for x in pair)):
                return {}, f"every '{key}' entry needs a two-item string 'pair' field"
    for e in raw.get("reviewed_quotes", []):
        if not (isinstance(e, dict) and isinstance(e.get("page"), str)
                and isinstance(e.get("quote"), str)):
            return {}, "every 'reviewed_quotes' entry needs string 'page' and 'quote' fields"
    for e in raw.get("reviewed_glossary_volatile", []):
        if not (isinstance(e, dict) and isinstance(e.get("term"), str)
                and isinstance(e.get("phrase"), str)):
            return {}, ("every 'reviewed_glossary_volatile' entry needs "
                        "string 'term' and 'phrase' fields")
    return raw, None


# --------------------------- Tier 1: per-page check registry ---------------------------
#
# Each per-page check below is a small, self-contained function a maintainer can
# read in isolation. It receives one PageContext and returns a list of fail
# tuples (check, page_relpath, detail), the same shape the loop appends. Two
# registries list them in evaluation order: TIER1_PATH_CHECKS (path-only, run
# before frontmatter parsing) and TIER1_PAGE_CHECKS (frontmatter-dependent);
# run_tier1_lint() iterates the entity pages and, for each, runs every check in order.
# This preserves the exact emit order of the previous inlined loop (page-outer,
# check-inner), so the grouped/sorted report is byte-for-byte identical.




__all__ = [
    "check_configured_entity_layout",
    "check_folder_structure",
    "check_log_entry_headers",
    "check_meta_utf8",
    "check_no_tracked_raw_artifacts",
    "check_sourcing_queue_count_markers",
    "check_stray_tool_tags",
    "parse_sourcing_queue_count_markers",
    "read_adjudications",
    "read_raw_buckets_registry",
]
