#!/usr/bin/env python3
"""Validate one sample and plant, then publish exact verifier batches."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wiki_evidence import EvidenceRunError, publish_evidence_batches


REPO_ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--run-dir", required=True, type=Path,
        help="Canonical tmp/evidence-check/<run-id> path",
    )
    result.add_argument("--batches", type=int, choices=(2, 3), required=True)
    result.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        plan = publish_evidence_batches(args.repo_root, args.run_dir, args.batches)
    except EvidenceRunError as exc:
        print(f"build_verifier_batches.py: {exc}", file=sys.stderr)
        return 1
    print(f"Built {plan.batch_count} exact verifier batches in {args.run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = []
