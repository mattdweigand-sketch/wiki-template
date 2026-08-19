#!/usr/bin/env python3
"""Validate and deterministically render both tracked wiki wrapper surfaces."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("scripts/wiki-wrapper-contract.json")
EXPECTED_NAMES = frozenset(
    {
        "wiki-capture",
        "wiki-eval",
        "wiki-export",
        "wiki-ingest",
        "wiki-lint",
        "wiki-promote",
        "wiki-synthesize",
    }
)
AUTHORIZATIONS = frozenset({"none", "lint-evidence-check"})
TOP_FIELDS = frozenset({"schema_version", "description", "shortcuts"})
SHORTCUT_FIELDS = frozenset(
    {
        "name",
        "workflow_refs",
        "script_hint",
        "claude_description",
        "codex_description",
        "authorization",
        "claude_arguments",
    }
)
NAME_RE = re.compile(r"wiki-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
WORKFLOW_RE = re.compile(r"workflows/[A-Za-z0-9_./-]+\.md\Z")
SCRIPT_HINT_RE = re.compile(r"python3 scripts/[A-Za-z0-9_./-]+\.py(?: [^\n`]*)?\Z")
SCRIPT_REF_RE = re.compile(r"scripts/[A-Za-z0-9_./-]+\.py")


class ContractError(ValueError):
    """The governed wrapper contract or requested render is invalid."""


class DuplicateKeyError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


@dataclass(frozen=True)
class Shortcut:
    name: str
    workflow_refs: tuple[str, ...]
    script_hint: str | None
    claude_description: str
    codex_description: str
    authorization: str
    claude_arguments: bool


@dataclass(frozen=True)
class WrapperContract:
    description: str
    shortcuts: tuple[Shortcut, ...]


def _field_shape(obj: dict[str, object], expected: frozenset[str], label: str) -> list[str]:
    problems: list[str] = []
    missing = expected - set(obj)
    unknown = set(obj) - expected
    if missing:
        problems.append(f"{label}: missing fields: {', '.join(sorted(missing))}")
    if unknown:
        problems.append(f"{label}: unknown fields: {', '.join(sorted(unknown))}")
    return problems


def load_contract(repo_root: Path = REPO_ROOT, contract_path: Path = CONTRACT_PATH) -> WrapperContract:
    path = repo_root / contract_path
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw, object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ContractError(f"cannot parse {contract_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("contract must be a JSON object")
    problems = _field_shape(data, TOP_FIELDS, "contract")
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        problems.append("contract: schema_version must be integer 1")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip() or "workflows/" not in description:
        problems.append("contract: description must be nonempty and name workflows/")
    records = data.get("shortcuts")
    if not isinstance(records, dict):
        problems.append("contract: shortcuts must be an object keyed by shortcut name")
        records = {}
    if set(records) != EXPECTED_NAMES:
        missing = EXPECTED_NAMES - set(records)
        extra = set(records) - EXPECTED_NAMES
        if missing:
            problems.append(f"contract: missing shortcut keys: {', '.join(sorted(missing))}")
        if extra:
            problems.append(f"contract: unknown shortcut keys: {', '.join(sorted(extra))}")

    shortcuts: list[Shortcut] = []
    for key in sorted(records):
        record = records[key]
        label = f"shortcut {key!r}"
        if not isinstance(record, dict):
            problems.append(f"{label}: record must be an object")
            continue
        problems.extend(_field_shape(record, SHORTCUT_FIELDS, label))
        name = record.get("name")
        if name != key:
            problems.append(f"{label}: name {name!r} must match its key")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            problems.append(f"{label}: name must be canonical wiki-* kebab-case")
        refs = record.get("workflow_refs")
        if not isinstance(refs, list) or not refs or not all(isinstance(v, str) for v in refs):
            problems.append(f"{label}: workflow_refs must be a nonempty string list")
            refs = []
        elif len(refs) != len(set(refs)):
            problems.append(f"{label}: workflow_refs must not contain duplicates")
        for ref in refs:
            if not WORKFLOW_RE.fullmatch(ref) or ref.startswith("/") or ".." in Path(ref).parts:
                problems.append(f"{label}: noncanonical workflow path {ref!r}")
            elif not (repo_root / ref).is_file():
                problems.append(f"{label}: workflow target does not exist: {ref}")
        hint = record.get("script_hint")
        if hint is not None and (not isinstance(hint, str) or not SCRIPT_HINT_RE.fullmatch(hint)):
            problems.append(f"{label}: script_hint must be null or one canonical python3 scripts/*.py command")
        elif isinstance(hint, str):
            refs_in_hint = SCRIPT_REF_RE.findall(hint)
            if len(refs_in_hint) != 1:
                problems.append(f"{label}: script_hint must contain exactly one scripts/*.py reference")
            elif not (repo_root / refs_in_hint[0]).is_file():
                problems.append(f"{label}: script target does not exist: {refs_in_hint[0]}")
        claude_description = record.get("claude_description")
        codex_description = record.get("codex_description")
        if not isinstance(claude_description, str) or not claude_description.strip() or "\n" in claude_description:
            problems.append(f"{label}: claude_description must be one nonempty line")
        if not isinstance(codex_description, str) or not codex_description.strip() or "\n" in codex_description:
            problems.append(f"{label}: codex_description must be one nonempty line")
        authorization = record.get("authorization")
        if authorization not in AUTHORIZATIONS:
            problems.append(f"{label}: unknown authorization {authorization!r}")
        arguments = record.get("claude_arguments")
        if not isinstance(arguments, bool):
            problems.append(f"{label}: claude_arguments must be boolean")
        if not problems or not any(p.startswith(label) for p in problems):
            shortcuts.append(
                Shortcut(
                    name=name,
                    workflow_refs=tuple(refs),
                    script_hint=hint,
                    claude_description=claude_description,
                    codex_description=codex_description,
                    authorization=authorization,
                    claude_arguments=arguments,
                )
            )
    if problems:
        raise ContractError("; ".join(problems))
    return WrapperContract(description=description, shortcuts=tuple(shortcuts))


def _title(name: str) -> str:
    return " ".join(part.title() for part in name.split("-"))


def _route_sentence(refs: tuple[str, ...]) -> str:
    rendered = ", then ".join(f"`{ref}`" for ref in refs)
    return f"Read `AGENTS.md`, then `CONTEXT.md`, then {rendered}, and follow the routed Load / Skip list exactly."


def _authorization_line(value: str) -> str:
    if value == "lint-evidence-check":
        return "Invoking this wrapper authorizes only the lint workflow's verifier-agent evidence check.\n"
    return ""


def render_claude(shortcut: Shortcut) -> bytes:
    pieces = [
        "---\n",
        f"description: {shortcut.claude_description}\n",
        "---\n\n",
        f"Run `{shortcut.name}` through the canonical wiki workflow. ",
        _route_sentence(shortcut.workflow_refs),
        "\n",
    ]
    if shortcut.script_hint:
        pieces.append(f"Command hint: `{shortcut.script_hint}`.\n")
    pieces.append(_authorization_line(shortcut.authorization))
    pieces.append("This wrapper is generated from `scripts/wiki-wrapper-contract.json`; canonical behavior lives in `workflows/`.\n")
    if shortcut.claude_arguments:
        pieces.append("\n$ARGUMENTS\n")
    return "".join(pieces).encode("utf-8")


def render_codex(shortcut: Shortcut) -> bytes:
    pieces = [
        "---\n",
        f"name: {shortcut.name}\n",
        f"description: {shortcut.codex_description}\n",
        "---\n\n",
        f"# {_title(shortcut.name)}\n\n",
        f"Run `{shortcut.name}` through the canonical wiki workflow for this repo. ",
        _route_sentence(shortcut.workflow_refs),
        "\n",
    ]
    if shortcut.script_hint:
        pieces.append(f"Command hint: `{shortcut.script_hint}`.\n")
    pieces.append(_authorization_line(shortcut.authorization))
    pieces.append("This wrapper is generated from `scripts/wiki-wrapper-contract.json`; canonical behavior lives in `workflows/`.\n")
    return "".join(pieces).encode("utf-8")


def expected_wrappers(contract: WrapperContract) -> dict[Path, bytes]:
    rendered: dict[Path, bytes] = {}
    for shortcut in contract.shortcuts:
        rendered[Path(".claude/commands") / f"{shortcut.name}.md"] = render_claude(shortcut)
        rendered[Path(".codex/skills") / shortcut.name / "SKILL.md"] = render_codex(shortcut)
    return rendered


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def render_all(repo_root: Path, *, check: bool) -> list[str]:
    contract = load_contract(repo_root)
    expected = expected_wrappers(contract)
    problems: list[str] = []
    for relative, content in sorted(expected.items(), key=lambda pair: pair[0].as_posix()):
        path = repo_root / relative
        try:
            current = path.read_bytes()
        except OSError:
            current = None
        if current == content:
            continue
        if check:
            problems.append(f"stale or missing generated wrapper: {relative.as_posix()}")
        else:
            atomic_write(path, content)
    return problems


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Report byte mismatches without writing.")
    mode.add_argument("--render", action="store_true", help="Render both complete wrapper surfaces.")
    p.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        problems = render_all(args.repo_root.resolve(), check=args.check)
    except ContractError as exc:
        print(f"wrapper contract invalid: {exc}", file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print("Wrapper renders are current." if args.check else "Rendered all wiki wrappers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
