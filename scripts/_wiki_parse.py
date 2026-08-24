#!/usr/bin/env python3
"""Shared markdown/frontmatter parsing primitives for the wiki scripts.

Single source of truth for the small parse helpers that several scripts used to
reimplement independently (lint.py, review_due.py, rebuild_referenced_by.py).
Keeping them here means the wikilink regex, the code-span stripping, the
frontmatter split, and the dangling-slug resolution cannot silently drift apart
across callers.

Vendor-neutral: stdlib only, no dependencies. Importable as a sibling module by
any scripts/*.py run from the repo root (the script's own directory is on
sys.path[0], exactly as capture_ledger is imported).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

# A wikilink slug, ignoring an optional folder prefix and an optional alias:
#   [[slug]], [[dir/slug]], [[dir/slug|alias]]  -> captures "slug".
LINK_RE = re.compile(r"\[\[(?:[^/\]|]+/)?([^\]|]+?)(?:\|[^\]]+)?\]\]")

# Root-level wiki pages that are catalogs/indexes, not entity pages: never link
# targets and never counted as link sources. Shared so the dangling-link scan,
# the index-coverage check, and the referenced-by rebuild enumerate the corpus
# identically and cannot drift on what counts as a meta page.
META_PAGES = {
    "index", "log", "overview", "glossary", "primer",
    "sourcing-queue", "contradictions", "design-notes", "SCHEMA", "synthesis",
    "domain",
}
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})([^\r\n]*)$")


class FrontmatterError(ValueError):
    """A leading frontmatter opener is malformed or has no exact close."""


@dataclass(frozen=True)
class _FrontmatterParts:
    block: str
    body: str
    end: int

# A wiki/log.md entry header: "## [YYYY-MM-DD] ..." or "## YYYY-MM-DD ...",
# followed by end-of-line, " | description", or a word. Single source of truth
# shared by rotate_log.py (which cuts the log only at these headers) and lint.py
# (which fails any other "## " line in log.md, so a nonconforming header cannot
# be silently merged into the previous entry's archive block at rotation).
LOG_ENTRY_HEADER_RE = re.compile(
    r"^## (?:(?:\[(?P<bracketed>\d{4}-\d{2}-\d{2})\])|"
    r"(?P<plain>\d{4}-\d{2}-\d{2}))"
    r"(?:$| \| (?:(?P<piped>[A-Za-z][\w-]*).*|.+)| (?P<worded>[A-Za-z][\w-]*).*)$"
)


def parse_log_entry_date(line: str) -> str | None:
    """The entry date if `line` is a recognized log entry header, else None."""
    match = LOG_ENTRY_HEADER_RE.match(line.rstrip("\n"))
    if not match:
        return None
    return match.group("bracketed") or match.group("plain")


def parse_log_entry_type(line: str) -> str | None:
    """The lowercased entry-type token from a recognized log entry header, or
    None when the line is not a header or carries no leading type token.
    Handles both live forms — "## [YYYY-MM-DD] type | ..." and
    "## YYYY-MM-DD | type | ..." — through the same LOG_ENTRY_HEADER_RE that
    recognizes headers, so recognition and type extraction cannot drift."""
    match = LOG_ENTRY_HEADER_RE.match(line.rstrip("\n"))
    if not match:
        return None
    token = match.group("piped") or match.group("worded")
    return token.lower() if token else None


def _line_value(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\n", "\r")):
        return line[:-1]
    return line


def _leading_frontmatter(text: str) -> _FrontmatterParts | None:
    """Return the one exact leading frontmatter region, if present."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return None
    first = _line_value(lines[0])
    if first != "---":
        if first.startswith("---"):
            raise FrontmatterError("leading frontmatter opener must be exactly '---'")
        return None

    offset = len(lines[0])
    for line in lines[1:]:
        if _line_value(line) == "---":
            block = text[len(lines[0]):offset]
            if block.endswith("\r\n"):
                block = block[:-2]
            elif block.endswith(("\n", "\r")):
                block = block[:-1]
            end = offset + len(line)
            return _FrontmatterParts(block=block, body=text[end:], end=end)
        offset += len(line)
    raise FrontmatterError("leading frontmatter is missing an exact closing '---' line")


def split_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    """Return (frontmatter_dict_of_toplevel_keys, body_text). Empty dict if none.

    Returns (None, text) when there is no parseable leading --- fence block.
    Block-style list values are flattened to '' (the key is present with an
    empty scalar); use frontmatter_block() when you need the raw block text.
    """
    parts = _leading_frontmatter(text)
    if parts is None:
        return None, text
    fm_block, body = parts.block, parts.body
    fm = {}
    for line in fm_block.splitlines():
        km = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$", line)
        if km:
            key = km.group(1)
            if key in fm:
                raise FrontmatterError(f"duplicate frontmatter key: {key}")
            fm[key] = km.group(2).strip()
    return fm, body


def frontmatter_block(text: str) -> str:
    """Return the raw frontmatter block (text between the leading --- fences),
    or '' if there is none. Unlike split_frontmatter, this preserves block-style
    list values that the key parser flattens, so checks that scan raw lines
    (raw/ refs, source slugs, tags) see the real content."""
    parts = _leading_frontmatter(text)
    return parts.block if parts is not None else ""


def _mask_range(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if chars[index] not in "\r\n":
            chars[index] = "\x00"


def _line_end(text: str, start: int) -> int:
    newline = text.find("\n", start)
    return len(text) if newline < 0 else newline + 1


def _context_mask(
    text: str, *, frontmatter: str = "preserve", mask_comments: bool
) -> str:
    """Mask code with one context-aware grammar.

    ``frontmatter`` is ``preserve`` (skip it without interpreting literals),
    ``mask`` (also blank it), or ``none`` (the caller already supplied a body).
    Comments are always skipped as scanner context and may be preserved or
    masked independently. This prevents fences/comments/frontmatter literals
    from changing how later authored text is parsed.
    """
    if frontmatter not in {"preserve", "mask", "none"}:
        raise ValueError(f"unsupported frontmatter mode: {frontmatter}")
    chars = list(text)
    start = 0
    if frontmatter != "none":
        parts = _leading_frontmatter(text)
        if parts is not None:
            if frontmatter == "mask":
                _mask_range(chars, 0, parts.end)
            start = parts.end

    index = start
    fence: tuple[str, int] | None = None
    while index < len(text):
        at_line_start = index == 0 or text[index - 1] == "\n"
        if fence is not None:
            end = _line_end(text, index)
            value = _line_value(text[index:end])
            char, length = fence
            if re.fullmatch(rf"[ \t]{{0,3}}{re.escape(char)}{{{length},}}[ \t]*", value):
                fence = None
            _mask_range(chars, index, end)
            index = end
            continue

        if at_line_start:
            end = _line_end(text, index)
            match = FENCE_OPEN_RE.match(_line_value(text[index:end]))
            if match:
                run = match.group(1)
                fence = (run[0], len(run))
                _mask_range(chars, index, end)
                index = end
                continue

        if text.startswith("<!--", index):
            close = text.find("-->", index + 4)
            end = len(text) if close < 0 else close + 3
            if mask_comments:
                _mask_range(chars, index, end)
            index = end
            continue

        if text[index] == "`":
            run_end = index
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            run_length = run_end - index
            search = run_end
            close_end = -1
            while search < len(text):
                if text[search] != "`":
                    search += 1
                    continue
                candidate_end = search
                while candidate_end < len(text) and text[candidate_end] == "`":
                    candidate_end += 1
                if candidate_end - search == run_length:
                    close_end = candidate_end
                    break
                search = candidate_end
            if close_end >= 0:
                _mask_range(chars, index, close_end)
                index = close_end
                continue
            index = run_end
            continue

        index += 1
    return "".join(chars)


def strip_code_spans(text: str) -> str:
    """Blank out fenced and inline code so a [[link]] written as a syntax
    example inside code is not mistaken for a real wikilink. Order matters:
    strip fenced blocks first, then inline spans, so the two dangling scans
    (entity pages and meta pages) stay in lockstep."""
    return mask_code_spans(text).replace("\x00", " ")


def mask_code_spans(text: str) -> str:
    """Like strip_code_spans, but length-preserving: every code character is
    replaced with a NUL so offsets in the masked text map 1:1 onto the raw
    text. Use this when a regex must LOCATE something (a section span to
    rewrite) rather than merely count matches, so a fenced example can be
    skipped without shifting positions."""
    return _context_mask(text, frontmatter="preserve", mask_comments=False)


def _heading(line: str) -> tuple[int, str] | None:
    match = HEADING_RE.match(line)
    if not match:
        return None
    title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
    return len(match.group(1)), title.casefold()


def _section_spans(
    text: str, names: set[str], *, parse_frontmatter: bool = True
) -> list[tuple[int, int]]:
    """Locate named Markdown sections outside code, through same/higher heading."""
    wanted = {name.casefold() for name in names}
    masked = _context_mask(
        text,
        frontmatter="mask" if parse_frontmatter else "none",
        mask_comments=True,
    )
    lines = masked.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []
    offset = 0
    for line in lines:
        parsed = _heading(_line_value(line))
        if parsed is not None:
            headings.append((offset, parsed[0], parsed[1]))
        offset += len(line)

    spans: list[tuple[int, int]] = []
    for index, (start, level, title) in enumerate(headings):
        if level != 2 or title not in wanted:
            continue
        end = len(text)
        for next_start, next_level, _ in headings[index + 1:]:
            if next_level <= level:
                end = next_start
                break
        spans.append((start, end))
    return spans


def section_spans(text: str, *names: str) -> list[tuple[int, int]]:
    """Public, heading-aware spans for callers that must rewrite sections."""
    return _section_spans(text, set(names))


def section_body(text: str, name: str) -> str | None:
    """Body of the first named section, or ``None`` when it is absent."""
    spans = _section_spans(text, {name})
    if not spans:
        return None
    start, end = spans[0]
    line_end = text.find("\n", start, end)
    if line_end < 0:
        return ""
    return text[line_end + 1:end]


def strip_sections(text: str, *names: str) -> str:
    """Remove named sections while preserving every byte outside their spans."""
    spans = _section_spans(text, set(names))
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        out.append(text[cursor:start])
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def strip_body_sections(text: str, *names: str) -> str:
    """Remove sections from already-split body text (no frontmatter reparse)."""
    spans = _section_spans(text, set(names), parse_frontmatter=False)
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        out.append(text[cursor:start])
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def authored_link_view(text: str) -> str:
    """Authored link graph: generated backlinks and all code are excluded."""
    return _context_mask(
        strip_sections(text, "Referenced by"),
        frontmatter="preserve",
        mask_comments=False,
    ).replace("\x00", " ")


def evidentiary_view(text: str) -> str:
    """Authored evidence excluding metadata, link sections, code, and comments."""
    _, body = split_frontmatter(text)
    body = strip_body_sections(body, "Referenced by", "Related pages")
    return authored_body_view(body)


def evidentiary_line_views(text: str) -> list[tuple[int, str, str]]:
    """Return original and masked evidence lines with one-based positions."""
    masked = list(_context_mask(text, frontmatter="mask", mask_comments=True))
    for start, end in _section_spans(text, {"Referenced by"}):
        for index in range(start, end):
            if masked[index] not in "\r\n":
                masked[index] = "\x00"
    visible_lines = "".join(masked).splitlines(keepends=True)
    original_lines = text.splitlines(keepends=True)
    return [
        (line_number, original_lines[line_number - 1], visible)
        for line_number, visible in enumerate(visible_lines, start=1)
        if visible.strip("\x00\r\n ")
    ]


def authored_body_view(text: str) -> str:
    """Authored body prose with code and HTML comments masked.

    Unlike :func:`evidentiary_view`, this accepts an already-extracted body and
    does not interpret a leading thematic break as frontmatter or remove named
    sections. It is the shared view for already-extracted structured bodies.
    """
    return _context_mask(text, frontmatter="none", mask_comments=True).replace("\x00", " ")


def status_review_view(text: str) -> str:
    """Status-review text: authored prose and curated links, never generated/code."""
    return _context_mask(
        strip_sections(text, "Referenced by"),
        frontmatter="preserve",
        mask_comments=False,
    ).replace("\x00", " ")


def canonical_authored_text(text: str) -> str:
    """Canonical authored content with generated backlink sections removed.

    Only joins created by removing generated sections and the final newline are
    canonicalized; every other authored character remains byte-for-byte.
    """
    canonical = text
    for start, end in reversed(_section_spans(canonical, {"Referenced by"})):
        before, after = canonical[:start], canonical[end:]
        if before and after:
            canonical = before.rstrip("\r\n") + "\n\n" + after.lstrip("\r\n")
        elif before:
            canonical = before.rstrip("\r\n")
        else:
            canonical = after.lstrip("\r\n")
    return canonical.rstrip("\r\n") + "\n" if canonical else ""


def dangling_slugs(text: str, valid_slugs: Collection[str]) -> list[str]:
    """Wikilink slugs in `text` that resolve to nothing, after stripping code
    spans and skipping folder-pointer links ([[name/]]). Single source of truth
    for both the Tier-1 entity-page scan and the Tier-2 meta-page scan, so the
    two cannot drift on what counts as a dangling link."""
    out = []
    for slug in LINK_RE.findall(authored_link_view(text)):
        if slug.endswith("/") or slug in valid_slugs:
            continue
        out.append(slug)
    return out


def get_entity_pages(wiki_root: Path) -> list[Path]:
    """All entity pages under `wiki_root`: top-level pages that are not meta
    pages, plus every page one level deep (every wiki/ subfolder is an
    entity-type folder). Sorted, so the link-graph scans in lint.py,
    review_due.py, and rebuild_referenced_by.py enumerate the corpus identically
    and cannot drift on what counts as an entity page."""
    pages = []
    for p in wiki_root.rglob("*.md"):
        parts = p.relative_to(wiki_root).parts
        if len(parts) == 1 and p.stem not in META_PAGES:
            pages.append(p)
        elif len(parts) == 2:
            pages.append(p)
    return sorted(pages)


def strip_referenced_by(text: str) -> str:
    """Remove the auto-generated "## Referenced by" section so it never counts as
    an authored link. Shared by lint.py (its outbound link-graph reads only
    authored links) and rebuild_referenced_by.py (it must not feed generated
    output back into the graph), so the two cannot drift on what is generated."""
    return strip_sections(text, "Referenced by")


def split_quoted_csv(value: str) -> list[str]:
    """Split a simple inline YAML scalar or [list] value into item strings,
    respecting quotes so a comma inside a quoted phrase does not split it.
    Single source of truth for the frontmatter inline-list grammar (sources:
    and tags: parsing in lint.py)."""
    if not value:
        return []
    value = value.strip()
    if value.startswith("["):
        value = value[1:]
    if value.endswith("]"):
        value = value[:-1]
    cur, quote = "", None
    raw_items = []
    for ch in value:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch == ",":
            raw_items.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        raw_items.append(cur)
    items = []
    for it in raw_items:
        it = it.strip().strip("\"'").strip()
        if it:
            items.append(it)
    return items
