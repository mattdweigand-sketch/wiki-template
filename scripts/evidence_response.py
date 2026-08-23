#!/usr/bin/env python3
"""Create or render one evidence-backed response packet."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _evidence_fidelity import load_json, safe_run_dir
from wiki_evidence import (
    EvidenceResponseStatement,
    EvidenceRunError,
    create_evidence_response_packet,
    render_verified_evidence_response,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("create", "render"):
        command = commands.add_parser(name)
        command.add_argument("--run-dir", required=True, type=Path)
        command.add_argument(
            "--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS
        )
    return result


def _load_response_draft(
    repo_root: Path,
    run_dir: Path,
) -> tuple[str, tuple[EvidenceResponseStatement, ...]]:
    resolved_run = safe_run_dir(repo_root.resolve(), run_dir.as_posix())
    payload = load_json(resolved_run / "response-draft.json")
    if not isinstance(payload, dict) or set(payload) != {"question", "statements"}:
        raise EvidenceRunError("response-draft.json fields must be question and statements")
    question = payload.get("question")
    raw_statements = payload.get("statements")
    if not isinstance(question, str) or not isinstance(raw_statements, list):
        raise EvidenceRunError("response-draft.json has invalid question or statements")
    statements: list[EvidenceResponseStatement] = []
    for index, item in enumerate(raw_statements, start=1):
        if not isinstance(item, dict) or set(item) != {"text", "claim_ids"}:
            raise EvidenceRunError(f"response draft statement {index} fields are invalid")
        text = item.get("text")
        claim_ids = item.get("claim_ids")
        if not isinstance(text, str) or not isinstance(claim_ids, list) or not all(
            isinstance(claim_id, str) for claim_id in claim_ids
        ):
            raise EvidenceRunError(f"response draft statement {index} is invalid")
        statements.append(EvidenceResponseStatement(text=text, claim_ids=tuple(claim_ids)))
    return question, tuple(statements)


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "create":
            question, statements = _load_response_draft(args.repo_root, args.run_dir)
            path = create_evidence_response_packet(
                args.repo_root, args.run_dir, question, statements
            )
            print(f"Created {path.relative_to(args.repo_root.resolve())}")
            return 0
        sys.stdout.write(render_verified_evidence_response(args.repo_root, args.run_dir))
        return 0
    except (EvidenceRunError, OSError) as exc:
        print(f"evidence_response.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = []
