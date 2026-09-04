#!/usr/bin/env python3
"""Exercise bounded navigation, pagination, and large-entry behavior."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from eval_lib import Results
from wiki_lint_contract import FOLDER_TYPE
from wiki_lookup import lookup_wiki_index, lookup_wiki_log


def main() -> int:
    results = Results()
    with tempfile.TemporaryDirectory(prefix="wiki-lookup-") as directory:
        root = Path(directory)
        (root / "wiki").mkdir()
        index = root / "wiki/index.md"
        index.write_text("# Empty catalog\n")
        (root / "wiki/log.md").write_text("# Empty log\n")
        results.record("empty-template-catalog", "Matches: 0" in lookup_wiki_index(root))
        results.record("empty-template-log", "Entries: 0" in lookup_wiki_log(root))
        try:
            lookup_wiki_index(root, limit=1000)
        except ValueError:
            results.record("excessive-catalog-limit-rejected", True)
        else:
            results.record("excessive-catalog-limit-rejected", False)
        index.write_text("# Index\n\n## Products\n" + "\n".join(
            f"| [Widget {i}](products/widget-{i}.md) | Product {i} | medium |"
            for i in range(60)
        ) + "\n## Sources\n| [Widget source](sources/widget-source.md) | source | high |\n")
        output = lookup_wiki_index(root, "widget", "products", limit=2, offset=3)
        results.record("index-filters-and-paginates", "Matches: 60" in output and "widget-3.md" in output and "widget-4.md" in output and "widget-5.md" not in output)
        sections = lookup_wiki_index(root)
        results.record("empty-query-returns-catalog-not-content", "## Products" in sections and "widget-0.md" not in sections)
        index.write_text("\n".join(f"| [Entry]({folder}/entry.md) | neutral |" for folder in FOLDER_TYPE))
        results.record("every-configured-folder-can-be-filtered", all(
            "Matches: 1" in lookup_wiki_index(root, folder=folder) for folder in FOLDER_TYPE))
        index.write_text("| [Huge](products/huge.md) | " + "x" * 50000 + " |\n")
        output = lookup_wiki_index(root, "huge")
        results.record("oversized-index-row-is-bounded-and-marked", len(output) <= 12000 and "Output truncated" in output)
        log = root / "wiki/log.md"
        log.write_text("# Log\n\n## [2026-09-03] workflow | New\nNew entry.\n\n## [2026-09-02] ingest | Older\nOld entry.\n")
        output = lookup_wiki_log(root, count=1)
        results.record("log-loads-only-requested-entries", "New entry." in output and "Old entry." not in output)
        results.record("log-pagination-reaches-older-entry", "Old entry." in lookup_wiki_log(root, count=1, offset=1))
        log.write_text("## [2026-09-03] workflow | Huge\n" + "x" * 50000)
        output = lookup_wiki_log(root)
        results.record("long-log-lines-cannot-exceed-budget", len(output) <= 12000 and "Output truncated" in output)
        try:
            lookup_wiki_log(root, count=1000)
        except ValueError:
            results.record("unbounded-log-request-rejected", True)
        else:
            results.record("unbounded-log-request-rejected", False)
    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
