#!/usr/bin/env python3
"""Create one random or exact-page evidence sample under tmp/evidence-check/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wiki_evidence import (
    EvidenceRunError,
    create_evidence_sample,
    create_targeted_evidence_sample,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--run-id", required=True)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--count", type=int, default=None)
    mode.add_argument(
        "--path",
        action="append",
        dest="page_paths",
        help="Include every cited claim on this exact wiki entity page; repeat as needed",
    )
    result.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.page_paths:
            manifest = create_targeted_evidence_sample(
                args.repo_root, args.run_id, args.page_paths
            )
        else:
            manifest = create_evidence_sample(
                args.repo_root,
                args.run_id,
                25 if args.count is None else args.count,
            )
    except EvidenceRunError as exc:
        print(f"build_evidence_sample.py: {exc}", file=sys.stderr)
        return 1
    relative = manifest.run_dir.relative_to(args.repo_root.resolve())
    print(
        f"Created {relative}/sample.json with {manifest.selected_count} claims; "
        f"manifest {manifest.manifest_sha256}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = []
