#!/usr/bin/env python3
"""Validate the exact capture-application ledger."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from capture_ledger import validate_capture_ledger_file


DEFAULT_CAPTURE_LEDGER = Path("scripts/capture-runs.jsonl")


def capture_ledger_parser() -> argparse.ArgumentParser:
    """Build the capture-ledger validation CLI."""
    parser = argparse.ArgumentParser(
        description="Validate scripts/capture-runs.jsonl."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_CAPTURE_LEDGER),
        help="JSONL exact-application ledger to validate.",
    )
    return parser


def main() -> int:
    args = capture_ledger_parser().parse_args()
    errors, application_count = validate_capture_ledger_file(Path(args.path))
    if errors:
        print("Capture ledger validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"Capture ledger validation passed: {application_count} application record(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
