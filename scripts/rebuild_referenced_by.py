#!/usr/bin/env python3
"""Rebuild generated ``## Referenced by`` sections for wiki entity pages.

The rebuild is deliberately planned from one immutable UTF-8 snapshot. Every
page is read and transformed before the first write, and every changed output
is applied through one recoverable file transaction. Generated sections and
code spans never feed the reverse link graph back into itself.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import stat
from pathlib import Path

from _file_transactions import TransactionError, recover_all, run_transaction
from _wiki_parse import (
    LINK_RE,
    authored_link_view,
    canonical_authored_text,
    get_entity_pages,
    section_spans,
)


WIKI_ROOT = Path("wiki")


class RebuildError(RuntimeError):
    """A controlled read, transform, or write failure."""


@dataclass(frozen=True)
class PageSnapshot:
    text: str
    content: bytes
    sha256: str
    mode: int


def load_page_texts(all_pages: list[Path]) -> dict[Path, PageSnapshot]:
    """Read every target exactly once as UTF-8, before any page is written."""
    snapshot: dict[Path, PageSnapshot] = {}
    for page in all_pages:
        try:
            info = page.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RebuildError(f"cannot snapshot unsafe page entry {page}")
            content = page.read_bytes()
            text = content.decode("utf-8")
            snapshot[page] = PageSnapshot(
                text=text,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                mode=stat.S_IMODE(info.st_mode),
            )
        except (OSError, UnicodeError) as exc:
            raise RebuildError(f"cannot read {page} as UTF-8: {exc}") from exc
    return snapshot


def authored_texts(snapshot: dict[Path, PageSnapshot]) -> dict[Path, str]:
    """Return pure link-scan views with code and generated regions masked."""
    return {page: authored_link_view(item.text) for page, item in snapshot.items()}


def build_reverse_index(
    scan_texts: dict[Path, str], wiki_root: Path = WIKI_ROOT
) -> dict[str, dict[str, list[Path]]]:
    """Build ``slug -> directory label -> source pages`` in one pure pass."""
    index: dict[str, dict[str, list[Path]]] = {}
    for page, text in scan_texts.items():
        parts = page.relative_to(wiki_root).parts
        directory_label = parts[0] if len(parts) > 1 else "wiki root"
        for slug in set(LINK_RE.findall(text)):
            index.setdefault(slug, {}).setdefault(directory_label, []).append(page)
    return index


def find_references(
    slug: str,
    reverse_index: dict[str, dict[str, list[Path]]],
    target_path: Path,
) -> dict[str, list[str]]:
    """Renderable inbound references, excluding a target's self-reference."""
    refs: defaultdict[str, list[str]] = defaultdict(list)
    for directory_label, pages in reverse_index.get(slug, {}).items():
        for page in pages:
            if page != target_path:
                refs[directory_label].append(f"[[{page.stem}]]")
    return {label: links for label, links in refs.items() if links}


def build_referenced_by_block(refs: dict[str, list[str]]) -> str:
    """Render one canonical generated section."""
    if not refs:
        return "## Referenced by\n\n_No inbound links yet._\n"
    lines = ["## Referenced by\n"]
    for directory_label in sorted(refs):
        links = ", ".join(sorted(refs[directory_label]))
        lines.append(f"\n**{directory_label}/**  {links}\n")
    return "\n".join(lines) + "\n"


def render_page(authored_page: str, new_block: str) -> str:
    """Purely replace, collapse, or insert the generated section in one page."""
    generated = section_spans(authored_page, "Referenced by")
    if generated:
        parts: list[str] = []
        last = 0
        for index, (start, end) in enumerate(generated):
            parts.append(authored_page[last:start])
            if index == 0:
                parts.append(new_block.rstrip("\n") + "\n")
            last = end
        parts.append(authored_page[last:])
        rendered = "".join(parts)
        if not rendered.endswith("\n"):
            rendered += "\n"
        return rendered

    related = section_spans(authored_page, "Related pages")
    related_start = related[0][0] if related else None
    if related_start == 0:
        return new_block.rstrip("\n") + "\n" + authored_page
    if related_start is not None:
        prefix = authored_page[:related_start].rstrip("\n")
        return (
            prefix
            + "\n\n"
            + new_block.rstrip("\n")
            + "\n"
            + authored_page[related_start:]
        )
    return authored_page.rstrip("\n") + "\n\n" + new_block.rstrip("\n") + "\n"


def build_backlink_rebuild_plan(
    snapshot: dict[Path, PageSnapshot], wiki_root: Path = WIKI_ROOT
) -> tuple[dict[Path, str], dict[Path, int]]:
    """Compute changed outputs and inbound counts from the original snapshot."""
    reverse_index = build_reverse_index(authored_texts(snapshot), wiki_root)
    changed: dict[Path, str] = {}
    inbound_counts: dict[Path, int] = {}
    for page, item in snapshot.items():
        original = item.text
        refs = find_references(page.stem, reverse_index, page)
        inbound_counts[page] = sum(len(links) for links in refs.values())
        rendered = render_page(original, build_referenced_by_block(refs))
        try:
            rendered.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RebuildError(f"rendered output is not UTF-8 encodable for {page}: {exc}") from exc
        if len(section_spans(rendered, "Referenced by")) != 1:
            raise RebuildError(f"generated-section invariant failed for {page}")
        if canonical_authored_text(rendered) != canonical_authored_text(original):
            raise RebuildError(f"authored text changed while rendering {page}")
        if rendered != original:
            changed[page] = rendered
    return changed, inbound_counts


def apply_backlink_rebuild_plan(
    changed_only: dict[Path, str],
    snapshot: dict[Path, PageSnapshot],
    *,
    repo_root: Path,
    fault: Callable[[str], None] | None = None,
) -> list[str]:
    """Apply only changed pages as one recoverable generated generation."""
    if not changed_only:
        return []
    outputs: dict[str, bytes] = {}
    preimages: dict[str, bytes | None] = {}
    for page, text in changed_only.items():
        item = snapshot[page]
        if not (item.mode & stat.S_IWUSR):
            raise RebuildError(f"cannot write {page}: owner write permission is not set")
        relative = page.relative_to(repo_root).as_posix() if page.is_absolute() else page.as_posix()
        outputs[relative] = text.encode("utf-8")
        preimages[relative] = item.content
    try:
        recovery = run_transaction(
            repo_root,
            consumer="rebuild-referenced-by",
            outputs=outputs,
            expected_preimages=preimages,
            allowed_prefixes=("wiki",),
            fault=fault,
        )
    except TransactionError as exc:
        raise RebuildError(str(exc)) from exc
    for page, text in changed_only.items():
        if page.read_bytes() != text.encode("utf-8"):
            raise RebuildError(f"installed backlink output failed verification: {page}")
    return recovery


def main() -> int:
    if not WIKI_ROOT.exists():
        print(
            "Error: 'wiki/' directory not found. Run this script from the repo root.\n"
            f"  Current directory: {Path.cwd()}",
            file=sys.stderr,
        )
        return 1

    all_pages = get_entity_pages(WIKI_ROOT)
    print(f"Found {len(all_pages)} entity pages.")
    try:
        try:
            recovery = recover_all(Path.cwd().resolve())
        except TransactionError as exc:
            raise RebuildError(str(exc)) from exc
        if recovery:
            print("Recovered interrupted transaction before snapshot:")
            for message in recovery:
                print(f"- {message}")
        snapshot = load_page_texts(all_pages)
        changed, inbound_counts = build_backlink_rebuild_plan(snapshot)
        apply_recovery = apply_backlink_rebuild_plan(
            changed,
            snapshot,
            repo_root=Path.cwd().resolve(),
        )
        if apply_recovery:
            print("Recovered interrupted transaction before commit:")
            for message in apply_recovery:
                print(f"- {message}")
    except (RebuildError, ValueError) as exc:
        print(f"Error: backlink rebuild failed: {exc}", file=sys.stderr)
        return 1

    for page in all_pages:
        print(f"  {page}  ({inbound_counts[page]} inbound links)")
    print(f"\nDone. Processed {len(all_pages)} pages; changed {len(changed)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
