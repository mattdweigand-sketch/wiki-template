#!/usr/bin/env python3
"""Seeded evals for Tier-2 review signals and meta maintenance."""

from eval_lint_fixture import *
from _wiki_parse import get_entity_pages

# ---- Tier 2: quote mismatches (evidence check, deterministic half) ----
FIXTURE_QUOTE = "The gamma fixture contains this exact sentence for verbatim quoting."


def seed_quote(root):
    edit(root, "wiki/concepts/beta.md",
         "Beta body text for the lint eval fixture.",
         f'Beta body text for the lint eval fixture. '
         f'"{FIXTURE_QUOTE}" (source: [[gamma]])')


run_case(
    "quote-mismatch-fires",
    seed_quote,
    args=(), expect=("quote mismatch", "not found in cited source"),
)
run_case(
    "quote-verbatim-passes",
    lambda r: (
        edit(r, "wiki/sources/gamma.md",
             "Gamma is an orphan source page.",
             f"Gamma is an orphan source page. {FIXTURE_QUOTE}"),
        seed_quote(r),
    ),
    args=(), absent=("not found in cited source",),
)
run_case(
    "unsafe-raw-symlink-cannot-satisfy-quote",
    lambda r: (
        (r / "raw" / "notes").mkdir(parents=True),
        append(r, "wiki/index.md", "\n" + FIXTURE_QUOTE + "\n"),
        (r / "raw" / "notes" / "escape.txt").symlink_to(
            r / "wiki" / "index.md"
        ),
        edit(
            r,
            "wiki/sources/gamma.md",
            'sources: ["experience: lint eval fixture"]',
            "sources: [raw/notes/escape.txt]",
        ),
        seed_quote(r),
    ),
    args=(),
    expect_code=1,
    expect=("source-ref", "quote mismatch", "not found in cited source"),
)
run_case(
    "quote-mismatch-suppressed",
    lambda r: (
        seed_quote(r),
        write_adjudications(r, reviewed_quotes=[
            {"page": "concepts/beta.md", "quote": FIXTURE_QUOTE,
             "reason": "fixture", "date": "2026-06-11"}]),
    ),
    args=(), expect=("suppressed",), absent=("not found in cited source",),
)

SPLIT_QUOTE_FRAGMENT_A = "Gamma source carries the first coherent quote fragment"
SPLIT_QUOTE_FRAGMENT_B = "Delta source carries the second coherent quote fragment"
SPLIT_QUOTE = f"{SPLIT_QUOTE_FRAGMENT_A} ... {SPLIT_QUOTE_FRAGMENT_B}"


def seed_split_quote(root, *, coherent=False):
    edit(
        root,
        "wiki/concepts/beta.md",
        "Beta body text for the lint eval fixture.",
        f'Beta body text for the lint eval fixture. "{SPLIT_QUOTE}" '
        "(sources: [[gamma]], [[delta-one]])",
    )
    edit(
        root,
        "wiki/sources/gamma.md",
        "Gamma is an orphan source page.",
        "Gamma is an orphan source page. "
        + SPLIT_QUOTE_FRAGMENT_A
        + (" " + SPLIT_QUOTE_FRAGMENT_B if coherent else ""),
    )
    edit(
        root,
        "wiki/concepts/delta-one.md",
        "Delta one body.",
        "Delta one body. " + SPLIT_QUOTE_FRAGMENT_B,
    )


run_case(
    "quote-fragments-split-across-sources-fires",
    lambda r: seed_split_quote(r),
    args=(), expect=("not found in cited source",),
)
run_case(
    "quote-fragments-one-source-passes",
    lambda r: seed_split_quote(r, coherent=True),
    args=(), absent=("not found in cited source",),
)

# ---- Tier 2: compiled-page recompile candidates ----
def seed_recompile_candidate(root):
    edit(root, "wiki/sources/gamma.md", "updated: 2026-06-01", "updated: 2026-06-10")
    append(root, "wiki/concepts/alpha.md", "\n- Derived from: [[gamma]]\n")


PERSON_RECOMPILE_BODY = (
    "Fixture Person records source-backed relationship context for the lint "
    "eval. Person pages are compiled pages in this wiki because they summarize "
    "roles, transactions, decisions, collaboration history, and evidence-backed "
    "status context that can become stale when a newer source clarifies the "
    "person's role. This dense fixture text keeps the page out of unrelated "
    "thin-page noise while the recompile candidate signal proves that people "
    "pages intentionally remain in scope for compiled-page freshness review."
)


def seed_person_recompile_candidate(root):
    edit(root, "wiki/sources/gamma.md", "updated: 2026-06-01", "updated: 2026-06-10")
    (root / "wiki" / "people").mkdir()
    (root / "wiki" / "people" / "fixture-person.md").write_text(
        '---\ntitle: "Fixture Person"\ntype: person\ncreated: 2026-06-01\n'
        'updated: 2026-06-01\nsources: ["experience: lint eval fixture"]\n'
        'tags: [fixture]\nconfidence: medium\nagent_use_cases:\n'
        '  - lint eval fixture\n---\n\n'
        f'{PERSON_RECOMPILE_BODY}\n\n'
        '## Open questions / gaps\n\n- Fixture page; no real questions.\n\n'
        '## Related pages\n\n- Related: [[gamma]]\n'
    )
    append(root, "wiki/index.md",
           "| [fixture-person.md](people/fixture-person.md) | Test person fixture |\n")
    append(root, "wiki/concepts/alpha.md", "\n- Related: [[fixture-person]]\n")


run_case(
    "recompile-candidate-direct-source-link-fires",
    seed_recompile_candidate,
    args=(), expect=("compiled pages with newer source inputs",
                     "concepts/alpha.md (page 2026-06-01): newer sources: sources/gamma.md 2026-06-10"),
)
run_case(
    "recompile-candidate-tier2-only",
    seed_recompile_candidate,
    absent=("compiled pages with newer source inputs", "newer sources: sources/gamma.md"),
)
run_case(
    "recompile-candidate-person-page-fires",
    seed_person_recompile_candidate,
    args=(), expect=("people/fixture-person.md (page 2026-06-01): newer sources: sources/gamma.md 2026-06-10",),
)
run_case(
    "recompile-candidate-generated-backlink-ignored",
    lambda r: (
        edit(r, "wiki/sources/gamma.md", "updated: 2026-06-01", "updated: 2026-06-10"),
        append(r, "wiki/concepts/alpha.md", "\n## Referenced by\n\n**sources/** [[gamma]]\n"),
    ),
    args=(), absent=("newer sources: sources/gamma.md",),
)
run_case(
    "recompile-candidate-same-date-not-flagged",
    lambda r: append(r, "wiki/concepts/alpha.md", "\n- Derived from: [[gamma]]\n"),
    args=(), absent=("newer sources: sources/gamma.md",),
)
run_case(
    "recompile-candidate-status-note-freshness-suppresses",
    lambda r: (
        seed_recompile_candidate(r),
        append(r, "wiki/concepts/alpha.md",
               "\n**Status (2026-06-15):** Alpha reviewed gamma.\n"),
    ),
    args=(), absent=("newer sources: sources/gamma.md",),
)
run_case(
    "recompile-candidate-not-flagged-when-page-fresh",
    lambda r: (
        seed_recompile_candidate(r),
        edit(r, "wiki/concepts/alpha.md", "updated: 2026-06-01", "updated: 2026-06-15"),
    ),
    args=(), absent=("newer sources: sources/gamma.md",),
)
run_case(
    "recompile-candidate-suppressed-by-adjudication",
    lambda r: (
        seed_recompile_candidate(r),
        write_adjudications(r, reviewed_recompile_candidates=[
            {"pair": ["concepts/alpha.md", "sources/gamma.md"],
             "reason": "fixture no-change", "date": "2026-06-26"}]),
    ),
    args=(), expect=("suppressed",), absent=("newer sources: sources/gamma.md",),
)
run_case(
    "recompile-candidate-skips-source-stale-side",
    lambda r: (
        (r / "wiki/sources/epsilon.md").write_text(
            '---\ntitle: "Epsilon"\ntype: source\ncreated: 2026-06-01\n'
            'updated: 2026-06-10\nsources: ["experience: lint eval fixture"]\n'
            'tags: [fixture]\nconfidence: medium\nsource_type: other\n'
            'agent_use_cases:\n  - lint eval fixture\n---\n\n'
            'Epsilon is a newer source page used to prove source pages are not '
            'the stale compiled side of the recompile candidate signal.\n\n'
            '## Open questions / gaps\n\n- Fixture page; no real questions.\n'
        ),
        append(r, "wiki/index.md", "| [epsilon.md](sources/epsilon.md) | Test source epsilon |\n"),
        append(r, "wiki/sources/gamma.md", "\n- Related: [[epsilon]]\n"),
    ),
    args=(), absent=("sources/gamma.md (page 2026-06-01): newer sources: sources/epsilon.md",),
)

# ---- Tier 2: unconsumed source pages (general isolation invariant) ----
UNCONSUMED_LABEL = ("source pages not consumed by any non-source entity page "
                    "(wire an authored link or adjudicate)")
UNCONSUMED_GAMMA = ("sources/gamma.md: no authored link from any non-source "
                    "entity page")


run_case(
    "unconsumed-source-fires",
    None, args=(), expect=(UNCONSUMED_GAMMA,),
)
run_case(
    "unconsumed-source-entity-link-passes",
    lambda r: append(r, "wiki/concepts/alpha.md", "\n- Related: [[gamma]]\n"),
    args=(), expect=(UNCONSUMED_LABEL + ": 0",),
)
run_case(
    # A sibling source's link is filing, not consumption: gamma stops being an
    # orphan but must still fire here.
    "unconsumed-source-peer-link-still-fires",
    lambda r: write_peer_source(r, source_name="gamma"),
    args=(), expect=(UNCONSUMED_GAMMA,),
    absent=("      sources/gamma.md\n",),
)
run_case(
    # A generated Referenced-by echo on an entity page is not consumption.
    "unconsumed-source-generated-backlink-ignored",
    lambda r: append(r, "wiki/concepts/alpha.md",
                     "\n## Referenced by\n\n**sources/**  [[gamma]]\n"),
    args=(), expect=(UNCONSUMED_GAMMA,),
)
run_case(
    "unconsumed-source-suppressed-by-adjudication",
    lambda r: write_adjudications(r, reviewed_unconsumed_sources=[
        {"page": "sources/gamma.md", "reason": "fixture standalone record",
         "date": "2026-07-09"}]),
    args=(), expect=("suppressed",),
    absent=(UNCONSUMED_GAMMA,
            "reviewed_unconsumed_sources: sources/gamma.md"),
)
run_case(
    # An accepted orphan is a fortiori an accepted standalone: one adjudication
    # suppresses both signals, no duplicate entry required.
    "unconsumed-source-accepted-orphan-suppresses",
    lambda r: write_adjudications(r, accepted_orphans=[
        {"page": "sources/gamma.md", "reason": "fixture", "date": "2026-06-11"}]),
    args=(), absent=(UNCONSUMED_GAMMA,),
)
run_case(
    # An adjudicated source that later gains a real consumer is no longer a
    # candidate, so its entry must surface as DEAD, not as "used".
    "unconsumed-adjudication-dead-when-consumed",
    lambda r: (
        append(r, "wiki/concepts/alpha.md", "\n- Related: [[gamma]]\n"),
        write_adjudications(r, reviewed_unconsumed_sources=[
            {"page": "sources/gamma.md", "reason": "fixture standalone record",
             "date": "2026-07-09"}]),
    ),
    args=(),
    expect=("reviewed_unconsumed_sources: sources/gamma.md",),
    absent=(UNCONSUMED_GAMMA,),
)
run_case(
    "unconsumed-adjudication-stale-fires",
    lambda r: write_adjudications(r, reviewed_unconsumed_sources=[
        {"page": "sources/renamed-unconsumed.md", "reason": "x",
         "date": "2026-07-09"}]),
    expect_code=1, expect=("adjudication-stale", "renamed-unconsumed"),
)

# ---- Tier 2: volatile status language in glossary entries ----
GLOSSARY_VOLATILE_LABEL = (
    "glossary entries restating volatile status "
    "(rewrite to a dated fact or delegate to the owner page)"
)


def seed_glossary(root, body):
    (root / "wiki" / "glossary.md").write_text("# Glossary\n\n" + body)


run_case(
    "glossary-volatile-fires",
    lambda r: seed_glossary(
        r,
        "### Alpha Term\n**Definition:** The escrow question remains open.\n",
    ),
    args=(),
    expect=("glossary.md 'Alpha Term': \"remains open\" (rewrite to a dated "
            "fact or delegate to the owner page)",),
)
run_case(
    "glossary-volatile-bullet-entry-fires",
    lambda r: seed_glossary(
        r,
        "## Operating Terms\n\n"
        "- **Alpha Term** - The launch decision is still pending.\n",
    ),
    args=(),
    expect=("glossary.md 'Alpha Term': \"still pending\" (rewrite to a dated "
            "fact or delegate to the owner page)",),
)
run_case(
    "glossary-volatile-boundary-fence-preamble-pass",
    lambda r: seed_glossary(
        r,
        "Preamble text: remains open.\n\n"
        "### Alpha Term\n**Definition:** The spending reserve; "
        "policy issued 2026-06-30.\n\n"
        "```\n### Example\nremains open\n```\n",
    ),
    args=(),
    expect=(GLOSSARY_VOLATILE_LABEL + ": 0",),
)
run_case(
    "glossary-volatile-suppressed-by-adjudication",
    lambda r: (
        seed_glossary(
            r,
            "### Alpha Term\n**Definition:** ARR not yet recognized as revenue.\n",
        ),
        write_adjudications(r, reviewed_glossary_volatile=[
            {"term": "Alpha Term", "phrase": "not yet",
             "reason": "fixture definitional usage", "date": "2026-07-04"}]),
    ),
    args=(),
    expect=(GLOSSARY_VOLATILE_LABEL + ": 0", "suppressed"),
    absent=("glossary.md 'Alpha Term'",),
)
run_case(
    "glossary-volatile-adjudication-missing-term-fires",
    lambda r: (
        seed_glossary(r, "### Alpha Term\n**Definition:** Fixture.\n"),
        write_adjudications(r, reviewed_glossary_volatile=[
            {"term": "Renamed Away", "phrase": "not yet",
             "reason": "fixture", "date": "2026-07-04"}]),
    ),
    expect_code=1,
    expect=("adjudication-stale", "missing glossary term"),
)
run_case(
    "glossary-volatile-adjudication-bad-phrase-fires",
    lambda r: (
        seed_glossary(r, "### Alpha Term\n**Definition:** Fixture.\n"),
        write_adjudications(r, reviewed_glossary_volatile=[
            {"term": "Alpha Term", "phrase": "banana",
             "reason": "fixture", "date": "2026-07-04"}]),
    ),
    expect_code=1,
    expect=("not in the volatile-language vocabulary",),
)
run_case(
    "glossary-volatile-dead-adjudication-reported",
    lambda r: (
        seed_glossary(
            r,
            "### Alpha Term\n**Definition:** Fixture with no volatile language.\n",
        ),
        write_adjudications(r, reviewed_glossary_volatile=[
            {"term": "Alpha Term", "phrase": "not yet",
             "reason": "fixture", "date": "2026-07-04"}]),
    ),
    args=(),
    expect=("reviewed_glossary_volatile: Alpha Term -> not yet",),
)

# ---- Tier 2: authority metadata adoption ----
run_case(
    "authority-missing-status-note-fires",
    lambda r: append(r, "wiki/concepts/alpha.md",
                     "\n**Status (2026-06-15):** Alpha is currently active.\n"),
    args=(), expect=("pages likely needing authority metadata",
                     "concepts/alpha.md: has dated Status note"),
)
run_case(
    "authority-missing-review-by-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md", "confidence: medium",
                   "confidence: medium\nreview_by: 2026-12-31"),
    args=(), expect=("pages likely needing authority metadata",
                     "concepts/alpha.md: has review_by"),
)
run_case(
    "authority-missing-suppressed-by-adjudication",
    lambda r: (
        append(r, "wiki/concepts/alpha.md",
               "\n**Status (2026-06-15):** Alpha is currently active.\n"),
        write_adjudications(r, reviewed_authority_missing=[
            {"page": "concepts/alpha.md", "reason": "fixture no-change",
             "date": "2026-07-04"}]),
    ),
    args=(), expect=("suppressed",),
    absent=("concepts/alpha.md: has dated Status note",
            "reviewed_authority_missing: concepts/alpha.md"),
)

# ---- Tier 2: candidates and suppression ----
run_case("orphan-surfaces", None, args=(), expect=("sources/gamma.md",))
run_case(
    "orphan-suppressed-by-adjudication",
    lambda r: write_adjudications(r, accepted_orphans=[
        {"page": "sources/gamma.md", "reason": "fixture", "date": "2026-06-11"}]),
    # the bare line is the orphan listing; the thin-pages listing has a "(Nw)"
    # suffix. A consumed suppression must NOT show up as a dead adjudication.
    args=(), expect=("suppressed",),
    absent=("      sources/gamma.md\n", "accepted_orphans: sources/gamma.md"),
)
run_case(
    "missing-adjudication-file-degrades-gracefully",
    lambda r: (r / "scripts" / "lint-adjudications.json").unlink(),
    args=(), expect=("sources/gamma.md",),
)
# ---- Tier 2: positive cases ----
run_case(
    # The Open questions / gaps mandate is Tier-1 (SCHEMA requires it on every
    # non-source page): removing the heading fails the gate.
    "missing-open-questions-fails-tier1",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   "## Open questions / gaps", "## Notes"),
    expect_code=1, expect=("open-questions", "missing Open questions / gaps section"),
)
run_case(
    # Sources are exempt from the Open-questions mandate (gamma has none).
    "sources-exempt-from-open-questions",
    None,
    absent=("sources/gamma.md: missing Open questions",),
)
run_case(
    # signal_thin had no case: every fixture page is under 80 words, so the
    # "(Nw)" listing must name them. Deleting the signal removes the marker.
    "thin-page-surfaces",
    None,
    args=(), expect=("thin pages (<80 words):", "concepts/alpha.md ("),
)
run_case(
    # signal_uncited had no case: a page with empty sources and no authored
    # body links must surface. The clean fixture has zero uncited pages.
    "uncited-surfaces",
    lambda r: (
        (r / "wiki" / "concepts" / "uncited-fixture.md").write_text(
            '---\ntitle: "Uncited"\ntype: concept\ncreated: 2026-06-01\n'
            'updated: 2026-06-01\nsources: []\ntags: [fixture]\n'
            'confidence: medium\nagent_use_cases:\n  - lint eval fixture\n---\n\n'
            'Uncited fixture body with no links and no sources at all.\n\n'
            '## Open questions / gaps\n\n- Fixture page; no real questions.\n'
        ),
        add_index_row(r, "concepts/uncited-fixture.md", "uncited fixture"),
    ),
    args=(), expect=("uncited (no sources, no body links): 1",
                     "concepts/uncited-fixture.md"),
)
run_case(
    # A block-style sources: list is flattened to '' by the key parser, but the
    # page is cited: it must NOT surface as uncited.
    "block-sourced-page-not-uncited",
    lambda r: (
        (r / "wiki" / "concepts" / "block-sourced-fixture.md").write_text(
            '---\ntitle: "Block sourced"\ntype: concept\ncreated: 2026-06-01\n'
            'updated: 2026-06-01\nsources:\n  - "experience: block-style fixture"\n'
            'tags: [fixture]\n'
            'confidence: medium\nagent_use_cases:\n  - lint eval fixture\n---\n\n'
            'Block-sourced fixture body with no links.\n\n'
            '## Open questions / gaps\n\n- Fixture page; no real questions.\n'
        ),
        add_index_row(r, "concepts/block-sourced-fixture.md", "block sourced fixture"),
    ),
    args=(), expect=("uncited (no sources, no body links): 0",),
)
run_case(
    # A [[link]] inside a code fence is a syntax example, not a graph edge:
    # gamma must STAY an orphan when the only "link" to it is fenced. Before the
    # shared strip_code_spans rule reached the outbound scan, this fenced link
    # suppressed the orphan signal.
    "code-fence-link-is-not-an-edge",
    lambda r: append(r, "wiki/concepts/alpha.md",
                     "\n```\nSyntax example: [[gamma]] inside a fence.\n```\n"),
    args=(), expect=("      sources/gamma.md\n",),
)
run_case(
    # review_due Tier-2 surface: a page whose review_by has passed is listed.
    "review-due-surfaces",
    lambda r: edit(r, "wiki/concepts/alpha.md", "updated: 2026-06-01",
                   "updated: 2026-06-01\nreview_by: 2020-01-01"),
    args=(), expect=("outcome reviews due (review_by has passed; run the review workflow): 1",
                     "concepts/alpha.md (review_by 2020-01-01"),
)
run_case(
    # adjudication_dead: an entry that suppresses nothing (alpha has inbound
    # links, so it is not an orphan) is reported as inert residue.
    "adjudication-dead-surfaces",
    lambda r: write_adjudications(r, accepted_orphans=[
        {"page": "concepts/alpha.md", "reason": "fixture", "date": "2026-06-11"}]),
    args=(), expect=("adjudication entries suppressing nothing",
                     "accepted_orphans: concepts/alpha.md"),
)
def write_burst_log(root, ingests, then_synthesis=False, trailing_ingests=0):
    lines = ["# Log\n\n"]
    day = 1
    for _ in range(ingests):
        lines.append(f"## [2026-03-{day:02d}] ingest | fixture source {day}\nBody.\n\n")
        day += 1
    if then_synthesis:
        lines.append(f"## [2026-03-{day:02d}] synthesis | fixture pass\nBody.\n\n")
        day += 1
    for _ in range(trailing_ingests):
        lines.append(f"## [2026-03-{day:02d}] ingest | fixture source {day}\nBody.\n\n")
        day += 1
    (root / "wiki" / "log.md").write_text("".join(lines))


run_case(
    # synthesis_due: an ingest burst with no synthesis pass following fires.
    "synthesis-due-burst-fires",
    lambda r: write_burst_log(r, ingests=8),
    args=(), expect=("ingest burst with no synthesis pass following", "8 ingest entries"),
)
run_case(
    # A synthesis entry resets the count: burst then synthesis then a few
    # ingests stays quiet.
    "synthesis-due-reset-by-synthesis-entry",
    lambda r: write_burst_log(r, ingests=8, then_synthesis=True, trailing_ingests=3),
    args=(), absent=("ingest entries since the last synthesis pass",),
)
run_case(
    # The plain-pipe header form ("## date | type | ...") is a recognized live
    # form and must count toward the burst exactly like the bracketed form.
    "synthesis-due-plain-pipe-headers-fire",
    lambda r: (r / "wiki" / "log.md").write_text(
        "# Log\n\n" + "".join(
            f"## 2026-03-{d:02d} | ingest | fixture source {d}\nBody.\n\n"
            for d in range(1, 9))),
    args=(), expect=("ingest burst with no synthesis pass following",
                     "8 ingest entries"),
)
run_case(
    # One below the burst threshold stays quiet.
    "synthesis-due-below-threshold-quiet",
    lambda r: write_burst_log(r, ingests=7),
    args=(), absent=("ingest entries since the last synthesis pass",),
)

# ---- Tier 2: meta-maintenance signals ----
def write_log(root, lines):
    (root / "wiki" / "log.md").write_text(
        "".join(f"line {i}\n" for i in range(1, lines + 1))
    )


def write_sourcing_queue(root: Path, *markers: str) -> None:
    (root / "wiki" / "sourcing-queue.md").write_text(
        "# Sourcing Queue\n\n" + "\n".join(markers) + "\n"
    )


def fixture_entity_count(root, folder):
    return sum(1 for p in get_entity_pages(root / "wiki") if p.parent.name == folder)


CONCEPT_FIXTURE_COUNT = fixture_entity_count(FIXTURE, "concepts")
SOURCE_FIXTURE_COUNT = fixture_entity_count(FIXTURE, "sources")


run_case(
    "log-rotation-due-fires",
    lambda r: write_log(r, 2501),
    args=(), expect=("log rotation due: 1",
                     "wiki/log.md has 2501 lines; threshold is 2500"),
)
run_case(
    "log-rotation-below-threshold-clean",
    lambda r: write_log(r, 2500),
    args=(), expect=("log rotation due: 0",),
    absent=("wiki/log.md has",),
)
run_case(
    "log-absent-clean-fixture-passes",
    None,
    args=(), expect=("log rotation due: 0",),
    absent=("wiki/log.md has",),
)
run_case(
    "sourcing-queue-count-drift-fires",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts count=99 -->"
    ),
    args=(), expect=("sourcing queue entity count drift: 1",
                     f"folder concepts declares 99 but actual count is {CONCEPT_FIXTURE_COUNT}"),
)
run_case(
    "sourcing-queue-count-drift-clean",
    lambda r: write_sourcing_queue(
        r,
        "<!-- lint:entity-count folder=concepts "
        f"count={fixture_entity_count(r, 'concepts')} -->",
    ),
    args=(), expect=("sourcing queue entity count drift: 0",),
    absent=("folder concepts declares",),
)
run_case(
    "sourcing-queue-count-drift-multiple-markers-only-stale-fires",
    lambda r: write_sourcing_queue(
        r,
        "<!-- lint:entity-count folder=concepts count=99 -->",
        f"<!-- lint:entity-count folder=sources count={SOURCE_FIXTURE_COUNT} -->",
    ),
    args=(), expect=("sourcing queue entity count drift: 1",
                     f"folder concepts declares 99 but actual count is {CONCEPT_FIXTURE_COUNT}"),
    absent=("folder sources declares",),
)
run_case(
    "sourcing-queue-count-bad-folder-fails-tier1",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=unknown count=0 -->"
    ),
    expect_code=1, expect=("sourcing-queue-count-marker", "unknown folder"),
)
run_case(
    "sourcing-queue-count-missing-folder-fails-tier1",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count count=0 -->"
    ),
    expect_code=1, expect=("sourcing-queue-count-marker", "missing folder"),
)
run_case(
    "sourcing-queue-count-bad-count-fails-tier1",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts count=many -->"
    ),
    expect_code=1, expect=("sourcing-queue-count-marker", "not an integer"),
)
run_case(
    "sourcing-queue-count-negative-count-fails-tier1",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts count=-3 -->"
    ),
    args=(), expect_code=1,
    expect=("sourcing-queue-count-marker", "non-negative",
            "sourcing queue entity count drift: 0"),
    absent=("folder concepts declares",),
)
run_case(
    "sourcing-queue-count-missing-count-fails-tier1",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts -->"
    ),
    expect_code=1, expect=("sourcing-queue-count-marker", "missing count"),
)
run_case(
    "sourcing-queue-count-duplicate-folder-fails-tier1",
    lambda r: write_sourcing_queue(
        r,
        "<!-- lint:entity-count folder=concepts count=5 -->",
        "<!-- lint:entity-count folder=concepts count=5 -->",
    ),
    expect_code=1, expect=("sourcing-queue-count-marker", "duplicate folder"),
)

raise SystemExit(finish_lint_eval())
