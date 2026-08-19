#!/usr/bin/env python3
"""Regression eval for the shared scripts/_wiki_parse.py primitives.

R1 extracted split_frontmatter, frontmatter_block, LINK_RE, the code-span REs,
strip_code_spans, and dangling_slugs into one module so lint.py,
review_due.py, and rebuild_referenced_by.py stop reimplementing them and cannot
silently drift. This suite pins that contract three ways:

1. Unit assertions on the primitives against a CRLF / edge-case sample, so the
   parse grammar (wikilink slug capture, code-span stripping, frontmatter split,
   block-list-preserving block extraction) is locked at the source.
2. An end-to-end consistency check: one CRLF-on-disk page driven through all
   callers, proving they agree. Every caller reads via Path.read_text (universal
   newlines), so a CRLF source is normalized to LF before _wiki_parse sees it,
   and all scripts treat the identical page identically.
3. Wiring assertions that each caller's source actually imports from _wiki_parse,
   so reverting any caller to a private reimplementation fails here.

Regression caught: if any caller is reverted to a private parser, or the shared
grammar is weakened (code-span stripping reordered or dropped, the frontmatter
anchor changed, the alias half of a [[slug|alias]] link captured instead of the
slug, the folder-pointer skip removed), at least one assertion below fails.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import importlib
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _wiki_parse import (  # noqa: E402  (after sys.path insert)
    FENCED_CODE_RE,
    INLINE_CODE_RE,
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
# load-bearing: dropping FENCED_CODE_RE, or swapping to inline-first, leaves the
# stray backtick to mis-pair across the fence and re-expose [[fenced-example]].
stripped = strip_code_spans(LF)
check("strip-code-spans-removes-both",
      "[[in-code]]" not in stripped and "[[fenced-example]]" not in stripped
      and "[[real-page]]" in stripped,
      detail=f"stripped={stripped!r}")
check("code-span-res-present",
      FENCED_CODE_RE.search(LF) is not None and INLINE_CODE_RE.search(LF) is not None)

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

try:
    repo_paths = importlib.import_module("_repo_paths")
except ImportError:
    repo_paths = None
check("shared-repo-path-module-present", repo_paths is not None)

with tempfile.TemporaryDirectory() as td:
    path_root = Path(td) / "repo"
    (path_root / "raw" / "notes").mkdir(parents=True)
    (path_root / "wiki" / "sources").mkdir(parents=True)
    (path_root / "tmp").mkdir()
    (path_root / "AGENTS.md").write_text("agent map", encoding="utf-8")
    (path_root / "raw" / "notes" / "inside.txt").write_text("inside", encoding="utf-8")
    (path_root / "wiki" / "sources" / "inside.md").write_text("inside", encoding="utf-8")
    (path_root / "wiki" / "index.md").write_text("index", encoding="utf-8")
    outside = Path(td) / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (path_root / "raw" / "notes" / "escape.txt").symlink_to(outside)
    (path_root / "raw" / "notes" / "loop-a").symlink_to("loop-b")
    (path_root / "raw" / "notes" / "loop-b").symlink_to("loop-a")
    (path_root / "alias").symlink_to("raw", target_is_directory=True)
    (path_root / "ROOT.md").symlink_to("raw/notes/inside.txt")
    if hasattr(os, "mkfifo"):
        os.mkfifo(path_root / "raw" / "notes" / "pipe")

    path_results: dict[str, object] = {}
    if repo_paths is not None:
        resolve_repo_path = getattr(repo_paths, "resolve_repo_path", None)
        RepoPathError = getattr(repo_paths, "RepoPathError", ValueError)

        def resolve(value: str, prefixes: tuple[str, ...], mode: str = "existing_file"):
            return resolve_repo_path(
                value,
                repo_root=path_root,
                allowed_prefixes=prefixes,
                mode=mode,
            )

        for value in (
            "raw/../outside.txt",
            "wiki/sources/../../outside.md",
            "/absolute.txt",
            "raw\\notes\\inside.txt",
            "https://example.com/source",
            "raw//notes/inside.txt",
            "raw/./notes/inside.txt",
            "raw/notes/escape.txt",
            "raw/notes/loop-a",
        ):
            try:
                resolve(value, ("raw", "wiki/sources"))
            except RepoPathError:
                path_results[value] = "rejected"
            except Exception as exc:
                path_results[value] = type(exc).__name__
            else:
                path_results[value] = "accepted"
        try:
            path_results["valid_raw"] = resolve("raw/notes/inside.txt", ("raw",))
            path_results["valid_wiki"] = resolve("wiki/sources/inside.md", ("wiki/sources",))
            path_results["create"] = resolve(
                "tmp/not-created.md", ("tmp",), mode="may_create_file"
            )
            path_results["exact_root"] = resolve_repo_path(
                "AGENTS.md",
                repo_root=path_root,
                allowed_root_files=("AGENTS.md",),
                mode="existing_file",
            )
            try:
                resolve("wiki/index.md/child.md", ("wiki",), mode="may_create_file")
            except RepoPathError:
                path_results["file_parent_create"] = "rejected"
            else:
                path_results["file_parent_create"] = "accepted"
            try:
                resolve("alias/notes/inside.txt", ("alias",))
            except RepoPathError:
                path_results["symlinked_root"] = "rejected"
            else:
                path_results["symlinked_root"] = "accepted"
            try:
                resolve_repo_path(
                    "ROOT.md",
                    repo_root=path_root,
                    allowed_root_files=("ROOT.md",),
                    mode="existing_file",
                )
            except RepoPathError:
                path_results["symlinked_root_file"] = "rejected"
            else:
                path_results["symlinked_root_file"] = "accepted"
            if hasattr(os, "mkfifo"):
                try:
                    resolve("raw/notes/pipe", ("raw",), mode="may_create_file")
                except RepoPathError:
                    path_results["existing_special_file"] = "rejected"
                else:
                    path_results["existing_special_file"] = "accepted"
            else:
                path_results["existing_special_file"] = "unsupported"
        except Exception as exc:
            path_results["valid_error"] = type(exc).__name__

    unsafe_values = {
        "raw/../outside.txt",
        "wiki/sources/../../outside.md",
        "/absolute.txt",
        "raw\\notes\\inside.txt",
        "https://example.com/source",
        "raw//notes/inside.txt",
        "raw/./notes/inside.txt",
        "raw/notes/escape.txt",
        "raw/notes/loop-a",
    }
    check(
        "repo-path-unsafe-inputs-rejected",
        repo_paths is not None
        and all(path_results.get(value) == "rejected" for value in unsafe_values),
        detail=str(path_results),
    )
    check(
        "repo-path-valid-existing-and-create-modes",
        repo_paths is not None
        and path_results.get("valid_raw") == "raw/notes/inside.txt"
        and path_results.get("valid_wiki") == "wiki/sources/inside.md"
        and path_results.get("create") == "tmp/not-created.md",
        detail=str(path_results),
    )
    check(
        "repo-path-exact-root-file",
        repo_paths is not None and path_results.get("exact_root") == "AGENTS.md",
        detail=str(path_results),
    )
    check(
        "repo-path-create-requires-directory-parent",
        repo_paths is not None and path_results.get("file_parent_create") == "rejected",
        detail=str(path_results),
    )
    check(
        "repo-path-rejects-symlinked-authority-roots",
        repo_paths is not None
        and path_results.get("symlinked_root") == "rejected"
        and path_results.get("symlinked_root_file") == "rejected",
        detail=str(path_results),
    )
    check(
        "repo-path-create-rejects-special-file",
        repo_paths is not None
        and path_results.get("existing_special_file") in {"rejected", "unsupported"},
        detail=str(path_results),
    )

# --- 2. end-to-end: one CRLF page through all four callers, must agree ---

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "wiki"
    (root / "concepts").mkdir(parents=True)
    (root / "sources").mkdir(parents=True)
    # Page under test: written with CRLF bytes on disk.
    page = root / "concepts" / "edge.md"
    page.write_bytes(CRLF_RAW.encode("utf-8"))
    # A real target so the link resolves and an inbound edge can form.
    (root / "sources" / "real-page.md").write_bytes(
        ("---\ntitle: real\ntype: source\ncreated: 2026-01-01\n"
         "updated: 2026-01-01\nsources: []\ntags: [agent]\n"
         "confidence: medium\nsource_type: other\n---\nbody\n").encode("utf-8")
    )

    # review_due: review_by is read from the CRLF page and surfaces as overdue.
    rd = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "review_due.py"),
                         "--root", str(root), "--today", "2026-06-21"],
                        text=True, capture_output=True)
    check("caller-review-due-exits-clean", rd.returncode == 0,
          detail=f"exit={rd.returncode}; stderr={rd.stderr!r}")
    check("caller-review-due-reads-crlf-review-by",
          "concepts/edge.md" in rd.stdout and "1 page(s)" in rd.stdout,
          detail=rd.stdout.replace("\n", " | "))

    # rebuild_referenced_by: the authored [[real-page]] body link from the CRLF
    # page produces an inbound edge on real-page.md, proving the LF-normalized
    # CRLF page is scanned with the shared LINK_RE grammar.
    rebuild = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "rebuild_referenced_by.py")],
        cwd=td, text=True, capture_output=True,
    )
    check("caller-rebuild-exits-clean", rebuild.returncode == 0,
          detail=f"exit={rebuild.returncode}; stderr={rebuild.stderr!r}")
    real_text = (root / "sources" / "real-page.md").read_text(encoding="utf-8")
    check("caller-rebuild-links-crlf-page",
          "## Referenced by" in real_text and "[[edge]]" in real_text,
          detail=real_text)
    # Nothing links to edge.md, so it gets the no-inbound marker. This pins that
    # the [[real-page]]/[[aliased]] links it emits are treated as outbound only.
    edge_text = page.read_text(encoding="utf-8")
    check("caller-rebuild-edge-has-no-inbound",
          "_No inbound links yet._" in edge_text,
          detail=edge_text)

# --- 3. wiring: each caller's source actually imports from _wiki_parse ---
#
# The end-to-end checks above prove the callers BEHAVE identically, but a caller
# reverted to a byte-identical private reimplementation would still pass them.
# Assert the shared import is wired in each caller's source so reverting any one
# of them to a private parser fails here.
CALLERS = ("lint.py", "review_due.py", "rebuild_referenced_by.py")


def has_import_from(path: Path, module: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.ImportFrom) and node.module == module
        for node in ast.walk(tree)
    )


for caller in CALLERS:
    path = REPO_ROOT / "scripts" / caller
    check(f"caller-imports-shared-parser-{caller}",
          has_import_from(path, "_wiki_parse"),
          detail=f"{caller} does not import from _wiki_parse")

decoy_tree = ast.parse("marker = 'from _wiki_parse import split_frontmatter'\n")
check(
    "import-check-rejects-string-decoy",
    not any(
        isinstance(node, ast.ImportFrom) and node.module == "_wiki_parse"
        for node in ast.walk(decoy_tree)
    ),
)

PATH_CALLERS = (
    "wiki_lint_frontmatter.py",
    "wiki_lint_page_checks.py",
    "capture_approval_policy.py",
    "ledger_common.py",
)
for caller in PATH_CALLERS:
    path = REPO_ROOT / "scripts" / caller
    check(
        f"caller-imports-shared-repo-paths-{caller}",
        has_import_from(path, "_repo_paths"),
        detail=f"{caller} does not import from _repo_paths",
    )

for caller in ("wiki_lint_page_checks.py", "wiki_lint_signals.py"):
    src = (REPO_ROOT / "scripts" / caller).read_text(encoding="utf-8")
    check(
        f"caller-uses-shared-markdown-views-{caller}",
        "evidentiary_view" in src or "authored_link_view" in src or "status_review_view" in src,
        detail=f"{caller} does not use an explicit shared Markdown view",
    )

sys.exit(results.finish())
