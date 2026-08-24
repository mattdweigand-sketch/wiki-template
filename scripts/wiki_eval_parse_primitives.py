#!/usr/bin/env python3
"""Regression eval for shared Markdown parsing primitives.

The shared primitives keep lint, review, and backlink behavior aligned. This
suite tests their parsing behavior directly, including malformed input.

The separate caller suite drives CRLF files through public command behavior.
This file does not inspect caller source code or private import wiring.
"""

from __future__ import annotations

import sys
import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _wiki_parse import (  # noqa: E402  (after sys.path insert)
    FrontmatterError,
    LINK_RE,
    dangling_slugs,
    frontmatter_block,
    split_frontmatter,
    strip_code_spans,
)
from eval_lib import Results  # noqa: E402  (after sys.path insert)

results = Results()
check = results.record


# A CRLF, code-span, aliased-link, block-list edge sample. The on-disk bytes use
# \r\n; callers read it through Path.read_text, which normalizes to \n, so the
# shared parser only ever sees the LF form. We assert both forms explicitly.
CRLF_RAW = (
    "---\r\n"
    "title: edge sample\r\n"
    "type: concept\r\n"
    "tags: [agent, money]\r\n"
    "review_by: 2020-01-01\r\n"
    "---\r\n"
    "Body links [[real-page]] and [[sources/aliased|shown text]].\r\n"
    "A folder pointer [[concepts/]] and an in-code link `[[in-code]]`.\r\n"
    "A fenced one (language tag + an unbalanced stray backtick inside):\r\n"
    "```python\r\n"
    "a stray ` backtick then\r\n"
    "[[fenced-example]]\r\n"
    "```\r\n"
)
LF = CRLF_RAW.replace("\r\n", "\n")

# --- 1. unit assertions on the shared primitives (LF, as callers feed them) ---

fm, body = split_frontmatter(LF)
check("split-frontmatter-keys",
      fm is not None and set(fm) == {"title", "type", "tags", "review_by"},
      detail=f"fm={fm}")
check("split-frontmatter-body-starts-after-fence",
      body.startswith("Body links"), detail=f"body={body[:20]!r}")

# block extraction preserves the raw block (including the bracketed tags list).
block = frontmatter_block(LF)
check("frontmatter-block-preserves-raw",
      "tags: [agent, money]" in block and "review_by: 2020-01-01" in block,
      detail=f"block={block!r}")

try:
    split_frontmatter("---\nstatus: unconfigured\nstatus: configured\n---\n")
except FrontmatterError:
    duplicate_frontmatter_rejected = True
else:
    duplicate_frontmatter_rejected = False
check("duplicate-frontmatter-key-is-rejected", duplicate_frontmatter_rejected)

for quote_case, malformed_value in (
    ("leading", "'configured"),
    ("trailing", "configured'"),
    ("different", "'configured\""),
):
    try:
        split_frontmatter(f"---\nstatus: {malformed_value}\n---\n")
    except FrontmatterError:
        mismatched_quote_rejected = True
    else:
        mismatched_quote_rejected = False
    check(
        f"frontmatter-{quote_case}-mismatched-quote-is-rejected",
        mismatched_quote_rejected,
    )

# LINK_RE captures the bare slug, strips the folder prefix, and drops the alias.
# The folder-pointer link [[concepts/]] is captured verbatim ("concepts/"); the
# trailing slash is what dangling_slugs keys on to skip it.
links = LINK_RE.findall(LF)
check("link-re-captures-and-strips",
      links == ["real-page", "aliased", "concepts/", "in-code", "fenced-example"],
      detail=f"links={links}")

# LINK_RE on a [[slug|alias]] link captures the slug, never the alias. This pins
# alias handling directly (the slug char class excludes | and ], so the alias
# side is never captured).
check("link-re-alias-captures-slug-not-alias",
      LINK_RE.findall("[[real-slug|Shown Alias]]") == ["real-slug"],
      detail=f"alias={LINK_RE.findall('[[real-slug|Shown Alias]]')}")

# strip_code_spans blanks both fenced and inline code. Order matters: fenced
# blocks first, then inline spans. The fenced block carries a language tag and
# an UNBALANCED stray backtick, so the documented fenced-then-inline order is
# load-bearing: scanning inline spans before fenced blocks would let the stray
# backtick mis-pair across the fence and re-expose [[fenced-example]].
stripped = strip_code_spans(LF)
check("strip-code-spans-removes-both",
      "[[in-code]]" not in stripped and "[[fenced-example]]" not in stripped
      and "[[real-page]]" in stripped,
      detail=f"stripped={stripped!r}")
# dangling_slugs ignores in-code/fenced examples and resolves real links.
dangling = dangling_slugs(LF, {"real-page", "aliased"})
check("dangling-skips-code-and-resolves",
      dangling == [], detail=f"dangling={dangling}")
dangling2 = dangling_slugs(LF, {"real-page"})  # 'aliased' unknown now
check("dangling-reports-unresolved",
      dangling2 == ["aliased"], detail=f"dangling2={dangling2}")
# Folder-pointer links ([[concepts/]]) are intentionally never reported dangling,
# even though "concepts/" is not a valid slug: the slug.endswith('/') skip in
# dangling_slugs drops them. Pin that skip directly.
dangling3 = dangling_slugs(LF, {"real-page", "aliased"})
check("dangling-skips-folder-pointer",
      "concepts/" not in dangling3, detail=f"dangling3={dangling3}")

# Raw CRLF is accepted by the line-oriented exact-fence grammar. Callers usually
# normalize it through Path.read_text, but direct users still get the same
# frontmatter instead of a newline-style-dependent result.
fm_raw, _ = split_frontmatter(CRLF_RAW)
check("raw-crlf-parses-consistently",
      fm_raw == fm and "tags: [agent, money]" in frontmatter_block(CRLF_RAW),
      detail=f"fm_raw={fm_raw}")

# --- Phase 2 contract: exact frontmatter, Markdown views, and repo paths ---
#
# These checks intentionally use dynamic discovery so the red run reports the
# missing/weak contract as named failures instead of aborting on the first
# missing symbol. Once the implementation lands, they exercise the same public
# API used by research, lint, the gate, and ledger validation.
parse_module = importlib.import_module("_wiki_parse")

malformed_error = None
try:
    split_frontmatter("---\ntitle: broken\n---junk\nBody\n")
except Exception as exc:  # the contract requires a typed FrontmatterError
    malformed_error = type(exc).__name__
check(
    "frontmatter-junk-close-is-malformed",
    malformed_error == "FrontmatterError",
    detail=f"error={malformed_error!r}",
)
for name, malformed in (
    ("frontmatter-junk-opener-is-malformed", "---junk\ntitle: broken\n---\nBody\n"),
    ("frontmatter-unterminated-is-malformed", "---\ntitle: broken\nBody\n"),
):
    error_name = None
    try:
        split_frontmatter(malformed)
    except Exception as exc:
        error_name = type(exc).__name__
    check(name, error_name == "FrontmatterError", detail=f"error={error_name!r}")

final_fm, final_body = split_frontmatter("---\ntitle: final close\n---")
check(
    "frontmatter-final-exact-close",
    final_fm == {"title": "final close"} and final_body == "",
    detail=f"fm={final_fm!r} body={final_body!r}",
)

rich_code = (
    "Visible [[real-page]].\n"
    "Double ``[[double-hidden]]``.\n"
    "~~~~ text\n[[tilde-hidden]]\n~~~~\n"
    "````python\n``` inner literal\n[[four-hidden]]\n````\n"
)
rich_stripped = strip_code_spans(rich_code)
check(
    "double-backtick-span-hidden",
    "[[real-page]]" in rich_stripped and "[[double-hidden]]" not in rich_stripped,
    detail=rich_stripped.replace("\n", " | "),
)
check(
    "tilde-fence-hidden",
    "[[tilde-hidden]]" not in rich_stripped,
    detail=rich_stripped.replace("\n", " | "),
)
check(
    "four-backtick-fence-with-inner-triple-hidden",
    "[[four-hidden]]" not in rich_stripped,
    detail=rich_stripped.replace("\n", " | "),
)

evidentiary_view = getattr(parse_module, "evidentiary_view", None)
authored_link_view = getattr(parse_module, "authored_link_view", None)
status_review_view = getattr(parse_module, "status_review_view", None)
canonical_authored_text = getattr(parse_module, "canonical_authored_text", None)
views_present = all(
    callable(view)
    for view in (
        evidentiary_view,
        authored_link_view,
        status_review_view,
        canonical_authored_text,
    )
)
check("explicit-markdown-views-present", views_present)

section_sample = (
    "---\ntitle: views\n---\n"
    "Evidence survives.\n"
    "<!-- [[comment-decoy]] hidden evidence -->\n"
    "## RELATED PAGES ###\n[[related-decoy]]\n"
    "### Child heading\nchild remains in section\n"
    "## Next\nNext evidence.\n"
    "## Referenced By ##\n[[generated-decoy]]\n"
)
if views_present:
    evidence = evidentiary_view(section_sample)
    authored = authored_link_view(section_sample)
    status = status_review_view(section_sample)
    canonical = canonical_authored_text(section_sample)
else:
    evidence = authored = status = canonical = ""
check(
    "evidentiary-view-excludes-non-evidence",
    "Evidence survives." in evidence
    and "Next evidence." in evidence
    and "comment-decoy" not in evidence
    and "related-decoy" not in evidence
    and "generated-decoy" not in evidence,
    detail=evidence.replace("\n", " | "),
)
comment_fence_sample = (
    "---\ntitle: comment fence\n---\n"
    "<!--\n```\ncomment fence decoy\n-->\n"
    "Real evidence before links.\n"
    "## Related Pages ##\nrelated quote decoy\n"
)
comment_fence_evidence = evidentiary_view(comment_fence_sample) if views_present else ""
check(
    "html-comment-fence-cannot-hide-link-section",
    "Real evidence before links." in comment_fence_evidence
    and "related quote decoy" not in comment_fence_evidence,
    detail=comment_fence_evidence.replace("\n", " | "),
)
comment_code_context_sample = (
    "<!--\n```\ncomment-only fence literal\n-->\n"
    "Real [[real-page]] and **Status (2026-01-01):** live.\n"
)
comment_code_authored = (
    authored_link_view(comment_code_context_sample) if views_present else ""
)
comment_code_status = (
    status_review_view(comment_code_context_sample) if views_present else ""
)
check(
    "comment-fence-literal-cannot-mask-authored-link-or-status",
    "[[real-page]]" in comment_code_authored
    and "Status (2026-01-01)" in comment_code_status
    and "comment-only fence literal" in comment_code_authored
    and "comment-only fence literal" in comment_code_status,
    detail=f"authored={comment_code_authored!r} status={comment_code_status!r}",
)
fence_comment_sample = (
    "---\ntitle: fence comment\n---\n"
    "```text\n<!-- unclosed comment literal\n```\n"
    "Real evidence after the fence.\n"
    "## Referenced by\n[[generated-after-fence]]\n"
)
fence_comment_evidence = evidentiary_view(fence_comment_sample) if views_present else ""
fence_comment_canonical = canonical_authored_text(fence_comment_sample) if views_present else ""
check(
    "fenced-comment-opener-cannot-hide-authored-tail",
    "Real evidence after the fence." in fence_comment_evidence
    and "generated-after-fence" not in fence_comment_evidence
    and "Real evidence after the fence." in fence_comment_canonical
    and "generated-after-fence" not in fence_comment_canonical,
    detail=(
        f"evidence={fence_comment_evidence!r} "
        f"canonical={fence_comment_canonical!r}"
    ),
)
frontmatter_comment_sample = (
    "---\ntitle: frontmatter comment\nnote: <!-- literal, not a body comment\n---\n"
    "Real body evidence.\n"
    "## Referenced by\n[[generated-after-frontmatter]]\n"
)
frontmatter_comment_evidence = (
    evidentiary_view(frontmatter_comment_sample) if views_present else ""
)
frontmatter_comment_canonical = (
    canonical_authored_text(frontmatter_comment_sample) if views_present else ""
)
check(
    "frontmatter-comment-opener-cannot-hide-body",
    "Real body evidence." in frontmatter_comment_evidence
    and "generated-after-frontmatter" not in frontmatter_comment_evidence
    and "Real body evidence." in frontmatter_comment_canonical
    and "generated-after-frontmatter" not in frontmatter_comment_canonical,
    detail=(
        f"evidence={frontmatter_comment_evidence!r} "
        f"canonical={frontmatter_comment_canonical!r}"
    ),
)
thematic_body_sample = (
    "---\ntitle: thematic body\n---\n"
    "---\n"
    "Real evidence after a body thematic break.\n"
    "## Related pages\n[[related-after-break]]\n"
)
thematic_body_error = None
try:
    thematic_body_evidence = (
        evidentiary_view(thematic_body_sample) if views_present else ""
    )
except Exception as exc:
    thematic_body_evidence = ""
    thematic_body_error = type(exc).__name__
check(
    "body-thematic-break-is-not-second-frontmatter",
    thematic_body_error is None
    and "Real evidence after a body thematic break." in thematic_body_evidence
    and "related-after-break" not in thematic_body_evidence,
    detail=f"error={thematic_body_error!r} evidence={thematic_body_evidence!r}",
)
malformed_section_error = None
if callable(canonical_authored_text):
    try:
        canonical_authored_text(
            "---\ntitle: malformed\n## Referenced by\n[[authored-must-not-be-mutated]]\n"
        )
    except Exception as exc:
        malformed_section_error = type(exc).__name__
check(
    "malformed-frontmatter-blocks-section-rewrite",
    malformed_section_error == "FrontmatterError",
    detail=f"error={malformed_section_error!r}",
)
check(
    "authored-and-status-views-have-distinct-contracts",
    "related-decoy" in authored
    and "generated-decoy" not in authored
    and "related-decoy" in status
    and "generated-decoy" not in status,
    detail=f"authored={authored!r} status={status!r}",
)
check(
    "canonical-authored-removes-generated-only",
    "related-decoy" in canonical
    and "generated-decoy" not in canonical
    and canonical.endswith("\n"),
    detail=canonical.replace("\n", " | "),
)
section_decoys = (
    "---\n## Referenced by\ntitle: frontmatter heading decoy\n---\n"
    "<!--\n## Referenced by\ncomment heading decoy\n-->\n"
    "### Referenced by\nAuthored level-three content survives.\n"
    "Authored tail survives.\n"
)
section_decoy_authored = authored_link_view(section_decoys) if views_present else ""
section_decoy_canonical = canonical_authored_text(section_decoys) if views_present else ""
check(
    "generated-heading-decoys-are-preserved",
    "frontmatter heading decoy" in section_decoy_authored
    and "comment heading decoy" in section_decoy_authored
    and "Authored level-three content survives." in section_decoy_authored
    and "Authored tail survives." in section_decoy_authored
    and section_decoy_canonical == section_decoys,
    detail=f"authored={section_decoy_authored!r} canonical={section_decoy_canonical!r}",
)

raise SystemExit(results.finish())
