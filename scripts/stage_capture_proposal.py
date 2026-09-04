#!/usr/bin/env python3
"""Build one complete exact capture proposal under ``tmp/``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from capture_staging import CaptureStagingError, stage_capture_proposal


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--request", required=True)
    command.add_argument("--output", required=True)
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        result = stage_capture_proposal(Path.cwd(), args.request, args.output)
    except CaptureStagingError as exc:
        print(f"capture-staging error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "proposal_path": result.proposal_path,
                "result_code": result.result_code,
                "target_paths": list(result.target_paths),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
