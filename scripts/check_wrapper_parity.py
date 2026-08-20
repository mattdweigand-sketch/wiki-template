#!/usr/bin/env python3
"""Verify generated wiki wrappers and human-facing shortcut name sets."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from render_wiki_wrappers import (
    CONTRACT_PATH,
    ContractError,
    REPO_ROOT,
    expected_wrappers,
    load_contract,
)


README_COMMAND_RE = re.compile(r"^\| `((?:wiki-[a-z0-9-]+))` \|", re.MULTILINE)
AGENTS_LIST_RE = re.compile(r"default wrapped workflows: (?P<list>[^.]+)\.")
BACKTICK_NAME_RE = re.compile(r"`(wiki-[a-z0-9-]+)`")


def _present_wrappers(repo_root: Path, surface: str) -> set[Path]:
    if surface == "claude":
        root = repo_root / ".claude" / "commands"
        return {
            path.relative_to(repo_root)
            for path in root.glob("wiki-*.md")
            if path.is_file()
        } if root.is_dir() else set()
    root = repo_root / ".agents" / "skills"
    return {
        path.relative_to(repo_root)
        for path in root.glob("wiki-*/SKILL.md")
        if path.is_file()
    } if root.is_dir() else set()


def _human_name_problems(repo_root: Path, expected_names: set[str]) -> list[str]:
    problems: list[str] = []
    try:
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        agents = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read README.md or AGENTS.md: {exc}"]
    readme_names = set(README_COMMAND_RE.findall(readme))
    match = AGENTS_LIST_RE.search(agents)
    agents_names = set(BACKTICK_NAME_RE.findall(match.group("list"))) if match else set()
    if readme_names != expected_names:
        problems.append(
            f"README.md shortcut names differ: expected {sorted(expected_names)}, found {sorted(readme_names)}"
        )
    if agents_names != expected_names:
        problems.append(
            f"AGENTS.md shortcut names differ: expected {sorted(expected_names)}, found {sorted(agents_names)}"
        )
    return problems


def wrapper_parity_problems(
    repo_root: Path = REPO_ROOT,
    contract_path: Path = CONTRACT_PATH,
) -> list[str]:
    problems: list[str] = []
    try:
        contract = load_contract(repo_root, contract_path)
    except ContractError as exc:
        return [f"wrapper contract invalid: {exc}"]
    expected = expected_wrappers(contract)
    expected_paths = set(expected)
    present = _present_wrappers(repo_root, "claude") | _present_wrappers(repo_root, "codex")
    for missing in sorted(expected_paths - present):
        problems.append(f"missing generated wrapper: {missing.as_posix()}")
    for extra in sorted(present - expected_paths):
        problems.append(f"unexpected wiki-* wrapper: {extra.as_posix()}")
    for relative in sorted(expected_paths & present):
        try:
            actual = (repo_root / relative).read_bytes()
        except OSError as exc:
            problems.append(f"cannot read wrapper {relative.as_posix()}: {exc}")
            continue
        if actual != expected[relative]:
            problems.append(f"stale generated wrapper: {relative.as_posix()}")
    problems.extend(
        _human_name_problems(repo_root, {shortcut.name for shortcut in contract.shortcuts})
    )
    return problems


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    problems = wrapper_parity_problems()
    if problems:
        print("Wrapper-parity problems found:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Wrapper surfaces are exact deterministic renders and name sets match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
