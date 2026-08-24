#!/usr/bin/env python3
"""
Lint the wiki against its own rules, split by enforcement tier.

Tier 1 (deterministic, machine-checkable): hard failures. A rule here is true
or false with no judgment. The script decides, and a Tier-1 failure exits
non-zero so it can gate a commit. Examples: frontmatter keys, type/folder
match, dangling [[links]], index coverage. (Em dashes are allowed in the wiki
corpus by decision, so they are not checked.)

Tier 2 (expert-checkable): ranked candidates, not verdicts. The script computes
signals a maintainer cannot eyeball across hundreds of pages (orphans, uncited
pages, compiled pages with newer source inputs, review dates,
log growth, and sourcing-queue count drift) and surfaces them for a human or
agent to adjudicate. Tier 2 never fails the run unless --strict is passed.

Tier 3 (genuine judgment: contradictions, "missing cross-refs that should
exist", inconsistent terminology) is deliberately NOT attempted here. It stays
in the prose lint workflow, because a script cannot decide it.

Vendor-neutral: stdlib only, no dependencies. Run from the repo root:
    python3 scripts/lint.py            # report both tiers, fail on Tier 1
    python3 scripts/lint.py --strict   # also fail on Tier 2 candidates
    python3 scripts/lint.py --tier1    # Tier 1 only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _wiki_parse import META_PAGES, get_entity_pages
from wiki_lint_adjudications import load_adjudications
from wiki_lint_contract import (
    ADJUDICATIONS_PATH,
    WIKI_ROOT,
)
from wiki_lint_signals import TIER2_SIGNALS, run_tier2_lint
from wiki_lint_tier1 import parse_index_targets, run_tier1_lint


def main() -> int:
    ap = argparse.ArgumentParser(description="Lint the wiki by enforcement tier.")
    ap.add_argument("--strict", action="store_true", help="fail on Tier-2 candidates too")
    ap.add_argument("--tier1", action="store_true", help="run Tier 1 only")
    ap.add_argument(
        "--restored-tree",
        action="store_true",
        help="validate complete restored raw/source closure without requiring Git history",
    )
    ap.add_argument(
        "--git-view",
        action="store_true",
        help="validate tracked manifest/source closure without local raw files",
    )
    args = ap.parse_args()
    if args.restored_tree and not args.tier1:
        ap.error("--restored-tree requires --tier1")
    if args.git_view and not args.tier1:
        ap.error("--git-view requires --tier1")
    if args.restored_tree and args.git_view:
        ap.error("--restored-tree and --git-view are mutually exclusive")

    if not WIKI_ROOT.exists():
        print(f"Error: 'wiki/' not found. Run from the repo root. cwd={Path.cwd()}",
              file=sys.stderr)
        return 2

    entity_pages = [
        path for path in get_entity_pages(WIKI_ROOT)
        if not path.is_symlink() and path.is_file()
    ]
    valid_slugs = {p.stem for p in entity_pages} | META_PAGES
    index_targets, index_duplicates, index_read_fails = parse_index_targets()

    print(f"Wiki lint: {len(entity_pages)} entity pages\n")

    t1 = run_tier1_lint(
        entity_pages,
        valid_slugs,
        index_targets,
        index_duplicates,
        index_read_fails,
        provenance_view=(
            "restored" if args.restored_tree
            else "git" if args.git_view
            else "live"
        ),
    )
    print("TIER 1  (deterministic; must fix)")
    if not t1:
        print("  all checks passed")
    else:
        by_check = {}
        for check, page, detail in t1:
            by_check.setdefault(check, []).append((page, detail))
        for check in sorted(by_check):
            rows = by_check[check]
            print(f"  [{check}]  {len(rows)}")
            for page, detail in rows[:25]:
                print(f"      {page}: {detail}")
            if len(rows) > 25:
                print(f"      ... and {len(rows) - 25} more")
    print()

    t2 = None
    suppressed = 0
    if not args.tier1:
        t2 = run_tier2_lint(entity_pages, valid_slugs, load_adjudications())
        suppressed = t2.pop("_suppressed", 0)
        print("TIER 2  (review; ranked candidates, judgment decides)")
        for key, label, _signal in TIER2_SIGNALS:
            items = t2[key]
            print(f"  {label}: {len(items)}")
            for it in items:
                print(f"      {it}")
        if suppressed:
            print(f"  (adjudicated, suppressed via {ADJUDICATIONS_PATH}: {suppressed})")
        print()

    n1 = len(t1)
    print(f"Summary: {n1} Tier-1 failure(s)" +
          ("" if args.tier1 else f"; {sum(len(v) for v in t2.values())} Tier-2 candidate(s)"))

    if n1:
        return 1
    if args.strict and t2 and any(t2.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
