#!/usr/bin/env python3
"""Render a deterministic, read-only wiki setup plan as JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wiki_entity_catalog import CatalogError, load_entity_catalog, plan_wiki_setup


def setup_plan_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an entity preset and calculate folder changes without writing."
    )
    parser.add_argument("--repo-root", default=".", help="Wiki repository root to inspect.")
    parser.add_argument("--preset", required=True, help="Supported catalog preset.")
    parser.add_argument(
        "--active",
        action="append",
        default=[],
        help="Comma-separated active type names; repeatable. Defaults to the preset.",
    )
    return parser


def _requested_types(values: list[str]) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for value in values
        for item in value.split(",")
        if item.strip()
    )


def main() -> int:
    args = setup_plan_parser().parse_args()
    try:
        catalog = load_entity_catalog()
        plan = plan_wiki_setup(
            Path(args.repo_root).resolve(),
            catalog,
            selected_preset=args.preset,
            requested_active_types=_requested_types(args.active),
        )
        payload = {
            "active_types": list(plan.active_types),
            "advisories": list(plan.advisories),
            "blocked_removals": list(plan.blocked_removals),
            "create_folders": list(plan.create_folders),
            "configuration_version": plan.configuration_version,
            "errors": list(plan.errors),
            "remove_folders": list(plan.remove_folders),
            "selected_preset": plan.selected_preset,
            "valid": plan.valid,
        }
    except CatalogError as exc:
        payload = {
            "active_types": [],
            "advisories": [],
            "blocked_removals": [],
            "create_folders": [],
            "configuration_version": 2,
            "errors": [str(exc)],
            "remove_folders": [],
            "selected_preset": args.preset,
            "valid": False,
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
