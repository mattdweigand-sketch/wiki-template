#!/usr/bin/env python3
"""Ranked, non-blocking review signals for wiki lint Tier 2."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Sequence
from datetime import date
from pathlib import Path
from typing import TypedDict, Union

from _wiki_parse import (
    FrontmatterError,
    LINK_RE,
    authored_link_view,
    evidentiary_view,
    get_entity_pages,
    parse_log_entry_type,
    status_review_view,
)
from review_due import collect_due_reviews
from wiki_lint_adjudications import Adjudications, glossary_entry_lines, normalize_quote
from wiki_lint_contract import (
    ADJUDICATION_CATEGORY_FIELDS,
    LOG_ROTATION_WARN_LINES,
    REVIEW_BY_REQUIRED_FOLDERS,
    STATUS_RE,
    VOLATILE_STATUS_RE,
    WIKI_ROOT,
)
from wiki_lint_frontmatter import authored_body, nonblocking_frontmatter, nonblocking_frontmatter_block, source_items, source_repo_references
from wiki_lint_repository_checks import parse_sourcing_queue_count_markers

# A quoted span followed by an inline source citation, e.g.
#   "exact words from the source" (source: [[some-page]])
# Straight or curly double quotes; the citation may name several pages.
# This stays deterministic and adjacency-gated on purpose: deciding whether a
# non-adjacent quoted phrase is an attributed source quote, the author's own
# framing, or a rhetorical/example line is a judgment call, which the wiki keeps
# in the wiki-lint evidence-review prose (Tier 3), not in this script.
QUOTED_CITATION_RE = re.compile(
    r'["“]([^"“”]{20,}?)["”]\s*\((?:own[^)]*?, )?source[sd]?:?\s*([^)]*\[\[[^)]*)\)',
    re.IGNORECASE,
)

def quote_fragments(quote):
    """Split a quote on ellipses and bracketed edits; fragments of 6+ words
    must each appear in the source for the quote to count as verbatim."""
    parts = re.split(r"\.\.\.|…|\[[^\]]*\]", quote)
    frags = [normalize_quote(p) for p in parts]
    return [f for f in frags if len(f.split()) >= 6]


def quote_mismatches(entity_pages, adjudicated_quotes, used=None):
    """Tier-2 candidates: quoted text attributed to a source that does not
    appear verbatim in the cited wiki page or its raw files. Deterministic
    string matching only; whether a non-match is a defect (vs. labeled own
    framing) is adjudicated by the lint workflow, not decided here. `used`
    (when given) collects the adjudication keys that suppressed a candidate."""
    by_stem = {p.stem: p for p in entity_pages}
    out, suppressed = [], 0
    for p in entity_pages:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # tier1 reports it
        rel = str(p.relative_to(WIKI_ROOT))
        _, body = nonblocking_frontmatter(text)
        for m in QUOTED_CITATION_RE.finditer(authored_body(body)):
            quote_raw, cite_blob = m.group(1), m.group(2)
            frags = quote_fragments(quote_raw)
            if not frags:
                continue  # too short to judge deterministically
            if "own framing" in m.group(0).lower() or "own interview framing" in m.group(0).lower():
                continue  # explicitly labeled as not a source quote
            # gather cited pages' text plus their raw files
            haystacks = []
            for slug in LINK_RE.findall(cite_blob):
                cited = by_stem.get(slug)
                if cited is None:
                    continue  # dangling link; tier1 reports it
                try:
                    cited_text = cited.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue  # non-UTF8 cited page; tier1 reports it
                haystacks.append(normalize_quote(cited_text))
                cited_fm = nonblocking_frontmatter_block(cited_text)
                if cited_fm:
                    for item in source_items(cited_fm):
                        references, _errors = source_repo_references(item)
                        for kind, canonical in references:
                            if kind != "raw":
                                continue
                            rp = Path.cwd().joinpath(*canonical.split("/"))
                            if rp.is_file():
                                try:
                                    haystacks.append(normalize_quote(
                                        rp.read_text(encoding="utf-8")))
                                except (OSError, UnicodeDecodeError):
                                    pass
            if not haystacks:
                continue
            found = any(all(f in h for f in frags) for h in haystacks)
            if found:
                continue
            key = (rel, normalize_quote(quote_raw))
            if key in adjudicated_quotes:
                if used is not None:
                    used.add(key)
                suppressed += 1
                continue
            preview = quote_raw[:70] + ("..." if len(quote_raw) > 70 else "")
            out.append(f'{rel}: "{preview}" not found in cited source(s)')
    return sorted(out), suppressed


# --------------------------- Tier 2 ---------------------------


def latest_status_date(text):
    # Strip code spans first so a **Status (date)** written as a format example
    # inside a code fence is not read as a real status note.
    out = []
    try:
        view = status_review_view(text)
    except FrontmatterError:
        return None
    for value in STATUS_RE.findall(view):
        try:
            out.append(date.fromisoformat(value))
        except ValueError:
            continue
    return max(out) if out else None


def frontmatter_updated_date(fm):
    if not fm or not fm.get("updated"):
        return None
    try:
        return date.fromisoformat(fm["updated"])
    except ValueError:
        return None


# --------------------------- Tier 2: candidate-signal registry ---------------------------
#
# Tier-2 surfaces ranked review candidates, never hard failures. Each signal
# below is a small function over a shared Tier2Context: it returns
# (items, suppressed_delta), where items is the ranked candidate list and
# suppressed_delta counts how many candidates were dropped because they are
# adjudicated. run_tier2_lint() builds the shared context once, then runs each registered
# signal in order, so the report order and counts are byte-for-byte identical to
# the previous inlined version.


class Tier2PageFacts(TypedDict):
    fm: dict[str, str]
    status_date: date | None
    freshness: date | None
    words: int
    body_links: bool
    source_items: list[str]


Tier2Item = Union[str, tuple[float, str, str], tuple[float, int, str, str]]
Tier2SignalResult = tuple[list[Tier2Item], int]
Tier2Report = dict[str, Union[list[Tier2Item], int]]


class Tier2Context:
    """Shared per-page state every Tier-2 signal reads.

    Computed once in run_tier2_lint() (page text, word counts, the inbound and
    outbound link graphs, and the adjudication sets), so the individual signal
    functions stay small and never re-walk the corpus."""

    __slots__ = ("pages", "data", "inbound", "outbound", "adj", "adj_used")

    pages: list[Path]
    data: dict[Path, Tier2PageFacts]
    inbound: dict[Path, int]
    outbound: dict[Path, set[str]]
    adj: Adjudications
    adj_used: Adjudications

    def __init__(
        self,
        pages: list[Path],
        valid_slugs: Collection[str],
        adjudicated: Adjudications,
    ) -> None:
        self.pages = pages
        self.data = {}
        self.inbound = {p: 0 for p in pages}
        self.outbound = {}
        for p in pages:
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # tier1 reports the encoding failure; skip for candidate signals
                text = ""
            fm, _ = nonblocking_frontmatter(text)
            try:
                ab = evidentiary_view(text)
            except FrontmatterError:
                ab = ""
            status_date = latest_status_date(text)
            dates = [d for d in (frontmatter_updated_date(fm), status_date)
                     if d is not None]
            self.data[p] = {
                "fm": fm or {},
                "status_date": status_date,
                "freshness": max(dates) if dates else None,
                "words": len(re.findall(r"\w+", ab)),
                # A [[link]] inside a code example is not a citation.
                "body_links": bool(LINK_RE.search(ab)),
                # Raw-block parse so block-style sources: lists count as cited.
                "source_items": source_items(nonblocking_frontmatter_block(text)),
            }
            # Outbound links must be authored; generated "Referenced by" blocks
            # would echo inbound links back and fabricate a bidirectional graph,
            # and a [[link]] inside a code span is a syntax example, not an edge
            # (the same rule the dangling scan and the rebuild apply). Fences
            # are blanked before the section strip so a fenced "## Referenced
            # by" example cannot swallow authored links after it.
            try:
                link_view = authored_link_view(text)
            except FrontmatterError:
                link_view = ""
            self.outbound[p] = set(LINK_RE.findall(link_view))

        stems = {p.stem: p for p in pages}
        for p in pages:
            for slug in self.outbound[p]:
                if slug in stems and stems[slug] is not p:
                    self.inbound[stems[slug]] += 1

        # adjudicated is always supplied by the sole caller (tier2 <- main, which
        # passes load_adjudications()); load_adjudications already returns the
        # empty template when the file is absent, so no fallback is needed here.
        self.adj = adjudicated
        # Which adjudication entries actually suppressed a candidate this run.
        # Signals record usage as they suppress; signal_adjudication_dead (kept
        # last in TIER2_SIGNALS) reports the entries that suppressed nothing.
        self.adj_used = {key: set() for key in adjudicated}


Tier2Signal = Callable[[Tier2Context], Tier2SignalResult]


def signal_quote_mismatch(ctx: Tier2Context) -> Tier2SignalResult:
    """Quoted text attributed to a source that is not verbatim in the cited page."""
    return quote_mismatches(ctx.pages, ctx.adj["quotes"], ctx.adj_used["quotes"])


def signal_orphans(ctx: Tier2Context) -> Tier2SignalResult:
    """Pages with no inbound links."""
    orphans = [str(p.relative_to(WIKI_ROOT)) for p in ctx.pages if ctx.inbound[p] == 0]
    out, suppressed = [], 0
    for o in sorted(orphans):
        if o in ctx.adj["orphans"]:
            ctx.adj_used["orphans"].add(o)
            suppressed += 1
        else:
            out.append(o)
    return out, suppressed


def signal_uncited(ctx: Tier2Context) -> Tier2SignalResult:
    """Non-source pages with no sources and no body links. Checked via
    source_items on the raw frontmatter block: the key parser flattens a
    block-style sources: list to '', which must still count as cited."""
    uncited = []
    for p in ctx.pages:
        if p.parent.name == "sources":
            continue
        if not ctx.data[p]["source_items"] and not ctx.data[p]["body_links"]:
            uncited.append(str(p.relative_to(WIKI_ROOT)))
    return sorted(uncited), 0


def signal_thin(ctx: Tier2Context) -> Tier2SignalResult:
    """Pages under 80 authored words."""
    return sorted(
        f"{p.relative_to(WIKI_ROOT)} ({ctx.data[p]['words']}w)"
        for p in ctx.pages if ctx.data[p]["words"] < 80
    ), 0


def signal_log_rotation_due(ctx: Tier2Context) -> Tier2SignalResult:
    """Log file has crossed the documented rotation warning threshold."""
    _ = ctx
    path = WIKI_ROOT / "log.md"
    if not path.exists():
        return [], 0
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], 0  # meta-page encoding is outside this maintenance signal
    line_count = len(text.splitlines())
    if line_count <= LOG_ROTATION_WARN_LINES:
        return [], 0
    return ([f"{path} has {line_count} lines; threshold is {LOG_ROTATION_WARN_LINES}"], 0)


def signal_sourcing_queue_count_drift(ctx: Tier2Context) -> Tier2SignalResult:
    """Entity-count markers in sourcing-queue.md that disagree with the corpus."""
    _ = ctx
    markers, fails = parse_sourcing_queue_count_markers()
    if fails:
        return [], 0  # Tier-1 reports malformed markers
    if not markers:
        return [], 0
    counts = {}
    for page in get_entity_pages(WIKI_ROOT):
        counts[page.parent.name] = counts.get(page.parent.name, 0) + 1
    out = []
    for folder, declared, _line in markers:
        actual = counts.get(folder, 0)
        if declared != actual:
            out.append(
                f"{WIKI_ROOT / 'sourcing-queue.md'}: folder {folder} "
                f"declares {declared} but actual count is {actual}"
            )
    return out, 0


def signal_recompile_candidates(ctx: Tier2Context) -> Tier2SignalResult:
    """Compiled pages older than authored source links they already depend on.

    This is a review prompt, not a stale-page verdict. It only follows direct
    authored links from non-source pages to source pages; reverse source-to-page
    links are intentionally left out until the noisier direction has a proven
    precision case.
    """
    stem_to_pages = {}
    for p in ctx.pages:
        stem_to_pages.setdefault(p.stem, []).append(p)

    out, suppressed = [], 0
    for p in sorted(ctx.pages):
        if p.parent.name == "sources":
            continue
        page_freshness = ctx.data[p].get("freshness")
        if page_freshness is None:
            continue
        page_rel = str(p.relative_to(WIKI_ROOT))
        source_hits = []
        for slug in sorted(ctx.outbound.get(p, set())):
            matches = stem_to_pages.get(slug, [])
            if len(matches) != 1:
                continue
            source = matches[0]
            if source.parent.name != "sources":
                continue
            source_updated = frontmatter_updated_date(ctx.data[source]["fm"])
            if source_updated is None or source_updated <= page_freshness:
                continue
            source_rel = str(source.relative_to(WIKI_ROOT))
            pair = (page_rel, source_rel)
            if pair in ctx.adj["recompile"]:
                ctx.adj_used["recompile"].add(pair)
                suppressed += 1
                continue
            source_hits.append((source_rel, source_updated))
        if source_hits:
            hits = "; ".join(
                f"{source_rel} {source_updated.isoformat()}"
                for source_rel, source_updated in source_hits
            )
            out.append(
                f"{page_rel} (page {page_freshness.isoformat()}): "
                f"newer sources: {hits}"
            )
    return out, suppressed


def signal_glossary_volatile_status(ctx: Tier2Context) -> Tier2SignalResult:
    """Glossary entries restating volatile status.

    Definitions should be durable. When a glossary entry says something is
    still pending or remains open, the claim can rot without any source page
    changing. Resolve by rewriting to a dated fact or delegating to the owner
    page. Adjudicate only durable definitional or rhetorical usage.
    """
    out = []
    suppressed = 0
    hits = dict.fromkeys(
        (term, m.group(0).lower())
        for term, line in glossary_entry_lines()
        for m in VOLATILE_STATUS_RE.finditer(line)
    )
    for term, phrase in hits:
        if (term, phrase) in ctx.adj["glossary_volatile"]:
            ctx.adj_used["glossary_volatile"].add((term, phrase))
            suppressed += 1
            continue
        out.append(f"glossary.md '{term}': \"{phrase}\" (rewrite to a dated "
                   "fact or delegate to the owner page)")
    return out, suppressed


def signal_authority_missing(ctx: Tier2Context) -> Tier2SignalResult:
    """Pages likely needing authority metadata but lacking authority_kind.

    The template version only uses generic signals available in every configured
    wiki: dated Status notes and review_by checkpoints. Domain-specific owner
    registries can add stricter checks later through an explicit tooling change.
    """
    candidates = []
    suppressed = 0
    for p in sorted(ctx.pages):
        rel = str(p.relative_to(WIKI_ROOT))
        if p.parent.name == "sources":
            continue
        fm = ctx.data[p]["fm"]
        if "authority_kind" in fm:
            continue

        priority = None
        reason = None
        if ctx.data[p].get("status_date") is not None:
            priority = 0
            reason = "has dated Status note"
        elif fm.get("review_by"):
            priority = 1
            reason = "has review_by"
        if reason is None:
            continue

        if rel in ctx.adj["authority_missing"]:
            ctx.adj_used["authority_missing"].add(rel)
            suppressed += 1
            continue
        candidates.append((priority, rel, reason))

    out = [f"{rel}: {reason}" for _priority, rel, reason in sorted(candidates)]
    return out, suppressed


def signal_unconsumed_sources(ctx: Tier2Context) -> Tier2SignalResult:
    """Source pages that no non-source entity page cites with an authored link.

    A source linked only by sibling sources, meta pages, or generated
    "Referenced by" blocks was filed but never integrated into the knowledge
    layer. The orphan check cannot see this class because batch-ingested sources
    can cross-link each other; accepted_orphans also suppresses this signal
    because an intentional standalone record is accepted as unconsumed too.
    """
    consumed = set()
    for p in ctx.pages:
        if p.parent.name != "sources":
            consumed |= ctx.outbound[p]

    out, suppressed = [], 0
    for p in sorted(ctx.pages):
        if p.parent.name != "sources" or p.stem in consumed:
            continue
        rel = str(p.relative_to(WIKI_ROOT))
        if rel in ctx.adj["unconsumed_sources"]:
            ctx.adj_used["unconsumed_sources"].add(rel)
            suppressed += 1
        elif rel in ctx.adj["orphans"]:
            ctx.adj_used["orphans"].add(rel)
            suppressed += 1
        else:
            out.append(f"{rel}: no authored link from any non-source entity page")
    return out, suppressed


def signal_review_by_missing(ctx: Tier2Context) -> Tier2SignalResult:
    """Catalog-governed page classes missing outcome-review enrollment.

    Surfaces the classes that should carry a dated review checkpoint but do not.
    Tier-2 and non-blocking: enrollment is a judgment call, and analyses stay
    opt-in (see REVIEW_BY_REQUIRED_FOLDERS)."""
    out = []
    for p in ctx.pages:
        if p.parent.name not in REVIEW_BY_REQUIRED_FOLDERS:
            continue
        if not ctx.data[p]["fm"].get("review_by"):
            out.append(str(p.relative_to(WIKI_ROOT)))
    return sorted(out), 0


# Ingest entries since the last synthesis pass that count as a burst worth
# distilling. The synthesize workflow stays manual and approval-gated; this only
# surfaces the trigger.
SYNTHESIS_BURST_THRESHOLD = 8


def signal_synthesis_due(ctx: Tier2Context) -> Tier2SignalResult:
    """Ingest burst with no synthesis pass following. Counts `ingest` log
    entries after the most recent `synthesis` entry (all of them if none); at
    SYNTHESIS_BURST_THRESHOLD or more, surfaces a candidate so the synthesize
    trigger does not depend on remembering to notice a burst. Self-clearing:
    logging a synthesis pass resets the count."""
    _ = ctx
    path = WIKI_ROOT / "log.md"
    if not path.exists():
        return [], 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return [], 0
    ingests_since = 0
    for line in lines:
        # Type extraction shares the header grammar (parse_log_entry_type in
        # _wiki_parse), so both live header forms are recognized identically.
        entry_type = parse_log_entry_type(line) or ""
        if entry_type.startswith("synthesis"):
            ingests_since = 0
        elif entry_type == "ingest":
            ingests_since += 1
    if ingests_since < SYNTHESIS_BURST_THRESHOLD:
        return [], 0
    return ([f"{ingests_since} ingest entries since the last synthesis pass "
             f"(threshold {SYNTHESIS_BURST_THRESHOLD}); consider a synthesize run"], 0)


def signal_review_due(ctx: Tier2Context) -> Tier2SignalResult:
    """Pages whose review_by date has passed (outcome grading due). Mirrors
    review_due.py on the most-frequently-run surface, so a due review cannot
    wait unseen for the next wiki-eval; the grading itself stays the review
    workflow's judgment. Self-clearing: grading advances or clears review_by."""
    _ = ctx
    due, _bad = collect_due_reviews(WIKI_ROOT, date.today())
    return ([f"{rel} (review_by {val}, {overdue} day(s) overdue)"
             for overdue, rel, val in due], 0)


def _adjudication_entry_labels(category, entries):
    """Human-readable labels for dead adjudication entries of one category."""
    out = []
    for e in sorted(entries, key=repr):
        if isinstance(e, frozenset):
            out.append(f"{category}: " + " ~ ".join(sorted(e)))
        elif isinstance(e, tuple):
            out.append(f"{category}: " + " -> ".join(str(x) for x in e))
        else:
            out.append(f"{category}: {e}")
    return out


def signal_adjudication_dead(ctx: Tier2Context) -> Tier2SignalResult:
    """Adjudication entries that suppressed nothing this run. A dead entry means
    the candidate it settled no longer fires at all, so the suppression is inert
    residue; prune it (or keep it deliberately, if the candidate is expected to
    return). run_tier2_lint() computes this after every other signal regardless of
    registry position, because it reads which entries those signals actually
    consumed via ctx.adj_used.

    """
    out = []
    for key, category in ADJUDICATION_CATEGORY_FIELDS.items():
        dead = ctx.adj[key] - ctx.adj_used[key]
        out.extend(_adjudication_entry_labels(category, dead))
    return sorted(out), 0


# Tier-2 signals as (output key, report label, signal fn), in report order.
# run_tier2_lint() runs each over the shared context and records its (items,
# suppressed_delta) under the key; main() reports them in this order using the
# label. Key, order, and label live in one tuple so adding/removing/reordering a
# signal is a single edit and the computation and report cannot drift. To add a
# signal, write a small signal_*(ctx) -> (items, suppressed) function and add a
# row here. (Meta-page dangling links moved to Tier-1 as a hard failure and are
# no longer surfaced here.)
TIER2_SIGNALS: tuple[tuple[str, str, Tier2Signal], ...] = (
    ("quote_mismatch", "quote mismatches (quoted text not verbatim in cited source)", signal_quote_mismatch),
    ("orphans", "orphans (no inbound links)", signal_orphans),
    ("uncited", "uncited (no sources, no body links)", signal_uncited),
    ("thin", "thin pages (<80 words)", signal_thin),
    ("log_rotation_due", "log rotation due", signal_log_rotation_due),
    ("sourcing_queue_count_drift", "sourcing queue entity count drift", signal_sourcing_queue_count_drift),
    ("recompile_candidates", "compiled pages with newer source inputs (review for no-change, small update, or recompile)", signal_recompile_candidates),
    ("glossary_volatile_status", "glossary entries restating volatile status (rewrite to a dated fact or delegate to the owner page)", signal_glossary_volatile_status),
    ("authority_missing", "pages likely needing authority metadata but lacking authority_kind", signal_authority_missing),
    ("unconsumed_sources", "source pages not consumed by any non-source entity page (wire an authored link or adjudicate)", signal_unconsumed_sources),
    ("review_by_missing", "goals and decisions with no review_by (enroll in the outcome-review loop or leave for now)", signal_review_by_missing),
    ("review_due", "outcome reviews due (review_by has passed; run the review workflow)", signal_review_due),
    ("synthesis_due", "ingest burst with no synthesis pass following (consider a synthesize run)", signal_synthesis_due),
    # adjudication_dead's row sets its report position; run_tier2_lint() computes it
    # after every other signal regardless of where this row sits, because it
    # reads which adjudication entries the other signals consumed.
    ("adjudication_dead", "adjudication entries suppressing nothing this run (prune or keep deliberately)", signal_adjudication_dead),
)


def run_tier2_lint(
    entity_pages: Sequence[Path],
    valid_slugs: Collection[str],
    adjudicated: Adjudications,
) -> Tier2Report:
    """Compute every ranked signal from one shared corpus context."""
    ctx = Tier2Context(list(entity_pages), valid_slugs, adjudicated)

    out = {}
    suppressed = 0
    for key, _label, signal in TIER2_SIGNALS:
        if signal is signal_adjudication_dead:
            continue
        items, delta = signal(ctx)
        out[key] = items
        suppressed += delta

    # Computed after the loop so it sees every other signal's adjudication
    # consumption; the ordering is structural, not a "keep this row last" rule.
    dead_items, dead_delta = signal_adjudication_dead(ctx)
    out["adjudication_dead"] = dead_items
    suppressed += dead_delta

    out["_suppressed"] = suppressed
    return out


# --------------------------- reporting ---------------------------




__all__ = [
    "TIER2_SIGNALS",
    "Tier2Context",
    "Tier2PageFacts",
    "Tier2Report",
    "Tier2Signal",
    "Tier2SignalResult",
    "run_tier2_lint",
]
