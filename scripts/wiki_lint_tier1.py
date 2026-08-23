#!/usr/bin/env python3
"""Tier-1 wiki lint orchestration over repository and page checks."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from pathlib import Path

from _wiki_parse import META_PAGES, dangling_slugs, get_entity_pages
from wiki_lint_adjudications import glossary_entry_lines
from wiki_lint_contract import (
    ADJUDICATIONS_PATH,
    FOLDER_TYPE,
    GLOSSARY_BULLET_ENTRY_RE,
    LintFailures,
    PageContext,
    VOLATILE_STATUS_RE,
    WIKI_ROOT,
)
from wiki_lint_page_checks import TIER1_PAGE_CHECKS, TIER1_PATH_CHECKS
from wiki_lint_repository_checks import (
    check_configured_entity_layout,
    check_current_state_registry,
    check_folder_structure,
    check_log_entry_headers,
    check_meta_utf8,
    check_no_tracked_raw_artifacts,
    check_sourcing_queue_count_markers,
    check_stale_sweep_proof_entries,
    check_stray_tool_tags,
    read_adjudications,
)
from wiki_entity_catalog import CatalogError, read_domain_configuration
from wiki_provenance import (
    MANIFEST_PATH,
    validate_live_provenance,
    validate_restored_provenance,
    validate_staged_provenance,
)


def meta_dangling_links(valid_slugs):
    """Dangling [[links]] in wiki/ meta pages. The Tier-1 dangling check covers
    entity pages, so this extends the same guarantee to meta pages, which would
    otherwise rot unseen. Excludes code-span examples, folder pointers
    ([[name/]]), and log.md (an append-only history that deliberately preserves
    de-linked references as prose). Uses the shared dangling_slugs helper so the
    entity-page and meta-page scans cannot drift."""
    out = []
    for name in sorted(META_PAGES):
        if name == "log":
            continue
        p = WIKI_ROOT / f"{name}.md"
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for slug in dangling_slugs(text, valid_slugs):
            out.append(f"{name}.md: [[{slug}]]")
    return sorted(set(out))



def run_tier1_lint(
    entity_pages: Sequence[Path],
    valid_slugs: Collection[str],
    index_targets: set[str],
    index_duplicates: Sequence[str],
    index_read_fails: Sequence[tuple[str, str, str]] = (),
    *,
    provenance_view: str = "live",
) -> LintFailures:
    """Compose repository and page checks while preserving failure order."""
    fails = []  # (check, page_relpath, detail)
    fails.extend(check_folder_structure())
    fails.extend(check_no_tracked_raw_artifacts())
    fails.extend(check_configured_entity_layout())
    fails.extend(check_current_state_registry())
    fails.extend(check_meta_utf8())
    fails.extend(check_stray_tool_tags())
    fails.extend(check_sourcing_queue_count_markers())
    fails.extend(check_log_entry_headers())
    fails.extend(check_stale_sweep_proof_entries())
    fails.extend(index_read_fails)
    try:
        domain_configuration = read_domain_configuration(Path.cwd().resolve())
    except CatalogError:
        domain_configuration = None
    if domain_configuration is not None and domain_configuration.status == "configured":
        if provenance_view == "restored":
            provenance_issues = validate_restored_provenance(Path.cwd())
        elif provenance_view == "git":
            provenance_issues = validate_staged_provenance(Path.cwd())
        else:
            provenance_issues = validate_live_provenance(Path.cwd())
        fails.extend(
            ("raw-provenance", MANIFEST_PATH, issue)
            for issue in provenance_issues
        )

    def rel(p):
        return str(p.relative_to(WIKI_ROOT))

    # Structural lint owns special entries. Never dereference a symlink or
    # open a FIFO/device merely because its name ends in .md.
    regular_entity_pages = [
        p for p in entity_pages if not p.is_symlink() and p.is_file()
    ]

    # wikilinks resolve by bare stem, so two pages sharing one is an
    # ambiguous link target and a miscounted inbound graph
    by_stem = {}
    for p in regular_entity_pages:
        by_stem.setdefault(p.stem, []).append(p)
    # source-page slugs, for resolving bare-slug provenance refs
    source_slugs = {
        p.stem for p in regular_entity_pages if p.parent.name == "sources"
    }

    # meta-page dangling links are a hard failure too: a broken [[link]] in
    # index/overview/glossary/synthesis is as deterministic as one on an entity
    # page, so it gates the commit rather than only surfacing for review.
    for hit in meta_dangling_links(valid_slugs):
        fails.append(("meta-dangling-link", hit, "resolves to nothing"))
    for stem, ps in sorted(by_stem.items()):
        if len(ps) > 1:
            others = ", ".join(rel(q) for q in ps)
            for p in ps:
                fails.append(("duplicate-stem", rel(p), f"stem '{stem}' is shared by: {others}"))

    entity_relpaths = set()
    for p in regular_entity_pages:
        r = rel(p)
        entity_relpaths.add(r)
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            fails.append(("encoding", r, f"not valid UTF-8: {e}"))
            continue
        except OSError as e:
            fails.append(("encoding", r, f"could not read: {e}"))
            continue

        ctx = PageContext(p, text, valid_slugs, source_slugs)

        # path-only checks run even without parseable frontmatter.
        for check in TIER1_PATH_CHECKS:
            fails.extend(check(ctx))

        if ctx.fm is None:
            detail = "missing or malformed frontmatter"
            if ctx.frontmatter_error:
                detail += f": {ctx.frontmatter_error}"
            fails.append(("frontmatter", r, detail))
            continue

        # frontmatter-dependent per-page checks, in registry order.
        for check in TIER1_PAGE_CHECKS:
            fails.extend(check(ctx))

    # index coverage (only for paths that name an entity folder). If index.md
    # itself is unreadable, report that root cause instead of flooding the output
    # with every page as index-missing.
    if not index_read_fails:
        for r in sorted(entity_relpaths - index_targets):
            fails.append(("index-missing", r, "no row in index.md"))
        for t in sorted(index_targets - entity_relpaths):
            if "/" in t and t.split("/")[0] in FOLDER_TYPE:
                fails.append(("index-stale", t, "index.md row points to missing page"))
        # "one row per page" is two-sided: coverage above, uniqueness here. Duplicate
        # rows have appeared under concurrent sessions and were invisible to lint.
        for t in index_duplicates:
            if "/" in t and t.split("/")[0] in FOLDER_TYPE:
                fails.append(("index-duplicate", t, "multiple index.md rows point to this page"))

    # the adjudication file must parse and every entry must reference an
    # existing page; otherwise suppression silently turns off or a rename
    # silently detaches the settled judgment.
    raw, adj_err = read_adjudications()
    if adj_err:
        fails.append(("adjudication-file", str(ADJUDICATIONS_PATH), adj_err))
    else:
        referenced = []
        for key in ("accepted_orphans", "hub_pages", "reviewed_confidence_low",
                    "reviewed_quotes", "reviewed_authority_missing",
                    "reviewed_unconsumed_sources"):
            referenced += [e["page"] for e in raw.get(key, [])]
        for key in ("skipped_crossref_pairs", "reviewed_near_duplicates",
                    "reviewed_status_drift"):
            for e in raw.get(key, []):
                referenced += e["pair"]
        for page in sorted(set(referenced)):
            if page not in entity_relpaths:
                fails.append(("adjudication-stale", str(ADJUDICATIONS_PATH),
                              f"entry references missing page '{page}'"))
        for e in raw.get("reviewed_recompile_candidates", []):
            compiled, source = e["pair"]
            if compiled not in entity_relpaths:
                fails.append(("adjudication-stale", str(ADJUDICATIONS_PATH),
                              f"recompile entry references missing compiled page '{compiled}'"))
            elif Path(compiled).parent.name == "sources":
                fails.append(("adjudication-stale", str(ADJUDICATIONS_PATH),
                              f"recompile compiled page must not be under sources/: '{compiled}'"))
            if source not in entity_relpaths:
                fails.append(("adjudication-stale", str(ADJUDICATIONS_PATH),
                              f"recompile entry references missing source page '{source}'"))
            elif Path(source).parent.name != "sources":
                fails.append(("adjudication-stale", str(ADJUDICATIONS_PATH),
                              f"recompile source page must be under sources/: '{source}'"))
        gv_entries = raw.get("reviewed_glossary_volatile", [])
        if gv_entries:
            glossary_terms = {term for term, _line in glossary_entry_lines()}
            for e in gv_entries:
                if e["term"] not in glossary_terms:
                    fails.append(("adjudication-stale", str(ADJUDICATIONS_PATH),
                                  "glossary_volatile entry references missing "
                                  f"glossary term '{e['term']}'"))
                if not VOLATILE_STATUS_RE.fullmatch(e["phrase"]):
                    fails.append(("adjudication-stale", str(ADJUDICATIONS_PATH),
                                  f"glossary_volatile phrase '{e['phrase']}' is "
                                  "not in the volatile-language vocabulary"))

    seen = set()
    deduped = []
    for f in fails:
        if f not in seen:
            seen.add(f)
            deduped.append(f)
    return deduped


def parse_index_targets() -> tuple[set[str], list[str], LintFailures]:
    """(targets, duplicates, read_fails): every .md path index.md links, plus
    the paths more than one row points to (the uniqueness half of "one row per
    page"). read_fails carries root-cause file read problems."""
    idx = WIKI_ROOT / "index.md"
    if not idx.exists():
        return set(), [], []
    try:
        text = idx.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return set(), [], [("index", str(idx), f"not valid UTF-8: {e}")]
    targets = re.findall(r"\]\(([^)]+?\.md)\)", text)
    seen, dups = set(), set()
    for t in targets:
        if t in seen:
            dups.add(t)
        seen.add(t)
    return seen, sorted(dups), []


__all__ = ["parse_index_targets", "run_tier1_lint"]
