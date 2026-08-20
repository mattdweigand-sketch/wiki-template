#!/usr/bin/env python3
"""Report optional verified remote-backup freshness without gating the wiki."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wiki_backup_receipt import DEFAULT_BACKUP_RECEIPT_PATH, backup_freshness


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Report verified remote-backup state.")
    result.add_argument("--receipt", type=Path, default=DEFAULT_BACKUP_RECEIPT_PATH)
    result.add_argument("--max-age-days", type=int, default=30)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        state = backup_freshness(args.receipt, max_age_days=args.max_age_days)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Backup state: {state.kind}")
    print(state.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "parser"]
