#!/usr/bin/env python3
"""Ordered deterministic checks for one parsed wiki page."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from _repo_paths import EXISTING_FILE, RepoPathError, is_http_url, resolve_repo_path
from _wiki_parse import dangling_slugs, evidentiary_view, section_body, split_frontmatter, strip_sections
from wiki_lint_contract import (
    AUTHORITY_ANCHOR_FIELDS,
    AUTHORITY_METADATA_FIELDS,
    BASE_KEYS,
    DATE_PREFIX_RE,
    DATE_RE,
    FOLDER_TYPE,
    KEBAB_RE,
    LintFailures,
    PageContext,
    RELATED_LABELS,
    ROOT_ALLOWED_DIRS,
    ROOT_ALLOWED_FILES,
    Tier1Check,
    VALID_AUTHORITY_FRESHNESS,
    VALID_AUTHORITY_KIND,
    VALID_CONFIDENCE,
    VALID_SOURCE_TYPE,
    WIKI_ROOT,
)
from wiki_lint_frontmatter import (
    authored_body,
    block_list_has_items,
    fm_scalar,
    is_nonrepository_source_reference,
    source_items,
    source_repo_references,
)


def check_filename(ctx: PageContext) -> LintFailures:
    """Filenames are kebab-case with no date prefix (chronology lives in log.md)."""
    fails = []
    if not KEBAB_RE.match(ctx.stem):
        fails.append(("filename", ctx.rel, "not kebab-case"))
    if DATE_PREFIX_RE.match(ctx.stem):
        fails.append(("filename", ctx.rel, "has date prefix"))
    return fails


def check_entity_folder(ctx: PageContext) -> LintFailures:
    """Every entity page sits in a known entity-type folder."""
    if ctx.folder is not None and ctx.folder not in FOLDER_TYPE:
        return [("entity-folder", ctx.rel, f"unknown folder '{ctx.folder}'")]
    return []


def check_required_keys(ctx: PageContext) -> LintFailures:
    """Required frontmatter keys are present, and agent_use_cases (non-sources)
    carries real list items rather than a bare header."""
    fails = []
    required = set(BASE_KEYS)
    if ctx.folder == "sources":
        required.add("source_type")
    if ctx.folder != "sources":
        required.add("agent_use_cases")
    missing = sorted(required - set(ctx.fm))
    if missing:
        fails.append(("frontmatter", ctx.rel, "missing keys: " + ", ".join(missing)))

    required_scalars = {"title", "type", "created", "updated", "confidence"}
    if ctx.folder == "sources":
        required_scalars.add("source_type")
    for key in sorted(required_scalars & set(ctx.fm)):
        if not fm_scalar(ctx.fm[key]):
            fails.append(("frontmatter", ctx.rel,
                          f"{key} must be a nonempty scalar"))

    # agent_use_cases must carry list items, not just the bare key. Use the
    # shared ctx.fm_block (frontmatter_block) the context already computed rather
    # than re-splitting ctx.text, so this check cannot diverge from it.
    if "agent_use_cases" in required and "agent_use_cases" in ctx.fm:
        if not block_list_has_items(ctx.fm_block, "agent_use_cases"):
            fails.append(("frontmatter", ctx.rel, "agent_use_cases has no list items"))
    return fails


def check_type_matches_folder(ctx: PageContext) -> LintFailures:
    """frontmatter type matches the folder it lives in."""
    expected = FOLDER_TYPE.get(ctx.folder)
    if "type" in ctx.fm and expected and ctx.fm["type"] != expected:
        return [("type", ctx.rel, f"type '{ctx.fm['type']}' != folder type '{expected}'")]
    return []


def check_confidence_value(ctx: PageContext) -> LintFailures:
    """confidence is one of the allowed values."""
    if ctx.fm.get("confidence") and ctx.fm["confidence"] not in VALID_CONFIDENCE:
        return [("confidence", ctx.rel, f"invalid value '{ctx.fm['confidence']}'")]
    return []


def check_source_type_placement(ctx: PageContext) -> LintFailures:
    """source_type is a valid value on sources, and absent elsewhere."""
    if ctx.folder == "sources":
        st = ctx.fm.get("source_type")
        if st and st not in VALID_SOURCE_TYPE:
            return [("source-type", ctx.rel, f"invalid value '{st}'")]
        return []
    if "source_type" in ctx.fm:
        return [("source-type", ctx.rel, "source_type set on non-source page")]
    return []


def check_dates(ctx: PageContext) -> LintFailures:
    """created/updated/review_by are real YYYY-MM-DD calendar dates.

    review_by is optional; it opts a page into the review loop. Validating the
    value is a real calendar date (not just digit-shaped) keeps lint and
    review_due.py in agreement on what is valid."""
    fails = []
    for k in ("created", "updated", "review_by"):
        v = ctx.fm.get(k)
        if not v:
            continue
        if not DATE_RE.match(v):
            fails.append(("date", ctx.rel, f"{k} '{v}' is not YYYY-MM-DD"))
            continue
        try:
            date.fromisoformat(v)
        except ValueError:
            fails.append(("date", ctx.rel, f"{k} '{v}' is not a real calendar date"))
    return fails


def check_authority_field_values(ctx: PageContext) -> LintFailures:
    """Authority metadata fields use accepted scalar values and dates."""
    fails = []
    kind = fm_scalar(ctx.fm.get("authority_kind"))
    if "authority_kind" in ctx.fm and kind not in VALID_AUTHORITY_KIND:
        fails.append(("authority-field-values", ctx.rel,
                      f"authority_kind '{kind}' is not an accepted value"))

    freshness = fm_scalar(ctx.fm.get("authority_freshness"))
    if ("authority_freshness" in ctx.fm
            and freshness not in VALID_AUTHORITY_FRESHNESS):
        fails.append(("authority-field-values", ctx.rel,
                      f"authority_freshness '{freshness}' is not an accepted value"))

    verify = fm_scalar(ctx.fm.get("verify_before_action"))
    if "verify_before_action" in ctx.fm and verify not in {"true", "false"}:
        fails.append(("authority-field-values", ctx.rel,
                      "verify_before_action must be true or false"))

    verified = fm_scalar(ctx.fm.get("last_verified"))
    if "last_verified" in ctx.fm:
        if not DATE_RE.match(verified):
            fails.append(("authority-field-values", ctx.rel,
                          f"last_verified '{verified}' is not YYYY-MM-DD"))
        else:
            try:
                date.fromisoformat(verified)
            except ValueError:
                fails.append(("authority-field-values", ctx.rel,
                              f"last_verified '{verified}' is not a real calendar date"))
    return fails


def check_authority_kind_anchor(ctx: PageContext) -> LintFailures:
    """Any authority-scoped field requires authority_kind as the anchor."""
    present = [k for k in AUTHORITY_ANCHOR_FIELDS if k in ctx.fm]
    if present and "authority_kind" not in ctx.fm:
        return [("authority-kind-anchor", ctx.rel,
                 "authority metadata present without authority_kind: "
                 + ", ".join(present))]
    return []


def check_authority_ref_required(ctx: PageContext) -> LintFailures:
    """authority_kind values other than none require a non-empty authority_ref."""
    kind = fm_scalar(ctx.fm.get("authority_kind"))
    if kind in VALID_AUTHORITY_KIND and kind != "none" and not fm_scalar(ctx.fm.get("authority_ref")):
        return [("authority-ref-required", ctx.rel,
                 f"authority_ref required when authority_kind is '{kind}'")]
    return []


def check_authority_ref_shape(ctx: PageContext) -> LintFailures:
    """authority_ref shape and cheap existence checks by authority_kind."""
    fails = []
    if "authority_kind" not in ctx.fm:
        return fails
    kind = fm_scalar(ctx.fm.get("authority_kind"))
    if kind not in VALID_AUTHORITY_KIND:
        return fails
    ref = fm_scalar(ctx.fm.get("authority_ref"))

    if kind == "none":
        if ref:
            fails.append(("authority-ref-shape", ctx.rel,
                          "authority_kind 'none' requires authority_ref to be absent or empty"))
        return fails
    if not ref:
        return fails  # authority-ref-required reports the missing value.

    def contained(prefixes, *, require_regular_file=True):
        try:
            resolve_repo_path(
                ref,
                repo_root=Path.cwd(),
                allowed_prefixes=prefixes,
                mode=EXISTING_FILE,
                require_regular_file=require_regular_file,
            )
        except RepoPathError:
            return False
        return True

    if kind == "raw-source":
        if not contained(("raw",), require_regular_file=False):
            fails.append(("authority-ref-shape", ctx.rel,
                          f"raw-source authority_ref '{ref}' must be a contained existing raw/ path"))
    elif kind == "source-page":
        if not ref.endswith(".md") or not contained(("wiki/sources",)):
            fails.append(("authority-ref-shape", ctx.rel,
                          f"source-page authority_ref '{ref}' must be a contained existing wiki/sources/*.md file"))
    elif kind == "owner-page":
        if not ref.endswith(".md") or not contained(("wiki",)):
            fails.append(("authority-ref-shape", ctx.rel,
                          f"owner-page authority_ref '{ref}' must be a contained existing wiki/*.md file"))
        elif ref.startswith("wiki/sources/"):
            fails.append(("authority-ref-shape", ctx.rel,
                          f"owner-page authority_ref '{ref}' must not be under wiki/sources/"))
    elif kind == "external-url":
        if not is_http_url(ref):
            fails.append(("authority-ref-shape", ctx.rel,
                          f"external-url authority_ref '{ref}' must be exactly one http:// or https:// URL"))
    elif kind == "local-resource":
        if ref.lower().startswith("source:"):
            return fails
        try:
            resolve_repo_path(
                ref,
                repo_root=Path.cwd(),
                allowed_prefixes=tuple(sorted(ROOT_ALLOWED_DIRS - {".git"})),
                allowed_root_files=ROOT_ALLOWED_FILES,
                mode=EXISTING_FILE,
                require_regular_file=False,
            )
        except RepoPathError:
            fails.append(("authority-ref-shape", ctx.rel,
                          f"local-resource authority_ref '{ref}' must exist under the repo root or start with source:"))
    elif kind == "mixed":
        # Mixed prose stays terminal only when explicitly classified. Any
        # path-shaped value still crosses the shared containment boundary.
        if ref.lower().startswith("source:") or is_http_url(ref):
            return fails
        path_shaped = (
            "/" in ref
            or "\\" in ref
            or ref.startswith((".", "~"))
            or ref in ROOT_ALLOWED_FILES
            or (not any(char.isspace() for char in ref) and Path(ref).suffix)
        )
        if path_shaped:
            try:
                resolve_repo_path(
                    ref,
                    repo_root=Path.cwd(),
                    allowed_prefixes=tuple(sorted(ROOT_ALLOWED_DIRS - {".git"})),
                    allowed_root_files=ROOT_ALLOWED_FILES,
                    mode=EXISTING_FILE,
                    require_regular_file=False,
                )
            except RepoPathError:
                fails.append(("authority-ref-shape", ctx.rel,
                              f"mixed authority_ref '{ref}' is an unsafe repository path"))
    return fails


def check_source_page_authority(ctx: PageContext) -> LintFailures:
    """Source pages with authority metadata stay immutable source summaries."""
    if ctx.folder != "sources" or not any(k in ctx.fm for k in AUTHORITY_METADATA_FIELDS):
        return []
    fails = []
    kind = fm_scalar(ctx.fm.get("authority_kind"))
    if kind in VALID_AUTHORITY_KIND and kind not in {"raw-source", "external-url", "mixed"}:
        fails.append(("source-page-authority", ctx.rel,
                      "source pages with authority metadata must use raw-source, external-url, or mixed"))
    freshness = fm_scalar(ctx.fm.get("authority_freshness"))
    if freshness in VALID_AUTHORITY_FRESHNESS and freshness != "immutable-source":
        fails.append(("source-page-authority", ctx.rel,
                      "source pages may only set authority_freshness to immutable-source"))
    return fails


def check_predictive_review_enrollment(ctx: PageContext) -> LintFailures:
    """Predictive authority metadata must enroll in the review_by loop."""
    if fm_scalar(ctx.fm.get("authority_freshness")) == "predictive" and not ctx.fm.get("review_by"):
        return [("predictive-review-enrollment", ctx.rel,
                 "authority_freshness 'predictive' requires review_by")]
    return []


def check_source_refs(ctx: PageContext) -> LintFailures:
    """Provenance refs in the sources: value must resolve. The scan is scoped to
    the sources line(s), not the whole frontmatter block, so a raw/ token inside
    a title or tag is not treated as a ref (code:lint#4). raw/ paths must exist
    on disk; a bare kebab slug must name a wiki/sources/ page, catching a typo'd
    citation that would otherwise read as cited."""
    fails = []
    if not ctx.fm_block:
        return fails
    for item in source_items(ctx.fm_block):
        if is_nonrepository_source_reference(item):
            continue
        references, errors = source_repo_references(item)
        fails.extend(("source-ref", ctx.rel, error) for error in errors)
        if references or errors:
            continue
        if KEBAB_RE.match(item) and item not in ctx.source_slugs:
            fails.append(("source-ref", ctx.rel,
                          f"source '{item}' matches no wiki/sources/ page"))
        elif not KEBAB_RE.match(item):
            fails.append(("source-ref", ctx.rel,
                          f"unclassified provenance reference: {item!r}"))
    return fails


def check_dangling_links(ctx: PageContext) -> LintFailures:
    """Wikilinks resolve to a real page. Code spans are stripped (a [[link]]
    inside a code example is not a failure); the shared dangling_slugs helper
    keeps this in lockstep with the Tier-2 meta-page dangling check."""
    if ctx.frontmatter_error:
        return []
    return [("dangling-link", ctx.rel, f"[[{slug}]] resolves to nothing")
            for slug in dangling_slugs(ctx.text, ctx.valid_slugs)]


def check_synthesis_not_cited(ctx: PageContext) -> LintFailures:
    """The synthesis ledger is orientation, never provenance: synthesis claims
    cite original pages, not the ledger (the rule wiki/synthesis.md states in
    prose; promoted from the ledger's 2026-06-10 standing question on
    2026-07-09). Flags [[synthesis]] or a bare `synthesis` slug among the
    sources: items, and "(source: [[synthesis]])"-style citations in the
    authored body. A plain [[synthesis]] link stays legal: in the body it is
    orientation, not provenance, and Related pages / Referenced by sit past
    the authored_body cut."""
    fails = []
    if ctx.fm_block:
        for item in source_items(ctx.fm_block):
            if item == "synthesis" or "[[synthesis]]" in item:
                fails.append(("synthesis-as-source", ctx.rel,
                              "sources: cites the synthesis ledger; cite the original pages"))
    scan = evidentiary_view(ctx.text)
    for _ in re.finditer(r"\(sources?:[^)]*\[\[synthesis\]\]", scan, re.I):
        fails.append(("synthesis-as-source", ctx.rel,
                      "body cites [[synthesis]] as a source; cite the original pages"))
    return fails


def check_related_labels(ctx: PageContext) -> LintFailures:
    """Related-pages relationship labels come from the fixed vocabulary
    (RELATED_LABELS here; the meanings table lives in REFERENCES.md). A bullet
    may be untyped ("- [[page]]"), but a "Label:" prefix on a bullet that carries
    a [[link]] must be one of the six labels. A plain prose bullet ("- Note:
    ...", a page-to-create) is permitted by SCHEMA and is not an attempted
    typed label."""
    fails = []
    related = section_body(ctx.text, "Related pages")
    if related is not None:
        for line in related.splitlines():
            lm = re.match(r"^-\s+([A-Za-z][A-Za-z ]*?):\s", line)
            if lm and "[[" in line and lm.group(1) not in RELATED_LABELS:
                fails.append(("related-label", ctx.rel,
                              f"'{lm.group(1)}:' is not an allowed relationship label"))
    return fails


def check_open_questions(ctx: PageContext) -> LintFailures:
    """Non-source pages carry an "Open questions / gaps" section (SCHEMA rule:
    required on every non-source entity type). Sources are exempt; confidence
    already flags preview-only material there. Presence-only and deterministic,
    so it gates like the other structural mandates."""
    if ctx.folder == "sources":
        return []
    if not re.search(r"^##+ Open [Qq]uestions", ctx.text, re.M):
        return [("open-questions", ctx.rel, "missing Open questions / gaps section")]
    return []


def check_confidence_restate(ctx: PageContext) -> LintFailures:
    """low/contested confidence is restated in the body (SCHEMA rule); contested
    pages also need a Disagreement section.

    NOTE: this is a keyword-presence proxy, not a semantic guarantee. It only
    verifies the word "confidence" appears in the authored body; it cannot tell a
    genuine caveat restatement from an incidental mention. True "did the page
    restate its uncertainty" is a judgment call that belongs in the Tier-3 prose
    review, so Tier-1 keeps the cheap proxy."""
    fails = []
    conf = ctx.fm.get("confidence")
    if conf in ("low", "contested"):
        _, body = split_frontmatter(ctx.text)
        ab = authored_body(body)
        if not re.search(r"confidence", ab, re.I):
            fails.append(("confidence-restate", ctx.rel,
                          f"confidence '{conf}' not restated in body"))
        if conf == "contested" and "## Disagreement" not in ab:
            fails.append(("confidence-restate", ctx.rel,
                          "contested page lacks a Disagreement section"))
    return fails


# Per-page Tier-1 checks, in evaluation order. run_tier1_lint() runs each in turn for
# every entity page whose frontmatter parsed. To add a check, write a small
# check_*(ctx) -> fails function above and list it here.
# Path-only checks: they read the path, not the frontmatter dict, so run_tier1_lint()
# runs them before frontmatter parsing and they still fire on pages whose
# frontmatter is missing or malformed. Kept as their own tuple so the
# pre-parse/post-parse split is structural, not a slice-plus-comment.
TIER1_PATH_CHECKS: tuple[Tier1Check, ...] = (
    check_filename,
    check_entity_folder,
)

TIER1_PAGE_CHECKS: tuple[Tier1Check, ...] = (
    check_required_keys,
    check_type_matches_folder,
    check_confidence_value,
    check_source_type_placement,
    check_dates,
    check_authority_field_values,
    check_authority_kind_anchor,
    check_authority_ref_required,
    check_authority_ref_shape,
    check_source_page_authority,
    check_predictive_review_enrollment,
    check_source_refs,
    check_dangling_links,
    check_synthesis_not_cited,
    check_related_labels,
    check_open_questions,
    check_confidence_restate,
)


__all__ = ["TIER1_PAGE_CHECKS", "TIER1_PATH_CHECKS"]
