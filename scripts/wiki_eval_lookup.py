#!/usr/bin/env python3
"""Exercise bounded navigation, pagination, and large-entry behavior."""
from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

from eval_lib import Results
from wiki_lint_contract import FOLDER_TYPE
from wiki_lookup import lookup_wiki_content, lookup_wiki_index, lookup_wiki_log


def main() -> int:
    results = Results()
    with tempfile.TemporaryDirectory(prefix="wiki-lookup-") as directory:
        root = Path(directory)
        (root / "wiki").mkdir()
        index = root / "wiki/index.md"
        index.write_text("# Empty catalog\n")
        (root / "wiki/log.md").write_text("# Empty log\n")
        results.record("empty-template-catalog", "Matches: 0" in lookup_wiki_index(root))
        results.record("empty-template-content", "Matching pages: 0;" in lookup_wiki_content(root, "widget"))
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
    with tempfile.TemporaryDirectory(prefix="wiki-content-lookup-") as directory:
        root = Path(directory)
        wiki = root / "wiki"
        (wiki / "features").mkdir(parents=True)
        (wiki / "sources").mkdir()
        index = wiki / "index.md"
        catalog = (
            "| [Hybrid](features/hybrid.md) | Local processing | high |\n"
            "| [Guide](sources/guide.md) | Setup | high |\n"
            "| [Log](log.md) | Activity | high |\n"
        )
        index.write_text(catalog)
        page = wiki / "features/hybrid.md"
        page.write_text(
            "---\ntitle: Hybrid\ntags: [metadata-only]\n---\n"
            "# Hybrid\n## Privacy choices\nUsers can skip the file.\n"
            "## Related pages\nrelated-only\n"
            "## Referenced by\nbacklink-only\n"
        )
        (wiki / "sources/guide.md").write_text("# Guide\nSkip this file.\n")
        (wiki / "log.md").write_text("# Log\nSkip the file.\n")
        before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        output = lookup_wiki_content(root, "skip file", "features")
        results.record("content-recovers-catalog-miss",
                       "Matches: 0;" in lookup_wiki_index(root, "skip file")
                       and "features/hybrid.md:7: Hybrid — Privacy choices" in output
                       and "Users can skip the file." in output and "sources/guide.md" not in output)
        output = lookup_wiki_content(root, "skip file", limit=1, offset=1)
        results.record("content-pagination-and-root-exclusion",
                       "Matching pages: 2;" in output and "sources/guide.md:2" in output
                       and "features/hybrid.md:" not in output and "wiki/log.md:" not in output)
        for query in ("metadata-only", "related-only", "backlink-only", "zzq_nonexistent_7391"):
            results.record("content-excludes-" + query,
                           "Matching pages: 0;" in lookup_wiki_content(root, query))
        results.record("content-read-only", before == {
            p: p.read_bytes() for p in root.rglob("*") if p.is_file()
        })
        for kwargs in ({"query": ""}, {"query": " "},
                       {"query": "skip", "limit": 0},
                       {"query": "skip", "folder": "../features"}, {"query": "skip", "folder": "typo"},
                       {"query": "skip", "limit": 13}, {"query": "skip", "offset": -1}):
            try:
                lookup_wiki_content(root, **kwargs)
            except ValueError:
                results.record("content-rejects-invalid-" + str(kwargs), True)
            else:
                results.record("content-rejects-invalid-" + str(kwargs), False)
        for relative in ("../outside.md", str(root / "outside.md"), "features/../sources/guide.md", "features/escape.md", "features/cross.md"):
            (root / "outside.md").write_text("skip file")
            if relative == "features/escape.md":
                (wiki / relative).symlink_to(root / "outside.md")
            elif relative == "features/cross.md":
                (wiki / relative).symlink_to(wiki / "sources/guide.md")
            index.write_text(f"| [Escape]({relative}) | Test | low |\n")
            try:
                lookup_wiki_content(root, "skip file")
            except ValueError:
                results.record("content-confines-" + relative, True)
            else:
                results.record("content-confines-" + relative, False)
        index.write_text(catalog)
        page.write_text("---\ntitle: Unclosed\nskip file\n")
        try:
            lookup_wiki_content(root, "skip file")
        except ValueError:
            results.record("content-rejects-malformed-frontmatter", True)
        else:
            results.record("content-rejects-malformed-frontmatter", False)
        page.write_text("# Hybrid\nskip file " + "x" * 20000)
        output = lookup_wiki_content(root, "skip file", "features")
        results.record("content-bounds-excerpt", "[excerpt truncated]" in output and len(output) < 1500)
        for name, line, query, missing in (
            ("late", "x" * 700 + " privacy gate " + "z" * 100, "privacy gate", False),
            ("dispersed", "privacy " + "x" * 700 + " gate", "privacy gate", True),
            ("repeated", "privacy " + "x" * 700 + " privacy gate", "privacy gate", False),
            ("unicode", "ß" * 600 + " Straße gate " + "z" * 600, "STRASSE gate", False),
            ("overlapping", "x" * 600 + " ababa " + "z" * 600, "aba bab", False),
            ("duplicate-terms", "x" * 700 + " privacy gate", "privacy privacy gate", False),
            ("short", "privacy gate choices", "privacy gate", False),
            ("whitespace", "  privacy gate choices  ", "privacy gate", False),
            ("oversized-term", "q" * 501, "q" * 501, True),
            ("closest", "privacy " + "x" * 200 + " gate " + "z" * 600 + "privacy gate", "privacy gate", False),
        ):
            page.write_text("# Hybrid\n## Choices\n" + line + "\n")
            output = lookup_wiki_content(root, query, "features")
            excerpt = output.split("\n  ", 1)[1].rstrip("\n")
            source = excerpt.split(" [excerpt truncated]", 1)[0]
            if source.startswith("… "):
                source = source[2:]
            if source.endswith(" …"):
                source = source[:-2]
            results.record("content-window-" + name,
                           "features/hybrid.md:3:" in output
                           and source in line and len(source) == min(len(line), 500)
                           and (name != "closest" or "privacy gate" in source)
                           and ("[some query terms omitted; open source line]" in excerpt) == missing
                           and (missing or all(word in source.casefold() for word in query.casefold().split()))
                           and (len(line) > 500 or excerpt == line))
        page.write_text("---\ntitle: " + "x" * 20000 + "\n---\nskip file\n")
        output = lookup_wiki_content(root, "skip file", "features")
        results.record("content-bounds-total-output", len(output) <= 12000 and "Output truncated" in output)
        page.write_text("# Hybrid\nskip\nfile\n")
        results.record("content-requires-same-line", "Matching pages: 0;" in
                       lookup_wiki_content(root, "skip file", "features"))
        page.write_text("# Hybrid\n## Related pages\n### Child\nnested-hidden\n"
                        "## Evidence\nrestored-visible\n")
        results.record("content-section-boundaries", "Matching pages: 0;" in
                       lookup_wiki_content(root, "nested-hidden", "features")
                       and "features/hybrid.md:6:" in
                       lookup_wiki_content(root, "restored-visible", "features"))
        for malformed in ("---broken\nskip file", "---\ntitle: A\ntitle: B\n---\nskip file",
                          '---\ntitle: "Unclosed\n---\nskip file'):
            page.write_text(malformed)
            try:
                lookup_wiki_content(root, "skip file", "features")
            except ValueError:
                results.record("content-malformed-parser-contract", True)
            else:
                results.record("content-malformed-parser-contract", False)
        rows = []
        for i in range(13):
            relative = f"features/item-{i}.md"
            (wiki / relative).write_text("# Item\nskip file\nskip file again\n")
            rows.append(f"| [Item]({relative}) | fixture |")
        index.write_text("\n".join(rows + rows[:1]))
        output = lookup_wiki_content(root, "skip file")
        results.record("content-default-limit-order-and-deduplication",
                       "Matching pages: 13; offset: 0; returned: 12." in output
                       and "--offset 12" in output and "item-12.md:" not in output
                       and output.count("wiki/features/item-0.md:") == 1
                       and output.index("item-2.md:") < output.index("item-10.md:"))
        results.record("content-last-and-empty-page",
                       "item-12.md:2:" in lookup_wiki_content(root, "skip file", offset=12)
                       and "returned: 0." in lookup_wiki_content(root, "skip file", offset=13))
        outside = root / "external-folder"
        outside.mkdir()
        (outside / "item.md").write_text("skip file")
        (wiki / "concepts").symlink_to(outside, target_is_directory=True)
        index.write_text("| [Escape](concepts/item.md) | fixture |")
        try:
            lookup_wiki_content(root, "skip file")
        except ValueError:
            results.record("content-confines-folder-symlink", True)
        else:
            results.record("content-confines-folder-symlink", False)
        index.write_text("# Empty template\n")
        (wiki / "domain.md").write_text("---\norg: <Organization name>\n---\n")
        before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        command = [sys.executable, "-B", str(Path(__file__).with_name("wiki_lookup.py").resolve()), "content"]
        for args in ([], ["--query", ""], ["--query", "skip", "--limit", "0"],
                     ["--query", "skip", "--limit", "13"], ["--query", "skip", "--limit", "abc"],
                     ["--query", "skip", "--offset", "-1"], ["--query", "skip", "--folder", "raw"]):
            proc = subprocess.run(command + args, cwd=root, capture_output=True, text=True)
            results.record("content-cli-invalid-" + repr(args), proc.returncode == 2 and not proc.stdout)
        proc = subprocess.run(command + ["--query", "skip"], cwd=root, capture_output=True, text=True)
        results.record("content-cli-unconfigured-template", proc.returncode == 0 and "Matching pages: 0;" in proc.stdout)
        results.record("content-cli-read-only", before == {
            p: p.read_bytes() for p in root.rglob("*") if p.is_file()
        })
    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
