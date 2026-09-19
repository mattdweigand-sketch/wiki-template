#!/usr/bin/env python3
"""Return bounded catalog matches, content excerpts, or recent log entries."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from _wiki_parse import parse_log_entry_date, section_spans, split_frontmatter
from wiki_entity_catalog import load_entity_catalog


MAX_OUTPUT_CHARS = 12000
MAX_EXCERPT_CHARS = 500


def _bounded_lookup_text(lines: list[str]) -> str:
    text = "\n".join(lines) + "\n"
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    note = "\n[Output truncated; narrow the query or open the indicated file lines.]\n"
    return text[:MAX_OUTPUT_CHARS - len(note)] + note


def lookup_wiki_index(
    repo_root: Path, query: str = "", folder: str = "", *, limit: int = 12, offset: int = 0,
) -> str:
    """Render current authored catalog rows, or section locations, within a fixed budget."""
    if not 1 <= limit <= 40 or offset < 0:
        raise ValueError("limit must be 1..40 and offset must be nonnegative")
    rows: list[str] = []
    words = query.casefold().split()
    for number, line in enumerate((repo_root / "wiki/index.md").read_text().splitlines(), 1):
        if not words and not folder:
            if line.startswith("## "):
                rows.append(f"wiki/index.md:{number}: {line}")
            continue
        match = re.search(r"\]\(([^)]+\.md)\)", line)
        if not match or not line.startswith("|"):
            continue
        if folder and not match[1].startswith(folder.rstrip("/") + "/"):
            continue
        if all(word in line.casefold() for word in words):
            rows.append(f"wiki/index.md:{number}: {line}")
    selected = rows[offset:offset + limit]
    header = f"Matches: {len(rows)}; offset: {offset}; returned: {len(selected)}. Use --offset {offset + len(selected)} for the next page."
    return _bounded_lookup_text([header, *selected])


def _matching_excerpt(line: str, words: list[str]) -> str:
    """Keep an exact source window around the closest group of query matches."""
    if len(line) <= MAX_EXCERPT_CHARS:
        return line
    # Casefold can expand characters (ß -> ss); map matches back to source offsets.
    folded = line.casefold()
    offsets = [index for index, char in enumerate(line) for _ in char.casefold()]
    terms = set(words)
    hits = sorted(
        (offsets[match.start()], offsets[match.start() + len(word) - 1] + 1, word)
        for word in terms
        for match in re.finditer(r"(?=" + re.escape(word) + r")", folded)
    )
    latest: dict[str, tuple[int, int]] = {}
    best = (len(line) + 1, 0, len(line))
    for start, end, word in hits:
        latest[word] = (start, end)
        if len(latest) == len(terms):
            left = min(span[0] for span in latest.values())
            right = max(span[1] for span in latest.values())
            best = min(best, (right - left, left, right))
    width, left, _ = best
    padding = max(0, (MAX_EXCERPT_CHARS - width) // 2)
    start = max(0, min(left - padding, len(line) - MAX_EXCERPT_CHARS))
    end = start + MAX_EXCERPT_CHARS
    excerpt = line[start:end]
    missing = not all(word in excerpt.casefold() for word in terms)
    return (
        ("… " if start else "") + excerpt + (" …" if end < len(line) else "")
        + " [excerpt truncated]"
        + (" [some query terms omitted; open source line]" if missing else "")
    )


def lookup_wiki_content(
    repo_root: Path, query: str, folder: str = "", *, limit: int = 12, offset: int = 0,
) -> str:
    """Search cataloged entity bodies; expose bounded navigation excerpts only."""
    words = query.casefold().split()
    if not words:
        raise ValueError("content lookup requires a nonempty query")
    if not 1 <= limit <= 12 or offset < 0:
        raise ValueError("limit must be 1..12 and offset must be nonnegative")
    folders = load_entity_catalog().folder_types
    if folder and folder not in folders:
        raise ValueError(f"unknown entity folder: {folder}")
    wiki_root = (repo_root / "wiki").resolve()
    catalog = (wiki_root / "index.md").read_text(encoding="utf-8")
    paths = dict.fromkeys(re.findall(
        r"^\|.*?\]\(([^)]+\.md)\)", catalog, re.MULTILINE,
    ))
    matches: list[str] = []
    for relative in paths:
        parts = Path(relative).parts
        if Path(relative).is_absolute() or ".." in parts:
            raise ValueError(f"unsafe catalog path: {relative}")
        if len(parts) < 2 or parts[0] not in folders:
            continue
        if folder and parts[0] != folder:
            continue
        path = (wiki_root / relative).resolve()
        if not path.is_relative_to(wiki_root) or path.relative_to(wiki_root).parts[0] != parts[0]:
            raise ValueError(f"catalog path escapes its entity folder: {relative}")
        text = path.read_text(encoding="utf-8")
        metadata, body = split_frontmatter(text)
        title = (metadata or {}).get("title") or path.stem
        excluded = section_spans(text, "Referenced by", "Related pages")
        position = len(text) - len(body)
        number = text[:position].count("\n") + 1
        section = title
        for line in body.splitlines(keepends=True):
            skip = any(start <= position < end for start, end in excluded)
            heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if heading and not skip:
                section = heading[1]
            if not skip and all(word in line.casefold() for word in words):
                excerpt = _matching_excerpt(line.rstrip("\r\n"), words)
                matches.append(
                    f"wiki/{relative}:{number}: {title} — {section}\n  {excerpt}"
                )
                break
            position += len(line)
            number += 1
    selected = matches[offset:offset + limit]
    return _bounded_lookup_text([
        f"Matching pages: {len(matches)}; offset: {offset}; returned: {len(selected)}. "
        f"Use --offset {offset + len(selected)} for the next page.",
        "Catalog order, not relevance rank. Excerpts are navigation aids, not verified answers; "
        "read page authority, confidence, qualifications, and evidence before answering.",
        *selected,
    ])


def lookup_wiki_log(repo_root: Path, *, count: int = 5, offset: int = 0) -> str:
    """Render a bounded window of complete newest-first activity entries."""
    if not 1 <= count <= 20 or offset < 0:
        raise ValueError("count must be 1..20 and offset must be nonnegative")
    lines = (repo_root / "wiki/log.md").read_text().splitlines()
    starts = [number for number, line in enumerate(lines) if parse_log_entry_date(line) is not None]
    entries: list[str] = []
    for index in range(offset, min(offset + count, len(starts))):
        start = starts[index]
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        entries.append(f"wiki/log.md:{start + 1}\n" + "\n".join(lines[start:end]))
    return _bounded_lookup_text([f"Entries: {len(starts)}; offset: {offset}; returned: {len(entries)}.", *entries])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index")
    index.add_argument("--query", default="")
    index.add_argument("--folder", default="")
    index.add_argument("--limit", type=int, default=12)
    index.add_argument("--offset", type=int, default=0)
    content = commands.add_parser("content")
    content.add_argument("--query", required=True)
    content.add_argument("--folder", default="")
    content.add_argument("--limit", type=int, default=12)
    content.add_argument("--offset", type=int, default=0)
    log = commands.add_parser("log")
    log.add_argument("--count", type=int, default=5)
    log.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.command in ("index", "content"):
            lookup = lookup_wiki_index if args.command == "index" else lookup_wiki_content
            result = lookup(Path.cwd(), args.query, args.folder, limit=args.limit, offset=args.offset)
        else:
            result = lookup_wiki_log(Path.cwd(), count=args.count, offset=args.offset)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(result, end="")
    return 0


__all__ = ["lookup_wiki_index", "lookup_wiki_content", "lookup_wiki_log"]


if __name__ == "__main__":
    raise SystemExit(main())
