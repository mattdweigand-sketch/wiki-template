#!/usr/bin/env python3
"""Regression eval for lint.py.

Guards lint's checks against going vacuous: every check in lint.py's
registries — TIER1_PATH_CHECKS, TIER1_PAGE_CHECKS, the repo/meta-level checks
inside tier1(), and TIER2_SIGNALS (those registries are authoritative; this
docstring deliberately does not enumerate them) — gets a seeded violation that
must fire, and the adjudication/suppression machinery gets positive and
negative cases. A check that cannot fail is indistinguishable from no check;
this suite exists so a future lint edit cannot silently disarm one.

Runs against the fixture mini-wiki in scripts/fixtures/wiki-lint/, copied to
a system temp directory per case. Writes nothing inside the repo.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _file_transactions import run_transaction
from _wiki_parse import META_PAGES, get_entity_pages

REPO_ROOT = Path(__file__).resolve().parents[1]
LINT = REPO_ROOT / "scripts" / "lint.py"
FIXTURE = REPO_ROOT / "scripts" / "fixtures" / "wiki-lint"

results = []


def copy_fixture(root):
    """Materialize the fixture mini-wiki (wiki/ + scripts/) under `root`."""
    shutil.copytree(FIXTURE / "wiki", root / "wiki")
    shutil.copytree(FIXTURE / "scripts", root / "scripts")


def run_case(name, mutate, args=("--tier1",), expect_code=0, expect=(), absent=()):
    """Copy the fixture, apply `mutate(root)`, run lint, assert on output."""
    with tempfile.TemporaryDirectory(prefix="wiki-lint-eval-") as td:
        root = Path(td)
        copy_fixture(root)
        if mutate:
            mutate(root)
        proc = subprocess.run(
            [sys.executable, str(LINT), *args],
            cwd=root, text=True, capture_output=True,
        )
        output = proc.stdout + proc.stderr
        ok = proc.returncode == expect_code
        for marker in expect:
            ok = ok and marker in output
        for marker in absent:
            ok = ok and marker not in output
        results.append((name, ok))
        if not ok:
            print(f"FAIL {name}")
            print(f"  exit {proc.returncode} (expected {expect_code})")
            for marker in expect:
                if marker not in output:
                    print(f"  missing: {marker!r}")
            for marker in absent:
                if marker in output:
                    print(f"  unexpected: {marker!r}")
            print("  output: " + output[:2000].replace("\n", " | "))
        else:
            print(f"PASS {name}")


def append(root, rel, text):
    p = root / rel
    p.write_text(p.read_text() + text)


def edit(root, rel, old, new):
    p = root / rel
    t = p.read_text()
    assert old in t, f"fixture drift: {old!r} not in {rel}"
    p.write_text(t.replace(old, new, 1))


def add_index_row(root, rel, summary):
    append(root, "wiki/index.md", f"| [{Path(rel).name}]({rel}) | {summary} |\n")


def write_adjudications(root, **kwargs):
    base = {"accepted_orphans": [], "hub_pages": [], "skipped_crossref_pairs": [],
            "reviewed_confidence_low": [], "reviewed_near_duplicates": [],
            "reviewed_quotes": [], "reviewed_recompile_candidates": [],
            "reviewed_authority_missing": [], "reviewed_glossary_volatile": [],
            "reviewed_unconsumed_sources": [], "reviewed_status_drift": []}
    base.update(kwargs)
    (root / "scripts" / "lint-adjudications.json").write_text(json.dumps(base))


def write_raw_buckets(root, value):
    (root / "scripts" / "raw-buckets.json").write_text(json.dumps(value))


def write_current_state_registry(root, *, enabled, owners):
    (root / "scripts" / "current-state-owners.json").write_text(json.dumps({
        "schema_version": 1,
        "enabled": enabled,
        "owners": owners,
    }))


def configure_current_state_owner(root, rel, *, updated="2026-07-01", status=None):
    edit(root, f"wiki/{rel}", "updated: 2026-06-01", f"updated: {updated}")
    add_authority(
        root,
        f"wiki/{rel}",
        "authority_kind: owner-page",
        f"authority_ref: wiki/{rel}",
        "authority_freshness: current-state",
    )
    if status:
        append(root, f"wiki/{rel}", f"\n**Status ({status}):** Fixture current state.\n")
    write_current_state_registry(root, enabled=True, owners=[rel])


def add_source_profile(root, name):
    """Add an indexed source with alpha/beta's three-link co-citation profile."""
    path = root / "wiki" / "sources" / f"{name}.md"
    path.write_text(
        f'---\ntitle: "{name.replace("-", " ").title()}"\ntype: source\n'
        'created: 2026-06-01\nupdated: 2026-06-01\n'
        'sources: ["experience: lint eval fixture"]\ntags: [fixture]\n'
        'confidence: medium\nsource_type: other\nagent_use_cases:\n'
        '  - lint eval fixture\n---\n\n'
        'Source profile fixture for cross-reference detector precision.\n\n'
        '## Related pages\n\n'
        '- [[delta-one]]\n- [[delta-two]]\n- [[delta-three]]\n'
    )
    append(root, "wiki/index.md",
           f"| [{name}.md](sources/{name}.md) | Source profile fixture |\n")


def add_authority(root, rel, *lines):
    p = root / rel
    t = p.read_text()
    marker = "confidence: medium\n"
    assert marker in t, f"fixture drift: no confidence marker in {rel}"
    p.write_text(t.replace(marker, marker + "\n".join(lines) + "\n", 1))


def write_peer_source(root, source_name="gamma"):
    (root / "wiki" / "sources" / "peer-source.md").write_text(
        '---\ntitle: "Peer Source"\ntype: source\ncreated: 2026-06-01\n'
        'updated: 2026-06-01\nsources: ["experience: lint eval fixture"]\n'
        'tags: [fixture]\nconfidence: medium\nsource_type: other\n'
        'agent_use_cases:\n  - lint eval fixture\n---\n\n'
        f'This peer source links [[{source_name}]], but source-to-source links '
        'must not satisfy the source consumption invariant.\n\n'
        '## Open questions / gaps\n\n- Fixture page; no real questions.\n'
    )
    add_index_row(root, "sources/peer-source.md", "fixture peer source")
    append(root, "wiki/concepts/alpha.md", "\n- Related: [[peer-source]]\n")



def fail_prerequisite(name, detail, *, sink=None, emit=True):
    """Record an unavailable eval prerequisite as a real failed case."""
    target = results if sink is None else sink
    target.append((name, False))
    if emit:
        print(f"FAIL {name} ({detail})")


# ---- Tier 1: clean fixture is the control ----
run_case("clean-fixture-passes", None)

# ---- Tier 1: explicit optional current-state-owner configuration ----
run_case(
    "current-state-registry-missing-fires",
    lambda r: (r / "scripts" / "current-state-owners.json").unlink(),
    expect_code=1,
    expect=("current-state-registry", "registry is missing"),
)
run_case(
    "current-state-registry-malformed-fires",
    lambda r: (r / "scripts" / "current-state-owners.json").write_text(
        '{"schema_version":1,"enabled":true,"enabled":false,"owners":[]}'
    ),
    expect_code=1,
    expect=("current-state-registry", "duplicate JSON key 'enabled'"),
)
run_case(
    "current-state-owner-missing-fires",
    lambda r: write_current_state_registry(
        r, enabled=True, owners=["concepts/missing.md"]
    ),
    expect_code=1,
    expect=("current-state-registry", "concepts/missing.md", "missing"),
)
run_case(
    "current-state-owner-needs-current-state-authority",
    lambda r: write_current_state_registry(
        r, enabled=True, owners=["concepts/alpha.md"]
    ),
    expect_code=1,
    expect=("current-state-registry", "authority_freshness: current-state"),
)
run_case(
    "configured-current-state-owner-passes-tier1",
    lambda r: configure_current_state_owner(r, "concepts/alpha.md"),
)

# ---- Tier 2: optional current-state drift family ----
run_case(
    "enabled-empty-current-state-registry-advises",
    lambda r: write_current_state_registry(r, enabled=True, owners=[]),
    args=(),
    expect=("enabled current-state registry with no owners: 1",),
)
run_case(
    "current-state-owner-status-missing-fires",
    lambda r: configure_current_state_owner(r, "concepts/alpha.md"),
    args=(),
    expect=("registered current-state owners with no dated Status note: 1",
            "concepts/alpha.md: no parseable dated Status note"),
)
run_case(
    "current-state-owner-self-drift-fires",
    lambda r: configure_current_state_owner(
        r, "concepts/alpha.md", updated="2026-06-01", status="2026-07-01"
    ),
    args=(),
    expect=("current-state owner Status notes newer than their updated frontmatter: 1",
            "concepts/alpha.md: updated 2026-06-01, status 2026-07-01"),
)
run_case(
    "current-state-status-drift-fires",
    lambda r: (
        configure_current_state_owner(
            r, "concepts/alpha.md", updated="2026-07-01", status="2026-07-01"
        ),
        edit(r, "wiki/concepts/delta-one.md", "[[alpha]]", "[[beta]]"),
        append(r, "wiki/concepts/beta.md", "\n- Related: [[alpha]]\n"),
    ),
    args=(),
    expect=("pages older than a registered current-state owner they reference: 1",
            "concepts/beta.md (page 2026-06-01) -> concepts/alpha.md"),
)
run_case(
    "current-state-source-page-is-not-stale-side",
    lambda r: (
        configure_current_state_owner(
            r, "concepts/alpha.md", updated="2026-07-01", status="2026-07-01"
        ),
        edit(r, "wiki/concepts/delta-one.md", "[[alpha]]", "[[beta]]"),
        append(r, "wiki/sources/gamma.md", "\n- Related: [[alpha]]\n"),
    ),
    args=(),
    expect=("pages older than a registered current-state owner they reference: 0",),
    absent=("sources/gamma.md (page",),
)
run_case(
    "current-state-authority-owner-mismatch-fires",
    lambda r: (
        configure_current_state_owner(
            r, "concepts/alpha.md", updated="2026-07-01", status="2026-07-01"
        ),
        add_authority(r, "wiki/concepts/beta.md",
                      "authority_kind: owner-page",
                      "authority_ref: wiki/concepts/alpha.md"),
        write_current_state_registry(r, enabled=True, owners=[]),
    ),
    args=(),
    expect=("owner-page authority references not present in the current-state registry: 1",
            "concepts/beta.md: authority_ref 'wiki/concepts/alpha.md'"),
)
run_case(
    "current-state-status-drift-adjudication-is-directional",
    lambda r: (
        configure_current_state_owner(
            r, "concepts/alpha.md", updated="2026-07-01", status="2026-07-01"
        ),
        edit(r, "wiki/concepts/delta-one.md", "[[alpha]]", "[[beta]]"),
        append(r, "wiki/concepts/beta.md", "\n- Related: [[alpha]]\n"),
        write_adjudications(r, reviewed_status_drift=[{
            "pair": ["concepts/beta.md", "concepts/alpha.md"],
            "reason": "fixture",
        }]),
    ),
    args=(),
    expect=("pages older than a registered current-state owner they reference: 0",
            "adjudicated, suppressed via scripts/lint-adjudications.json: 1"),
)
run_case(
    "current-state-reversed-adjudication-does-not-suppress",
    lambda r: (
        configure_current_state_owner(
            r, "concepts/alpha.md", updated="2026-07-01", status="2026-07-01"
        ),
        edit(r, "wiki/concepts/delta-one.md", "[[alpha]]", "[[beta]]"),
        append(r, "wiki/concepts/beta.md", "\n- Related: [[alpha]]\n"),
        write_adjudications(r, reviewed_status_drift=[{
            "pair": ["concepts/alpha.md", "concepts/beta.md"],
            "reason": "reversed fixture",
        }]),
    ),
    args=(),
    expect=("pages older than a registered current-state owner they reference: 1",
            "concepts/beta.md (page 2026-06-01) -> concepts/alpha.md"),
)
run_case(
    "current-state-markdown-link-drives-drift",
    lambda r: (
        configure_current_state_owner(
            r, "concepts/alpha.md", updated="2026-07-01", status="2026-07-01"
        ),
        edit(r, "wiki/concepts/delta-one.md", "[[alpha]]", "[[beta]]"),
        append(r, "wiki/concepts/beta.md", "\n- [Current owner](alpha.md)\n"),
    ),
    args=(),
    expect=("pages older than a registered current-state owner they reference: 1",
            "concepts/beta.md (page 2026-06-01) -> concepts/alpha.md"),
)

# ---- Tier 1: each check fires on a seeded violation ----
run_case(
    "filename-nonkebab-fires",
    lambda r: shutil.copy(r / "wiki/concepts/alpha.md", r / "wiki/concepts/Bad_Name.md"),
    expect_code=1, expect=("filename", "not kebab-case"),
)
run_case(
    "filename-date-prefix-fires",
    lambda r: shutil.copy(r / "wiki/concepts/alpha.md", r / "wiki/concepts/2026-06-01-alpha.md"),
    expect_code=1, expect=("filename", "has date prefix"),
)
run_case(
    "missing-frontmatter-key-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md", "tags: [fixture]\n", ""),
    expect_code=1, expect=("frontmatter", "missing keys: tags"),
)
run_case(
    "type-folder-mismatch-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md", "type: concept", "type: source"),
    expect_code=1, expect=("type", "folder type 'concept'"),
)
run_case(
    "invalid-confidence-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md", "confidence: medium", "confidence: certain"),
    expect_code=1, expect=("confidence", "invalid value 'certain'"),
)
run_case(
    "malformed-date-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md", "created: 2026-06-01", "created: 2026/06/01"),
    expect_code=1, expect=("date", "created '2026/06/01'"),
)
run_case(
    "invalid-source-type-fires",
    lambda r: edit(r, "wiki/sources/gamma.md", "source_type: other", "source_type: invalid"),
    expect_code=1, expect=("source-type", "invalid value 'invalid'"),
)
run_case(
    "source-type-on-non-source-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md", "agent_use_cases:", "source_type: other\nagent_use_cases:"),
    expect_code=1, expect=("source-type", "source_type set on non-source page"),
)
run_case(
    "index-missing-fires",
    lambda r: edit(r, "wiki/index.md", "| [alpha.md](concepts/alpha.md) | Test concept alpha |\n", ""),
    expect_code=1, expect=("index-missing", "concepts/alpha.md"),
)
run_case(
    "index-stale-fires",
    lambda r: append(r, "wiki/index.md", "| [missing.md](concepts/missing.md) | stale fixture |\n"),
    expect_code=1, expect=("index-stale", "concepts/missing.md"),
)
run_case(
    "non-utf8-index-fails-cleanly",
    lambda r: (r / "wiki" / "index.md").write_bytes(b"\xff"),
    expect_code=1, expect=("index", "not valid UTF-8"),
)
run_case(
    "related-label-fires",
    lambda r: append(r, "wiki/concepts/alpha.md", "- Causes: [[delta-one]]\n"),
    expect_code=1, expect=("related-label", "'Causes:'"),
)
run_case(
    "confidence-restate-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md", "confidence: medium", "confidence: low"),
    expect_code=1, expect=("confidence-restate", "not restated in body"),
)
run_case(
    "confidence-restate-satisfied",
    lambda r: (
        edit(r, "wiki/concepts/alpha.md", "confidence: medium", "confidence: low"),
        edit(r, "wiki/concepts/alpha.md", "Alpha body text",
             "Confidence is low; fixture restatement. Alpha body text"),
    ),
)
run_case(
    "contested-needs-disagreement",
    lambda r: (
        edit(r, "wiki/concepts/alpha.md", "confidence: medium", "confidence: contested"),
        edit(r, "wiki/concepts/alpha.md", "Alpha body text",
             "Confidence is contested. Alpha body text"),
    ),
    expect_code=1, expect=("confidence-restate", "Disagreement"),
)
run_case(
    "dangling-link-fires",
    lambda r: append(r, "wiki/concepts/alpha.md", "- [[no-such-page]]\n"),
    expect_code=1, expect=("dangling-link",),
)
run_case(
    "synthesis-as-source-frontmatter-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   'sources: ["experience: lint eval fixture"]',
                   'sources: ["experience: lint eval fixture", "[[synthesis]]"]'),
    expect_code=1, expect=("synthesis-as-source", "sources: cites the synthesis ledger"),
)
run_case(
    "synthesis-as-source-bare-slug-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   'sources: ["experience: lint eval fixture"]',
                   'sources: ["experience: lint eval fixture", "synthesis"]'),
    expect_code=1, expect=("synthesis-as-source", "source-ref"),
)
run_case(
    "synthesis-as-source-body-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   "Alpha body text for the lint eval fixture.",
                   "Alpha body text for the lint eval fixture (source: [[synthesis]])."),
    expect_code=1, expect=("synthesis-as-source", "body cites [[synthesis]] as a source"),
)
run_case(
    "synthesis-link-not-as-source-allowed",
    lambda r: (
        edit(r, "wiki/concepts/alpha.md",
             "Alpha body text for the lint eval fixture.",
             "Alpha body text for the lint eval fixture near [[synthesis]], "
             "with a syntax example `(source: [[synthesis]])` in code."),
        append(r, "wiki/concepts/alpha.md", "- Related: [[synthesis]]\n"),
    ),
    expect_code=0, absent=("synthesis-as-source",),
)
run_case(
    # content:links#2 + #3: a [[link]] written as a syntax example inside an
    # inline code span on an ENTITY page must not be reported dangling, matching
    # the meta-page behavior. Reverting the code-span strip in the Tier-1
    # dangling scan turns this into a [dangling-link] failure (exit 1).
    "in-code-span-link-not-dangling",
    lambda r: append(r, "wiki/concepts/alpha.md",
                     "\nLink syntax example: `[[some-undefined-demo-page]]`.\n"),
    expect_code=0, absent=("some-undefined-demo-page",),
)
run_case(
    "rich-code-links-not-dangling",
    lambda r: append(
        r,
        "wiki/concepts/alpha.md",
        "\nDouble ``[[double-code-decoy]]``.\n"
        "~~~\n[[tilde-code-decoy]]\n~~~\n"
        "````python\n``` inner literal\n[[four-code-decoy]]\n````\n",
    ),
    expect_code=0,
    absent=("double-code-decoy", "tilde-code-decoy", "four-code-decoy"),
)
run_case(
    "uppercase-generated-backlinks-not-dangling",
    lambda r: append(
        r,
        "wiki/concepts/alpha.md",
        "\n## REFERENCED BY ###\n\n[[generated-dangling-decoy]]\n",
    ),
    expect_code=0,
    absent=("generated-dangling-decoy",),
)
run_case(
    # code:lint#4: a raw/ token inside a non-sources frontmatter field (here a
    # title) must NOT be existence-checked as a provenance ref. Reverting the
    # sources-scoped scan reintroduces a spurious (source-ref) failure.
    "raw-token-in-title-not-source-ref",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   'title: "Alpha"',
                   'title: "How to use raw/data pipelines"'),
    expect_code=0, absent=("source-ref",),
)
run_case(
    "source-url-containing-raw-segment-is-not-repo-path",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [https://example.test/raw/records/remote.pdf]",
    ),
    expect_code=0,
    absent=("source-ref",),
)
run_case(
    "prefixed-absolute-raw-path-fires",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [/raw/notes/real.md]",
    ),
    expect_code=1,
    expect=("source-ref", "unsafe raw repository path expression"),
)
run_case(
    "uri-raw-path-fires",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [file:raw/notes/real.md]",
    ),
    expect_code=1,
    expect=("source-ref", "unsafe raw repository path expression"),
)
run_case(
    "windows-raw-path-fires",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        r"sources: [C:\raw\notes\real.md]",
    ),
    expect_code=1,
    expect=("source-ref", "unsafe raw repository path expression"),
)
run_case(
    "nul-prefixed-raw-path-fires",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [\x00raw/notes/real.md]",
    ),
    expect_code=1,
    expect=("source-ref", "unsafe raw repository path expression"),
)
run_case(
    "explicit-wiki-source-ref-passes",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [wiki/sources/gamma.md]",
    ),
)
run_case(
    "traversing-wiki-source-ref-fires",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [wiki/sources/../../outside.md]",
    ),
    expect_code=1,
    expect=("source-ref", "wiki/sources/../../outside.md", "unsafe"),
)
run_case(
    "uri-wiki-source-ref-fires",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [file:wiki/sources/gamma.md]",
    ),
    expect_code=1,
    expect=("source-ref", "unsafe wiki repository path expression"),
)
run_case(
    "generic-traversing-source-ref-fires",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [../outside]",
    ),
    expect_code=1,
    expect=("source-ref", "unsafe provenance path expression"),
)
run_case(
    # code:lint#3: a prose bullet of the form "- Word: ..." with NO wikilink in
    # a Related pages section is permitted (page-to-create / descriptive prose).
    # Reverting the "[[ in line" guard makes this a (related-label) failure.
    "related-label-prose-bullet-allowed",
    lambda r: append(r, "wiki/concepts/alpha.md", "- Background: context, no link\n"),
    expect_code=0, absent=("related-label",),
)
run_case(
    # code:lint#3 companion: a "- Word: [[link]]" bullet with a non-vocabulary
    # label DOES still fire, so the guard narrows scope without disarming.
    "related-label-with-link-still-fires",
    lambda r: append(r, "wiki/concepts/alpha.md", "- Causes: [[delta-one]] context\n"),
    expect_code=1, expect=("related-label", "'Causes:'"),
)
run_case(
    # content:contradictions#2: a bare-slug source ref that names no
    # wiki/sources/ page (a typo'd citation) is a Tier-1 source-ref failure.
    "bare-slug-source-ref-typo-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   'sources: ["experience: lint eval fixture"]',
                   'sources: [gamma-typo-not-a-real-source]'),
    expect_code=1, expect=("source-ref", "matches no wiki/sources/ page"),
)
run_case(
    # content:contradictions#2 companion: a bare-slug ref that DOES name a real
    # source page passes, and an experience: entry is never treated as a slug.
    "bare-slug-source-ref-resolves-passes",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   'sources: ["experience: lint eval fixture"]',
                   'sources: [gamma]'),
    expect_code=0, absent=("source-ref",),
)
run_case(
    "empty-agent-use-cases-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   "agent_use_cases:\n  - lint eval fixture", "agent_use_cases:"),
    expect_code=1, expect=("frontmatter", "agent_use_cases has no list items"),
)
run_case(
    "impossible-review-by-date-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md", "confidence: medium",
                   "confidence: medium\nreview_by: 2026-13-99"),
    expect_code=1, expect=("date", "real calendar date"),
)
run_case(
    "invalid-authority-kind-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: stale-source"),
    expect_code=1, expect=("authority-field-values", "authority_kind 'stale-source'"),
)
run_case(
    "invalid-authority-freshness-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: none",
                            "authority_freshness: always-fresh"),
    expect_code=1, expect=("authority-field-values",
                           "authority_freshness 'always-fresh'"),
)
run_case(
    "nonboolean-verify-before-action-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: none",
                            "verify_before_action: yes"),
    expect_code=1, expect=("authority-field-values",
                           "verify_before_action must be true or false"),
)
run_case(
    "malformed-last-verified-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: none",
                            "last_verified: 2026/07/04"),
    expect_code=1, expect=("authority-field-values",
                           "last_verified '2026/07/04'"),
)
run_case(
    "authority-field-without-kind-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_ref: wiki/sources/gamma.md"),
    expect_code=1, expect=("authority-kind-anchor",
                           "authority metadata present without authority_kind"),
)
run_case(
    "authority-ref-required-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: source-page"),
    expect_code=1, expect=("authority-ref-required",
                           "authority_ref required"),
)
run_case(
    "authority-raw-source-missing-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: raw-source",
                            "authority_ref: raw/notes/missing-authority.md"),
    expect_code=1, expect=("authority-ref-shape",
                           "raw/notes/missing-authority.md"),
)
run_case(
    "authority-source-page-traversal-fires",
    lambda r: (
        (r / "outside.md").write_text("outside fixture"),
        add_authority(
            r,
            "wiki/concepts/alpha.md",
            "authority_kind: source-page",
            "authority_ref: wiki/sources/../../outside.md",
        ),
    ),
    expect_code=1,
    expect=("authority-ref-shape", "contained existing wiki/sources"),
)
run_case(
    "external-url-authority-must-be-one-url",
    lambda r: add_authority(
        r,
        "wiki/concepts/alpha.md",
        "authority_kind: external-url",
        "authority_ref: https://example.test raw/../outside.md",
    ),
    expect_code=1,
    expect=("authority-ref-shape", "exactly one http:// or https:// URL"),
)
run_case(
    "mixed-authority-traversal-fires",
    lambda r: add_authority(
        r,
        "wiki/concepts/alpha.md",
        "authority_kind: mixed",
        "authority_ref: raw/../outside.md",
    ),
    expect_code=1,
    expect=("authority-ref-shape", "mixed authority_ref", "unsafe repository path"),
)
run_case(
    "source-url-plus-unsafe-path-fires",
    lambda r: edit(
        r,
        "wiki/concepts/alpha.md",
        'sources: ["experience: lint eval fixture"]',
        "sources: [https://example.test raw/../outside.md]",
    ),
    expect_code=1,
    expect=("source-ref", "raw/../outside.md"),
)
run_case(
    "source-ref-traversal-fires",
    lambda r: (
        (r / "outside.md").write_text("outside fixture"),
        edit(
            r,
            "wiki/concepts/alpha.md",
            'sources: ["experience: lint eval fixture"]',
            "sources: [raw/../outside.md]",
        ),
    ),
    expect_code=1,
    expect=("source-ref", "raw/../outside.md"),
)
run_case(
    "source-page-current-state-authority-fires",
    lambda r: (
        (r / "raw" / "notes").mkdir(parents=True),
        (r / "raw" / "notes" / "source-authority.md").write_text("raw fixture"),
        add_authority(r, "wiki/sources/gamma.md",
                      "authority_kind: raw-source",
                      "authority_ref: raw/notes/source-authority.md",
                      "authority_freshness: current-state"),
    ),
    expect_code=1, expect=("source-page-authority",
                           "authority_freshness to immutable-source"),
)
run_case(
    "predictive-authority-without-review-by-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: source-page",
                            "authority_ref: wiki/sources/gamma.md",
                            "authority_freshness: predictive"),
    expect_code=1, expect=("predictive-review-enrollment",
                           "requires review_by"),
)
run_case(
    "authority-none-with-ref-fires",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: none",
                            "authority_ref: wiki/sources/gamma.md"),
    expect_code=1, expect=("authority-ref-shape",
                           "authority_kind 'none'"),
)
run_case(
    "valid-source-page-authority-passes",
    lambda r: (
        (r / "raw" / "notes").mkdir(parents=True),
        (r / "raw" / "notes" / "source-authority.md").write_text("raw fixture"),
        add_authority(r, "wiki/sources/gamma.md",
                      "authority_kind: raw-source",
                      "authority_ref: raw/notes/source-authority.md"),
    ),
)
run_case(
    "valid-owner-page-authority-passes",
    lambda r: add_authority(r, "wiki/concepts/alpha.md",
                            "authority_kind: owner-page",
                            "authority_ref: wiki/concepts/beta.md",
                            "verify_before_action: true"),
)
run_case(
    "adjudication-stale-fires",
    lambda r: write_adjudications(r, accepted_orphans=[
        {"page": "sources/renamed-away.md", "reason": "x", "date": "2026-06-11"}]),
    expect_code=1, expect=("adjudication-stale", "renamed-away"),
)
run_case(
    "adjudication-stale-fires-reviewed-authority-missing",
    lambda r: write_adjudications(r, reviewed_authority_missing=[
        {"page": "concepts/renamed-authority.md", "reason": "x",
         "date": "2026-07-04"}]),
    expect_code=1, expect=("adjudication-stale", "renamed-authority"),
)
run_case(
    # reviewed_quotes carries a 'page' field like the other entity-page keys, so a
    # stale entry pointing at a renamed/deleted page must also fail loudly rather
    # than keep silently suppressing.
    "adjudication-stale-fires-reviewed-quotes",
    lambda r: write_adjudications(r, reviewed_quotes=[
        {"page": "concepts/renamed-quote-page.md", "quote": "x", "reason": "y",
         "date": "2026-06-11"}]),
    expect_code=1, expect=("adjudication-stale", "renamed-quote-page"),
)
run_case(
    "recompile-adjudication-stale-fires",
    lambda r: write_adjudications(r, reviewed_recompile_candidates=[
        {"pair": ["concepts/renamed-away.md", "sources/gamma.md"],
         "reason": "fixture", "date": "2026-06-26"}]),
    expect_code=1, expect=("adjudication-stale", "renamed-away"),
)
run_case(
    "recompile-adjudication-source-shape-fires",
    lambda r: write_adjudications(r, reviewed_recompile_candidates=[
        {"pair": ["concepts/alpha.md", "concepts/beta.md"],
         "reason": "fixture", "date": "2026-06-26"}]),
    expect_code=1, expect=("adjudication-stale", "source page must be under sources/"),
)
run_case(
    "recompile-adjudication-compiled-shape-fires",
    lambda r: write_adjudications(r, reviewed_recompile_candidates=[
        {"pair": ["sources/gamma.md", "sources/gamma.md"],
         "reason": "fixture", "date": "2026-06-26"}]),
    expect_code=1, expect=("adjudication-stale",
                           "compiled page must not be under sources/"),
)
run_case(
    "non-utf8-page-fails-cleanly",
    lambda r: (r / "wiki/concepts/alpha.md").write_bytes(b"---\ntitle: x\n---\n\xff\xfe"),
    expect_code=1, expect=("encoding", "not valid UTF-8"),
)
run_case(
    "non-utf8-glossary-fails-cleanly",
    lambda r: (r / "wiki" / "glossary.md").write_bytes(b"# Glossary\n\n\xff"),
    expect_code=1, expect=("glossary", "not valid UTF-8"),
)
run_case(
    "malformed-adjudication-json-fails-cleanly",
    lambda r: (r / "scripts/lint-adjudications.json").write_text("{not json"),
    expect_code=1, expect=("adjudication-file", "unreadable JSON"),
)
run_case(
    # A suppression filed under a misspelled category key would silently
    # detach; an unknown top-level key is a Tier-1 adjudication-file failure.
    "adjudication-unknown-key-fails-cleanly",
    lambda r: (r / "scripts/lint-adjudications.json").write_text(
        '{"accepted_orphanz": []}'),
    expect_code=1, expect=("adjudication-file", "unknown top-level"),
)
run_case(
    # Underscore-prefixed keys are documentation metadata, not categories.
    "adjudication-metadata-key-allowed",
    lambda r: (r / "scripts/lint-adjudications.json").write_text(
        '{"_description": "fixture", "accepted_orphans": []}'),
    expect_code=0, absent=("unknown top-level",),
)
run_case(
    # An undecodable log.md must fail the header guard loudly instead of
    # silently disarming the rotate_log cut-point protection.
    "non-utf8-log-fails-header-guard",
    lambda r: (r / "wiki" / "log.md").write_bytes(b"# Log\n\n\xff\xfe## garbage\n"),
    expect_code=1, expect=("log-entry-header", "not valid UTF-8"),
)
run_case(
    "misshapen-adjudication-entry-fails-cleanly",
    lambda r: (r / "scripts/lint-adjudications.json").write_text(
        '{"accepted_orphans": [{"reason": "no page key"}]}'),
    expect_code=1, expect=("adjudication-file", "string 'page'"),
)
run_case(
    "duplicate-stem-fires",
    lambda r: (
        shutil.copy(r / "wiki/concepts/delta-three.md", r / "wiki/sources/delta-three.md"),
        edit(r, "wiki/sources/delta-three.md", "type: concept", "type: source\nsource_type: other"),
        append(r, "wiki/index.md", "| [delta-three.md](sources/delta-three.md) | dup stem |\n"),
    ),
    expect_code=1, expect=("duplicate-stem",),
)
run_case(
    "missing-raw-source-ref-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   'sources: ["experience: lint eval fixture"]',
                   'sources: [raw/notes/does-not-exist.md]'),
    expect_code=1, expect=("source-ref", "does-not-exist"),
)
run_case(
    "resolving-raw-source-ref-passes",
    lambda r: (
        (r / "raw" / "notes").mkdir(parents=True),
        (r / "raw" / "notes" / "real.md").write_text("raw fixture"),
        edit(r, "wiki/concepts/alpha.md",
             'sources: ["experience: lint eval fixture"]',
             'sources: [raw/notes/real.md]'),
    ),
)
run_case(
    "resolving-raw-directory-marker-passes",
    lambda r: (
        (r / "raw" / "notes" / "record-folder").mkdir(parents=True),
        edit(
            r,
            "wiki/concepts/alpha.md",
            'sources: ["experience: lint eval fixture"]',
            "sources: [raw/notes/record-folder/]",
        ),
    ),
)
run_case(
    # Block-style sources: lists get the same provenance checks as inline
    # lists: a missing raw/ ref on an indented '- item' line must fire.
    "block-style-missing-raw-source-ref-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   'sources: ["experience: lint eval fixture"]',
                   'sources:\n  - raw/notes/does-not-exist.md'),
    expect_code=1, expect=("source-ref", "does-not-exist"),
)
run_case(
    # Companion: block-style refs that resolve (a real raw path, a real source
    # slug, and free-text provenance) pass without source-ref noise.
    "block-style-source-refs-resolve-passes",
    lambda r: (
        (r / "raw" / "notes").mkdir(parents=True),
        (r / "raw" / "notes" / "real.md").write_text("raw fixture"),
        edit(r, "wiki/concepts/alpha.md",
             'sources: ["experience: lint eval fixture"]',
             'sources:\n  - raw/notes/real.md\n  - gamma\n'
             '  - "experience: block-style fixture"'),
    ),
)
run_case(
    # A typo'd bare slug on a block-style line is caught like an inline one.
    "block-style-bare-slug-typo-fires",
    lambda r: edit(r, "wiki/concepts/alpha.md",
                   'sources: ["experience: lint eval fixture"]',
                   'sources:\n  - gamma-typo-not-a-real-source'),
    expect_code=1, expect=("source-ref", "matches no wiki/sources/ page"),
)
run_case(
    "unexpected-root-file-fires",
    lambda r: (r / "loose.txt").write_text("loose root file"),
    expect_code=1, expect=("repo-structure", "unexpected top-level file"),
)
run_case(
    # code:eval-lint#2: the directory branch of the repo-structure check was
    # never proven. An unknown top-level directory is a Tier-1 failure.
    "unexpected-root-dir-fires",
    lambda r: (r / "notabucket").mkdir(),
    expect_code=1, expect=("repo-structure", "unexpected top-level directory"),
)


def seed_nonclean_transaction(root):
    page = root / "wiki/concepts/alpha.md"
    content = page.read_bytes()
    try:
        run_transaction(
            root,
            consumer="rebuild-referenced-by",
            outputs={"wiki/concepts/alpha.md": content + b"\nchanged\n"},
            expected_preimages={"wiki/concepts/alpha.md": content},
            allowed_prefixes=("wiki",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_prepared_publish" else None,
        )
    except RuntimeError:
        pass


run_case(
    "nonclean-transaction-state-fails-tier1",
    seed_nonclean_transaction,
    expect_code=1,
    expect=("transaction-state", "PREPARED"),
)
run_case(
    "empty-transaction-authority-passes-tier1",
    lambda root: (root / ".wiki-transactions").mkdir(mode=0o700),
)
run_case(
    "unknown-transaction-authority-entry-fails-tier1",
    lambda root: (
        (root / ".wiki-transactions").mkdir(mode=0o700),
        (root / ".wiki-transactions/unknown").write_text("x", encoding="utf-8"),
    ),
    expect_code=1,
    expect=("transaction-state", "unknown authority entry"),
)
run_case(
    "unexpected-wiki-folder-fires",
    lambda r: (r / "wiki" / "misc").mkdir(),
    expect_code=1, expect=("wiki-structure", "unexpected wiki/ folder"),
)
run_case(
    "nested-wiki-page-fires",
    lambda r: (
        (r / "wiki/concepts/nested").mkdir(),
        (r / "wiki/concepts/nested/deep.md").write_text("# hidden\n"),
    ),
    expect_code=1, expect=("wiki-structure", "wiki/concepts/nested", "direct directory"),
    absent=("nested/deep.md",),
)
run_case(
    # code:eval-lint#2: the file branch of the wiki-structure check was never
    # proven. A stray non-allowed file directly under wiki/ is a Tier-1 failure.
    "stray-wiki-root-file-fires",
    lambda r: (r / "wiki" / "notes.txt").write_text("stray wiki root file"),
    expect_code=1, expect=("wiki-structure", "unexpected wiki/ root file"),
)
run_case(
    # code:eval-lint#1: the entity-folder check (unknown wiki subfolder) had no
    # firing case. A page under a folder absent from FOLDER_TYPE fires.
    "unknown-entity-folder-fires",
    lambda r: (
        (r / "wiki" / "misc").mkdir(),
        shutil.copy(r / "wiki/concepts/alpha.md", r / "wiki/misc/alpha.md"),
    ),
    expect_code=1, expect=("entity-folder", "unknown folder 'misc'"),
)
run_case(
    # code:eval-lint#1: the missing/malformed-frontmatter branch (a body-only
    # page with no --- block) had no firing case.
    "body-only-page-fires",
    lambda r: (r / "wiki/concepts/alpha.md").write_text("Just a body, no frontmatter.\n"),
    expect_code=1, expect=("frontmatter", "missing or malformed"),
)
run_case(
    "junk-frontmatter-close-fails-cleanly",
    lambda r: edit(r, "wiki/concepts/alpha.md", "---\n\nAlpha body", "---junk\n\nAlpha body"),
    expect_code=1,
    expect=("frontmatter", "missing an exact closing"),
)
run_case(
    "junk-frontmatter-full-lint-fails-cleanly",
    lambda r: edit(r, "wiki/concepts/alpha.md", "---\n\nAlpha body", "---junk\n\nAlpha body"),
    args=(),
    expect_code=1,
    expect=("frontmatter", "missing an exact closing"),
    absent=("Traceback",),
)
run_case(
    # code:eval-lint#1: corrupt raw-buckets.json (the integrity branch) had no
    # firing case. A raw/ tree plus unparseable taxonomy is a Tier-1 failure.
    "corrupt-raw-buckets-fires",
    lambda r: (
        (r / "raw" / "notes").mkdir(parents=True),
        (r / "raw" / "notes" / ".gitkeep").write_text(""),
        (r / "scripts" / "raw-buckets.json").write_text("{not valid json"),
    ),
    expect_code=1, expect=("raw-buckets", "unreadable JSON"),
)
run_case(
    # code:eval-lint#1: wrong-shape raw-buckets.json (buckets not an object).
    "wrong-shape-raw-buckets-fires",
    lambda r: (
        (r / "raw" / "notes").mkdir(parents=True),
        (r / "raw" / "notes" / ".gitkeep").write_text(""),
        (r / "scripts" / "raw-buckets.json").write_text(
            '{"description": "fixture", "buckets": ["notes"]}'
        ),
    ),
    expect_code=1, expect=("raw-buckets", "must contain a 'buckets' object"),
)
run_case(
    "loose-raw-file-fires",
    lambda r: (
        (r / "raw").mkdir(),
        (r / "raw" / "source.pdf").write_text("loose source artifact"),
    ),
    expect_code=1, expect=("raw-structure", "loose raw/ file"),
)
run_case(
    "unknown-raw-bucket-fires",
    lambda r: (r / "raw" / "misc").mkdir(parents=True),
    expect_code=1, expect=("raw-structure", "missing from scripts/raw-buckets.json"),
)
run_case(
    "raw-folder-nonkebab-fires",
    lambda r: (
        (r / "raw" / "BadBucket").mkdir(parents=True),
    ),
    expect_code=1, expect=("raw-structure", "raw/ folder is not kebab-case"),
)
run_case(
    # The tracked .gitkeep placeholder is exempt; any other loose file fires.
    "loose-deliverable-fires",
    lambda r: (
        (r / "deliverables").mkdir(),
        (r / "deliverables" / ".gitkeep").write_text(""),
        (r / "deliverables" / "model.xlsx").write_text("loose deliverable"),
    ),
    expect_code=1, expect=("deliverables-structure", "loose deliverable"),
    absent=(".gitkeep",),
)
run_case(
    "deliverables-folder-nonkebab-fires",
    lambda r: (
        (r / "deliverables" / "Bad Folder").mkdir(parents=True),
    ),
    expect_code=1, expect=("deliverables-structure", "deliverables/ subfolder is not kebab-case"),
)
run_case(
    "finder-metadata-fires",
    lambda r: (r / "wiki" / ".DS_Store").write_text("metadata"),
    expect_code=1, expect=("os-metadata", ".DS_Store"),
)
run_case(
    # A standalone </content> line is a stray agent tool-call artifact that leaks
    # into a page during ingest Write/Edit. Removing check_stray_tool_tags stops
    # this firing.
    "stray-content-tag-fires",
    lambda r: append(r, "wiki/concepts/alpha.md", "\n</content>\n"),
    expect_code=1, expect=("stray-tag", "</content>"),
)
run_case(
    # The <parameter ...> opening tag is matched by prefix, not exact string,
    # because it carries attributes. This exercises the startswith branch.
    "stray-parameter-tag-fires",
    lambda r: append(r, "wiki/concepts/alpha.md", '\n<parameter name="content">x\n'),
    expect_code=1, expect=("stray-tag", "<parameter"),
)
run_case(
    # Negative/precision: a sentence that merely mentions the tag (the
    # whole-line-equals / startswith guard) must NOT fire, matching the real
    # wiki/log.md prose that records a prior cleanup. Reverting the standalone-only
    # match would turn this into a spurious stray-tag failure.
    "stray-tag-in-prose-does-not-fire",
    lambda r: append(r, "wiki/concepts/alpha.md",
                     "\nThe 2026-06-10 sweep removed two stray </content> "
                     "ingestion artifacts from the corpus.\n"),
    expect_code=0, absent=("stray-tag",),
)

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
run_case(
    "orphan-and-crossref-surface",
    None, args=(),
    expect=("sources/gamma.md",
            "concepts/alpha.md  +  concepts/beta.md"),
)
run_case(
    "crossref-both-source-pages-skipped",
    lambda r: (add_source_profile(r, "source-one"),
               add_source_profile(r, "source-two")),
    args=(), absent=("sources/source-one.md  +  sources/source-two.md",),
)
run_case(
    "crossref-mixed-source-nonsource-still-fires",
    lambda r: add_source_profile(r, "source-profile"),
    args=(), expect=("concepts/alpha.md  +  sources/source-profile.md",),
)
run_case(
    "crossref-nonsource-control-still-fires",
    None,
    args=(), expect=("concepts/alpha.md  +  concepts/beta.md",),
)
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
    "crossref-pair-suppressed",
    lambda r: write_adjudications(r, skipped_crossref_pairs=[
        {"pair": ["concepts/alpha.md", "concepts/beta.md"], "reason": "fixture", "date": "2026-06-11"}]),
    args=(), absent=("concepts/alpha.md  +  concepts/beta.md",),
)
run_case(
    "hub-page-suppresses-pairs",
    lambda r: write_adjudications(r, hub_pages=[
        {"page": "concepts/alpha.md", "reason": "fixture", "date": "2026-06-11"}]),
    args=(), absent=("concepts/alpha.md  +  concepts/beta.md",),
)
run_case(
    "missing-adjudication-file-degrades-gracefully",
    lambda r: (r / "scripts" / "lint-adjudications.json").unlink(),
    args=(), expect=("sources/gamma.md",),
)
run_case(
    "low-overlap-pair-not-reported",
    # diluting alpha's link profile with meta-page links drops Jaccard below 0.5
    lambda r: append(r, "wiki/concepts/alpha.md",
                     "- [[log]]\n- [[glossary]]\n- [[overview]]\n- [[primer]]\n"),
    args=(), absent=("concepts/alpha.md  +  concepts/beta.md",),
)

# ---- Tier 2: positive cases for categories that previously had none ----
# Shared body text long enough to push two derived pages over the 0.35 Jaccard
# near-duplicate bar (the token set must overlap heavily).
NEAR_DUP_BODY = (
    "Capital allocation strategy across diversified portfolio assets requires "
    "balancing concentrated thesis positions against broad index exposure while "
    "managing sequence risk, liquidity buffers, taxable rebalancing thresholds, "
    "and withdrawal timing throughout the accumulation and decumulation phases."
)
run_case(
    # code:eval-lint#3: near-duplicate category had no firing case. Two derived
    # (non-source) concept pages sharing the same dense body exceed the Jaccard
    # bar and surface as a near-duplicate pair.
    "near-duplicate-pair-surfaces",
    lambda r: (
        edit(r, "wiki/concepts/delta-one.md", "Delta one body.", NEAR_DUP_BODY),
        edit(r, "wiki/concepts/delta-two.md", "Delta two body.", NEAR_DUP_BODY),
    ),
    args=(), expect=("concepts/delta-one.md", "concepts/delta-two.md", "jaccard"),
)
run_case(
    # code:eval-lint#3: confidence_upgrade category had no firing case. A
    # low-confidence non-source page with >=2 inbound links is flagged as an
    # upgrade candidate. delta-one already has inbound from alpha and delta-three.
    "confidence-upgrade-surfaces",
    lambda r: (
        edit(r, "wiki/concepts/delta-one.md", "confidence: medium", "confidence: low"),
        edit(r, "wiki/concepts/delta-one.md", "Delta one body.",
             "Delta one body. Confidence is low here for the fixture."),
    ),
    args=(), expect=("confidence:low with >=2 inbound", "concepts/delta-one.md (3 inbound)"),
)
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
    # reviewed_near_duplicates suppression path had no case.
    "near-duplicate-suppressed",
    lambda r: (
        edit(r, "wiki/concepts/delta-one.md", "Delta one body.", NEAR_DUP_BODY),
        edit(r, "wiki/concepts/delta-two.md", "Delta two body.", NEAR_DUP_BODY),
        write_adjudications(r, reviewed_near_duplicates=[
            {"pair": ["concepts/delta-one.md", "concepts/delta-two.md"],
             "reason": "fixture", "date": "2026-06-11"}]),
    ),
    args=(), expect=("suppressed",),
    absent=("concepts/delta-one.md  ~  concepts/delta-two.md",),
)
run_case(
    # reviewed_confidence_low suppression path had no case.
    "confidence-upgrade-suppressed",
    lambda r: (
        edit(r, "wiki/concepts/delta-one.md", "confidence: medium", "confidence: low"),
        edit(r, "wiki/concepts/delta-one.md", "Delta one body.",
             "Delta one body. Confidence is low here for the fixture."),
        write_adjudications(r, reviewed_confidence_low=[
            {"page": "concepts/delta-one.md", "reason": "fixture", "date": "2026-06-11"}]),
    ),
    args=(), expect=("suppressed",), absent=("concepts/delta-one.md (3 inbound)",),
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
run_case(
    # hub_pages suppresses event-driven candidates that can legitimately go
    # quiet between events; it is excluded from the dead-entry report.
    "adjudication-dead-skips-hub-pages",
    lambda r: write_adjudications(
        r,
        hub_pages=[{"page": "concepts/alpha.md", "reason": "fixture",
                    "date": "2026-06-11"}],
    ),
    args=(), absent=("hub_pages: concepts/alpha.md",),
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


def write_sourcing_queue(root, *markers):
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

# ---- Tier 1: index-row uniqueness ----
run_case(
    "index-duplicate-row-fails-tier1",
    lambda r: add_index_row(r, "concepts/alpha.md", "duplicate row"),
    expect_code=1, expect=("index-duplicate", "multiple index.md rows"),
)

# ---- Tier 1: log entry headers (the grammar rotate_log.py cuts at) ----
def write_log_text(root, text):
    (root / "wiki" / "log.md").write_text(text)


run_case(
    "log-entry-header-bad-heading-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-06-01] ingest | ok\nBody.\n\n## Random Section\nBody.\n",
    ),
    expect_code=1, expect=("log-entry-header", "not a recognized log entry header"),
)
run_case(
    "log-entry-header-valid-forms-pass-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-06-01] ingest | ok\nBody.\n\n## 2026-06-02 | plain form\nBody.\n",
    ),
)
run_case(
    # rotate_log's cuts are fence-unaware, so ANY fenced '## ' line in log.md
    # is a hazard: a fenced date-shaped header would become a bogus cut point.
    "log-entry-header-fenced-line-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-06-01] ingest | ok\nBody.\n\n"
        "```\n## [2026-06-02] fenced example\n```\n",
    ),
    expect_code=1, expect=("log-entry-header", "fenced '## ' line"),
)

# ---- Tier 1: structured stale-text sweep proof on new ingest log entries ----
run_case(
    "stale-sweep-impossible-log-date-fails-cleanly",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-06-31] ingest | fixture source\n"
        "Stale-text sweep: status=completed; "
        "commands=[\"rg -n -i -- 'old wording' wiki/\"]; "
        "hit_count=0; pages_fixed=[]; historical_no_change_hits=[]\n",
    ),
    expect_code=1, expect=("stale-sweep-proof", "real calendar date"),
)
run_case(
    "stale-sweep-completed-proof-passes-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-05] ingest | fixture source\n"
        "Stale-text sweep: status=completed; "
        "commands=[\"rg -n -i -- 'old wording' wiki/\"]; "
        "hit_count=0; pages_fixed=[]; historical_no_change_hits=[]\n",
    ),
)
run_case(
    "stale-sweep-not-applicable-proof-passes-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-05] ingest | fixture source\n"
        'Stale-text sweep: status=not_applicable; '
        'reason="source did not resolve an open current-state claim"\n',
    ),
)
run_case(
    "stale-sweep-missing-hit-count-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-05] ingest | fixture source\n"
        "Stale-text sweep: status=completed; "
        "commands=[\"rg -n -i -- 'old wording' wiki/\"]; "
        "pages_fixed=[]; historical_no_change_hits=[]\n",
    ),
    expect_code=1,
    expect=("stale-sweep-proof", "missing field(s): hit_count"),
)
run_case(
    "stale-sweep-malformed-json-array-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-05] ingest | fixture source\n"
        "Stale-text sweep: status=completed; commands=[rg -n -i old wiki/]; "
        "hit_count=1; pages_fixed=[]; historical_no_change_hits=[]\n",
    ),
    expect_code=1,
    expect=("stale-sweep-proof", "commands must be a JSON array of strings"),
)
run_case(
    "stale-sweep-non-rg-command-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-05] ingest | fixture source\n"
        "Stale-text sweep: status=completed; "
        "commands=[\"echo stale sweep passed\"]; hit_count=0; "
        "pages_fixed=[]; historical_no_change_hits=[]\n",
    ),
    expect_code=1,
    expect=("stale-sweep-proof", "commands entries must be rg evidence"),
)
run_case(
    "stale-sweep-wrong-root-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-05] ingest | fixture source\n"
        "Stale-text sweep: status=completed; "
        "commands=[\"rg -n -i -- 'old wording' raw\"]; hit_count=0; "
        "pages_fixed=[]; historical_no_change_hits=[]\n",
    ),
    expect_code=1,
    expect=("stale-sweep-proof", "commands entries must search the wiki root"),
)
run_case(
    "stale-sweep-extra-rg-flag-fails-tier1",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-05] ingest | fixture source\n"
        "Stale-text sweep: status=completed; "
        "commands=[\"rg -n -i -g '!*' -- 'old wording' wiki\"]; hit_count=0; "
        "pages_fixed=[]; historical_no_change_hits=[]\n",
    ),
    expect_code=1,
    expect=("stale-sweep-proof", "commands entries must use exactly -n -i"),
)
run_case(
    "stale-sweep-old-pre-cutoff-ingest-ignored",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-04] ingest | fixture source\nBody.\n",
    ),
)
run_case(
    "stale-sweep-non-ingest-log-entry-ignored",
    lambda r: write_log_text(
        r,
        "# Log\n\n## [2026-07-05] maintenance | fixture pass\nBody.\n",
    ),
)

# ---- Tier 2: review_by enrollment for decisions ----
# A dense body (>=80 authored words) plus an inbound link from alpha keep the
# seeded decision out of the thin and orphan listings, so its only appearance in
# lint output is the enrollment signal. That isolation is what lets the negative
# case assert the page vanishes entirely once review_by is set.
DECISION_BODY = (
    "This fixture decision exists to exercise the review_by enrollment signal. It "
    "carries a deliberately dense body so it clears the thin-page threshold and "
    "its only appearance in lint output comes from the enrollment check rather "
    "than the orphan or thin listings. The decision describes a dated choice whose "
    "realized outcome should eventually be graded against what actually happened "
    "instead of standing on self-assessed confidence forever, which is exactly "
    "the population the outcome-review loop is meant to enroll and surface for "
    "periodic grading by a human reviewer working the maintenance review task."
)


def seed_decision_without_review_by(root):
    (root / "wiki" / "decisions").mkdir(exist_ok=True)
    (root / "wiki" / "decisions" / "target.md").write_text(
        '---\ntitle: "Target"\ntype: decision\ncreated: 2026-06-01\nupdated: 2026-06-01\n'
        'sources: ["experience: lint eval fixture"]\ntags: [fixture]\nconfidence: medium\n'
        'agent_use_cases:\n  - lint eval fixture\n---\n\n'
        f'{DECISION_BODY}\n\n'
        '## Open questions / gaps\n\n- Fixture page; no real questions.\n')
    append(root, "wiki/index.md", "| [target.md](decisions/target.md) | fixture decision |\n")
    append(root, "wiki/concepts/alpha.md", "- Related: [[target]]\n")


run_case(
    "review-by-missing-fires",
    seed_decision_without_review_by,
    args=(), expect_code=0,
    expect=("with no review_by", "decisions/target.md"),
)
run_case(
    "review-by-present-not-flagged",
    lambda r: (
        seed_decision_without_review_by(r),
        edit(r, "wiki/decisions/target.md", "confidence: medium",
             "confidence: medium\nauthority_kind: none\nreview_by: 2026-12-31"),
    ),
    args=(), expect_code=0,
    absent=("decisions/target.md",),
)


def seed_goal_without_review_by(root):
    (root / "wiki" / "goals").mkdir(exist_ok=True)
    (root / "wiki" / "goals" / "target-goal.md").write_text(
        '---\ntitle: "Target Goal"\ntype: goal\ncreated: 2026-06-01\nupdated: 2026-06-01\n'
        'sources: ["experience: lint eval fixture"]\ntags: [fixture]\nconfidence: medium\n'
        'agent_use_cases:\n  - lint eval fixture\n---\n\n'
        f'{DECISION_BODY}\n\n'
        '## Open questions / gaps\n\n- Fixture page; no real questions.\n')
    append(root, "wiki/index.md", "| [target-goal.md](goals/target-goal.md) | fixture goal |\n")
    append(root, "wiki/concepts/alpha.md", "- Related: [[target-goal]]\n")


run_case(
    "goal-review-by-missing-fires",
    seed_goal_without_review_by,
    args=(), expect_code=0,
    expect=("goals and decisions with no review_by", "goals/target-goal.md"),
)
run_case(
    "goal-review-by-present-not-flagged",
    lambda r: (
        seed_goal_without_review_by(r),
        edit(r, "wiki/goals/target-goal.md", "confidence: medium",
             "confidence: medium\nauthority_kind: none\nreview_by: 2026-12-31"),
    ),
    args=(), expect_code=0,
    absent=("goals/target-goal.md",),
)


def configure_fixture_domain(root, active_types):
    lines = [
        "---", "title: Domain Config", "type: domain", "created: 2026-06-01",
        "updated: 2026-06-01", "status: configured",
    ]
    lines.append("entity_types_active:")
    lines.extend(f"  - {value}" for value in active_types)
    lines.extend(("raw_buckets: []", "example_queries: []", "---", "", "# Domain Config", ""))
    (root / "wiki" / "domain.md").write_text("\n".join(lines))


run_case(
    "configured-layout-drift-fails-tier1",
    lambda r: configure_fixture_domain(r, ("source",)),
    expect_code=1,
    expect=("entity-configuration", "inactive entity folders present: concepts"),
)
# ---- Tier 1: meta-page dangling links (promoted from Tier-2; gates commit) ----
run_case(
    "meta-dangling-link-fires",
    lambda r: append(r, "wiki/index.md", "\nSee [[no-such-meta-target]] for details.\n"),
    expect_code=1, expect=("meta-dangling-link", "index.md: [[no-such-meta-target]]"),
)
run_case(
    "meta-dangling-ignores-folder-and-code",
    lambda r: append(r, "wiki/index.md", "\nRouting: [[concepts/]]. Example: `[[demo]]`.\n"),
    expect_code=0, absent=("index.md: [[concepts/]]", "index.md: [[demo]]"),
)
run_case(
    # content:links#3: an in-code-span [[link]] on a META page must not fire
    # even when its target is a real-looking but nonexistent slug.
    "meta-dangling-in-code-span-ignored",
    lambda r: append(r, "wiki/index.md",
                     "\nSyntax example: `[[some-undefined-meta-demo]]`.\n"),
    expect_code=0, absent=("some-undefined-meta-demo",),
)
run_case(
    "meta-dangling-rich-code-ignored",
    lambda r: append(
        r,
        "wiki/index.md",
        "\nDouble ``[[double-meta-decoy]]``.\n"
        "~~~\n[[tilde-meta-decoy]]\n~~~\n"
        "````python\n``` inner literal\n[[four-meta-decoy]]\n````\n",
    ),
    expect_code=0,
    absent=("double-meta-decoy", "tilde-meta-decoy", "four-meta-decoy"),
)

# ---- Phase 5: fail-closed structure and governed Tier-1 data ----
run_case(
    "direct-entity-junk-file-fails",
    lambda r: (r / "wiki/concepts/illegal.bin").write_bytes(b"junk"),
    expect_code=1,
    expect=("wiki-structure", "wiki/concepts/illegal.bin", "non-.md"),
    absent=("Traceback",),
)
run_case(
    "empty-direct-entity-directory-fails",
    lambda r: (r / "wiki/concepts/nested").mkdir(),
    expect_code=1,
    expect=("wiki-structure", "wiki/concepts/nested", "directory"),
    absent=("Traceback",),
)
run_case(
    "direct-entity-broken-symlink-fails",
    lambda r: (r / "wiki/concepts/escape.md").symlink_to(r / "missing-target.md"),
    args=(),
    expect_code=1,
    expect=("wiki-structure", "wiki/concepts/escape.md", "special entry"),
    absent=("Traceback",),
)
run_case(
    "direct-entity-directory-symlink-fails",
    lambda r: (r / "wiki/concepts/directory-link.md").symlink_to(
        r / "wiki/concepts", target_is_directory=True
    ),
    args=(),
    expect_code=1,
    expect=("wiki-structure", "wiki/concepts/directory-link.md", "special entry"),
    absent=("Traceback",),
)

for case_name, registry, marker in (
    ("raw-buckets-list-top-level-fails", [], "top level must be a JSON object"),
    ("raw-buckets-empty-object-fails", {}, "nonempty string 'description'"),
    (
        "raw-buckets-empty-buckets-fails",
        {"description": "fixture", "buckets": {}},
        "'buckets' must be a nonempty object",
    ),
    (
        "raw-buckets-bad-key-fails",
        {"description": "fixture", "buckets": {"Bad Bucket": "fixture"}},
        "bucket key 'Bad Bucket' is not kebab-case",
    ),
    (
        "raw-buckets-blank-description-fails",
        {"description": "  ", "buckets": {"notes": "fixture"}},
        "nonempty string 'description'",
    ),
    (
        "raw-buckets-blank-bucket-description-fails",
        {"description": "fixture", "buckets": {"notes": "  "}},
        "bucket 'notes' needs a nonempty string description",
    ),
):
    run_case(
        case_name,
        lambda r, value=registry: write_raw_buckets(r, value),
        expect_code=1,
        expect=("raw-buckets", marker),
        absent=("Traceback",),
    )

for page, field in (
    ("wiki/concepts/alpha.md", "title"),
    ("wiki/concepts/alpha.md", "type"),
    ("wiki/concepts/alpha.md", "created"),
    ("wiki/concepts/alpha.md", "updated"),
    ("wiki/concepts/alpha.md", "confidence"),
    ("wiki/sources/gamma.md", "source_type"),
):
    for suffix, replacement in (("blank", ""), ("quote-only", "''")):
        run_case(
            f"required-{field}-{suffix}-fails",
            lambda r, rel=page, key=field, value=replacement: edit(
                r, rel, next(
                    line for line in (r / rel).read_text().splitlines()
                    if line.startswith(f"{key}:")
                ), f"{key}: {value}"
            ),
            expect_code=1,
            expect=("frontmatter", f"{field} must be a nonempty scalar"),
            absent=("Traceback",),
        )

for meta_name in sorted(META_PAGES):
    run_case(
        f"non-utf8-meta-{meta_name.lower()}-fails-cleanly",
        lambda r, name=meta_name: (r / "wiki" / f"{name}.md").write_bytes(b"\xff"),
        expect_code=1,
        expect=("meta-encoding", f"wiki/{meta_name}.md", "not valid UTF-8"),
        absent=("Traceback",),
    )

run_case(
    "sourcing-marker-duplicate-attribute-fails",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts folder=sources count=5 -->"
    ),
    expect_code=1,
    expect=("sourcing-queue-count-marker", "duplicate attribute 'folder'"),
    absent=("Traceback",),
)
run_case(
    "sourcing-marker-unknown-attribute-fails",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts count=5 extra=yes -->"
    ),
    expect_code=1,
    expect=("sourcing-queue-count-marker", "unknown attribute 'extra'"),
    absent=("Traceback",),
)
run_case(
    "sourcing-marker-unparsed-attribute-text-fails",
    lambda r: write_sourcing_queue(
        r, "<!-- lint:entity-count folder=concepts stray count=5 -->"
    ),
    expect_code=1,
    expect=("sourcing-queue-count-marker", "malformed attribute text"),
    absent=("Traceback",),
)

LONG_QUOTE_PREFIX = (
    "This deliberately long shared quote prefix contains enough normalized words "
    "and characters to extend well beyond the former eighty character identity boundary"
)
LONG_QUOTE_ONE = LONG_QUOTE_PREFIX + " before ending with the first distinct conclusion."
LONG_QUOTE_TWO = LONG_QUOTE_PREFIX + " before ending with the second distinct conclusion."


def seed_long_quote_identity(root):
    edit(
        root,
        "wiki/concepts/beta.md",
        "Beta body text for the lint eval fixture.",
        f'Beta body text for the lint eval fixture. "{LONG_QUOTE_ONE}" '
        f'(source: [[gamma]])\n\n"{LONG_QUOTE_TWO}" (source: [[gamma]])',
    )
    write_adjudications(root, reviewed_quotes=[{
        "page": "concepts/beta.md",
        "quote": LONG_QUOTE_ONE,
        "reason": "fixture full-identity suppression",
        "date": "2026-07-11",
    }])


run_case(
    "long-quotes-sharing-eighty-character-prefix-stay-distinct",
    seed_long_quote_identity,
    args=(),
    expect_code=0,
    expect=(
        "quote mismatches (quoted text not verbatim in cited source): 1",
        "adjudicated, suppressed via scripts/lint-adjudications.json: 1",
    ),
    absent=("adjudication_dead", "Traceback"),
)


def check_raw_artifact_git_workflow_passes():
    """A raw source can be tracked and pass both repository guard commands."""
    real_git = shutil.which("git")
    if real_git is None:
        fail_prerequisite(
            "raw-artifact-git-workflow-passes", "git prerequisite unavailable"
        )
        return
    with tempfile.TemporaryDirectory(prefix="wiki-raw-tracking-") as td:
        root = Path(td)
        copy_fixture(root)
        shutil.copyfile(REPO_ROOT / ".gitignore", root / ".gitignore")
        (root / "scripts/hooks").mkdir()
        for name in (
            "wiki_transactions.py", "_file_transactions.py",
            "_transaction_contract.py", "_durable_files.py",
            "wiki_provenance.py", "wiki_lint_frontmatter.py",
            "wiki_lint_contract.py", "wiki_entity_catalog.py",
            "_wiki_parse.py", "_repo_paths.py",
        ):
            shutil.copyfile(REPO_ROOT / "scripts" / name, root / "scripts" / name)
        shutil.copyfile(
            REPO_ROOT / "scripts/entity-catalog.json",
            root / "scripts/entity-catalog.json",
        )
        shutil.copyfile(
            REPO_ROOT / "scripts/hooks/pre-commit", root / "scripts/hooks/pre-commit"
        )
        source = root / "raw/notes/source.txt"
        source.parent.mkdir(parents=True)
        source_bytes = b"tracked source artifact\n"
        source.write_bytes(source_bytes)
        (root / "wiki/sources/tracked-source.md").write_text(
            "---\ntitle: Tracked source\ntype: source\n"
            "created: 2026-08-22\nupdated: 2026-08-22\n"
            "sources: [\"raw/notes/source.txt\"]\ntags: [fixture]\n"
            "confidence: high\nsource_type: other\n"
            "agent_use_cases:\n  - raw tracking eval\n---\n\nTracked source.\n",
            encoding="utf-8",
        )
        append(
            root, "wiki/index.md",
            "| [tracked-source.md](sources/tracked-source.md) | Tracked source fixture |\n",
        )
        (root / "scripts/raw-artifacts.json").write_text(
            json.dumps({
                "artifacts": [{
                    "captured_at": "2026-08-22",
                    "files": [{
                        "path": "raw/notes/source.txt",
                        "sha256": hashlib.sha256(source_bytes).hexdigest(),
                        "size": len(source_bytes),
                    }],
                    "source_slug": "tracked-source",
                }],
                "schema_version": 1,
            }, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        subprocess.run([real_git, "init", "-q"], cwd=root, check=True, capture_output=True)
        add = subprocess.run(
            [real_git, "add", "-A"], cwd=root, text=True, capture_output=True
        )
        tracked = subprocess.run(
            [real_git, "ls-files", "--error-unmatch", "raw/notes/source.txt"],
            cwd=root, text=True, capture_output=True,
        )
        lint = subprocess.run(
            [sys.executable, str(LINT), "--tier1"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        hook = subprocess.run(
            ["sh", "scripts/hooks/pre-commit"],
            cwd=root, text=True, capture_output=True,
        )
        ok = (
            add.returncode == 0
            and tracked.returncode == 0
            and lint.returncode == 0
            and hook.returncode == 0
        )
        name = "raw-artifact-git-workflow-passes"
        results.append((name, ok))
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            print(
                f"  add={add.returncode} tracked={tracked.returncode} "
                f"lint={lint.returncode} hook={hook.returncode}; "
                f"stderr={(add.stderr + tracked.stderr + lint.stderr + hook.stderr)[:500]}"
            )


check_raw_artifact_git_workflow_passes()

print()
failed = [n for n, ok in results if not ok]
print(f"Summary: {len(results) - len(failed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
