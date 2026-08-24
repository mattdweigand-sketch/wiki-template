#!/usr/bin/env python3
"""Seeded evals for lint page and baseline hard rules."""

from eval_lint_fixture import *
from _file_transactions import run_transaction

# ---- Tier 1: clean fixture is the control ----
run_case("clean-fixture-passes", None)

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
run_case(
    "legacy-codex-root-fires",
    lambda r: (r / ".codex").mkdir(),
    expect_code=1, expect=("repo-structure", ".codex"),
)


def seed_nonclean_transaction(root):
    page = root / "wiki/concepts/alpha.md"
    content = page.read_bytes()
    try:
        run_transaction(
            root,
            consumer="capture-gate",
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

raise SystemExit(finish_lint_eval())
