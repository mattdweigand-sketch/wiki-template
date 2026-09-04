#!/usr/bin/env python3
"""Check a Git revision range for exact capture-record agreement."""

from __future__ import annotations

import argparse
from pathlib import Path

from capture_diff import capture_diff_problems


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--base", required=True)
    command.add_argument("--head", required=True)
    return command


def main() -> int:
    args = parser().parse_args()
    problems = capture_diff_problems(Path.cwd(), args.base, args.head)
    if problems:
        print("Capture diff check failed:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print(f"Capture diff check passed: {args.base}..{args.head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
