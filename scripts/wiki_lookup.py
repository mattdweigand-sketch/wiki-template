#!/usr/bin/env python3
"""Return bounded catalog matches or recent log entries without loading the corpus."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from _wiki_parse import parse_log_entry_date


MAX_OUTPUT_CHARS = 12000


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
    log = commands.add_parser("log")
    log.add_argument("--count", type=int, default=5)
    log.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    try:
        result = (lookup_wiki_index(Path.cwd(), args.query, args.folder, limit=args.limit, offset=args.offset)
                  if args.command == "index" else lookup_wiki_log(Path.cwd(), count=args.count, offset=args.offset))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(result, end="")
    return 0


__all__ = ["lookup_wiki_index", "lookup_wiki_log"]


if __name__ == "__main__":
    raise SystemExit(main())
