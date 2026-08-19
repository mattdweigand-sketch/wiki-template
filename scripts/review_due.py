#!/usr/bin/env python3
"""List wiki pages whose dated prediction or decision is due for outcome review.

A page opts into the grading loop by adding `review_by: YYYY-MM-DD` to its
frontmatter. This surfaces every page whose review_by is on or before today, so
the highest-stakes predictions and decisions get graded against what actually
happened instead of standing on self-assessed confidence forever.

The script is deterministic and surfaces only: recording the realized outcome
and adjusting confidence is a human judgment, performed via
workflows/maintenance/review.md, which then advances or clears review_by so the
page leaves this list until its next checkpoint. Lint validates the date format;
this report is informational and always exits 0.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from _wiki_parse import FrontmatterError, frontmatter_block, get_entity_pages


# Capture the whole rest of the line: a value with trailing tokens (e.g.
# "2026-05-01 approx") must land in the invalid report, not silently drop the
# page out of the review loop the way a \S+-anchored match would.
REVIEW_BY_RE = re.compile(r"^review_by:(.*)$", re.M)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_date_arg(value: str) -> date:
    """Argparse converter for clean usage errors on malformed --today."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a valid YYYY-MM-DD date"
        ) from exc


def collect(
    root: Path,
    today: date,
) -> tuple[list[tuple[int, str, str]], list[tuple[str, str]]]:
    due, bad = [], []
    for p in get_entity_pages(root):
        try:
            fm = frontmatter_block(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, FrontmatterError):
            continue
        m = REVIEW_BY_RE.search(fm)
        if not m:
            continue
        rel = str(p.relative_to(root))
        val = m.group(1).strip()
        if not val:
            continue  # bare 'review_by:' means not enrolled; lint skips it too
        if not DATE_RE.match(val):
            bad.append((rel, val))
            continue
        try:
            review_by = date.fromisoformat(val)
        except ValueError:  # shape-valid but impossible date, e.g. 2026-13-99
            bad.append((rel, val))
            continue
        if review_by <= today:
            due.append(((today - review_by).days, rel, val))
    due.sort(reverse=True)
    return due, bad


def main() -> int:
    ap = argparse.ArgumentParser(description="List pages due for outcome review.")
    ap.add_argument("--root", default="wiki", help="Wiki root to scan.")
    ap.add_argument("--today", type=iso_date_arg, default=None,
                    help="Override today (YYYY-MM-DD), for tests.")
    args = ap.parse_args()
    today = args.today or date.today()

    due, bad = collect(Path(args.root), today)
    print(f"Outcome review due as of {today.isoformat()}: {len(due)} page(s)")
    for overdue, rel, val in due:
        print(f"  {rel}  (review_by {val}, {overdue} day(s) overdue)")
    if bad:
        print(f"Invalid review_by values (lint also flags these): {len(bad)}")
        for rel, val in bad:
            print(f"  {rel}: '{val}'")
    return 0  # informational: a review backlog is not a failure


if __name__ == "__main__":
    sys.exit(main())
