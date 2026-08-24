#!/usr/bin/env python3
"""Command line entry for the disposable one-time wiki initializer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wiki_entity_catalog import CatalogError
from wiki_setup_initializer import (
    WikiSetupInitializerError,
    finalize_wiki_setup,
    preview_wiki_setup,
)


ANSWERS_PATH = Path("tmp/wiki-setup-answers.json")


def setup_finalizer_parser() -> argparse.ArgumentParser:
    """Build the two-command parser for the disposable finalizer."""
    parser = argparse.ArgumentParser(description="Preview one-time wiki initialization.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview")
    preview.add_argument("--answers", type=Path, required=True)
    apply = subparsers.add_parser("apply")
    apply.add_argument("--answers", type=Path, required=True)
    apply.add_argument("--approve-digest", required=True)
    return parser


def _require_answers_path(path: Path) -> None:
    if path != ANSWERS_PATH or path.is_absolute():
        raise WikiSetupInitializerError(
            "answers path must be exactly tmp/wiki-setup-answers.json"
        )
    if path.is_symlink():
        raise WikiSetupInitializerError("answers path must not be a symlink")


def main() -> int:
    args = setup_finalizer_parser().parse_args()
    try:
        _require_answers_path(args.answers)
        if args.command == "preview":
            preview = preview_wiki_setup(Path.cwd(), args.answers)
            print(json.dumps(preview.to_dict(), sort_keys=True, separators=(",", ":")))
            return 0 if preview.valid else 2
        result = finalize_wiki_setup(
            Path.cwd(), args.answers, args.approve_digest
        )
        print(json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")))
        return 0 if result.valid else 1
    except (WikiSetupInitializerError, CatalogError) as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
