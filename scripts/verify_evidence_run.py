#!/usr/bin/env python3
"""Validate one exact evidence run and persist its authoritative result."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wiki_evidence import EvidenceRunError, validate_evidence_run


REPO_ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--run-dir", required=True, type=Path)
    result.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        validation = validate_evidence_run(args.repo_root, args.run_dir)
    except EvidenceRunError as exc:
        print(f"verify_evidence_run.py: {exc}", file=sys.stderr)
        return 1
    print(f"Evidence fidelity: {validation.status}")
    print(
        f"Structure: {validation.structure}; snapshot: {validation.snapshot}; "
        f"review: {validation.review}"
    )
    if validation.metrics is not None:
        print(
            f"Counts: sampled={validation.metrics.sampled} "
            f"verified={validation.metrics.verified} "
            f"flagged={validation.metrics.flagged} "
            f"missing={validation.metrics.missing} "
            f"plant={validation.metrics.plant_verdict}"
        )
    for claim_id in validation.flagged_ids:
        print(f"Flagged claim: {claim_id}")
    for error in validation.errors:
        print(f"- {error}")
    return 0 if validation.status == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = []
