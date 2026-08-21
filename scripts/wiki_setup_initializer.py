#!/usr/bin/env python3
"""Preview and apply the disposable first-clone wiki initialization."""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from wiki_entity_catalog import (
    CatalogError,
    EntityCatalog,
    load_entity_catalog,
    read_domain_configuration,
)


SETUP_ANSWERS_FIELDS = {
    "schema_version", "context_name", "domain", "preset", "active_types",
    "raw_buckets", "example_queries", "privacy_acknowledged",
}
SETUP_DELETE_PATHS = (
    "SETUP.md",
    "scripts/finalize_wiki_setup.py",
    "scripts/wiki_setup_initializer_test.py",
    "scripts/wiki-setup-presets.json",
    "scripts/wiki_setup_initializer.py",
)
SETUP_WRITE_PATHS = (
    ".github/workflows/wiki-ci.yml",
    "AGENTS.md",
    "CONTEXT.md",
    "README.md",
    "REFERENCES.md",
    "archive/setup/answers.json",
    "archive/setup/finalization-receipt.json",
    "raw/README.md",
    "scripts/document-reachability.json",
    "scripts/raw-buckets.json",
    "scripts/wiki_lint_contract.py",
    "wiki/design-notes.md",
    "wiki/domain.md",
    "wiki/index.md",
    "wiki/log.md",
    "wiki/primer.md",
)
KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_SETUP_MARKER_SYNTAX = ("<!-- ", " -->")
HASH_SETUP_MARKER_SYNTAX = ("# ", "")


class WikiSetupInitializerError(ValueError):
    """The one-time setup answers or template checkout are invalid."""


@dataclass(frozen=True)
class WikiSetupAnswers:
    """Validated answers that the one-time initializer will consume."""

    context_name: str
    domain: str
    preset: str
    active_types: tuple[str, ...]
    raw_buckets: dict[str, str]
    example_queries: tuple[str, ...]


@dataclass(frozen=True)
class WikiSetupPreview:
    """Complete read-only operation list shown before approval."""

    context_name: str
    preset: str
    active_types: tuple[str, ...]
    create_folders: tuple[str, ...]
    remove_folders: tuple[str, ...]
    blocked_removals: tuple[str, ...]
    raw_buckets: tuple[str, ...]
    write_paths: tuple[str, ...]
    delete_paths: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors and not self.blocked_removals

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "context_name": self.context_name,
            "preset": self.preset,
            "active_types": list(self.active_types),
            "create_folders": list(self.create_folders),
            "remove_folders": list(self.remove_folders),
            "blocked_removals": list(self.blocked_removals),
            "raw_buckets": list(self.raw_buckets),
            "create_raw_folders": [f"raw/{value}" for value in self.raw_buckets],
            "write_paths": list(self.write_paths),
            "delete_paths": list(self.delete_paths),
            "errors": list(self.errors),
            "valid": self.valid,
        }


@dataclass(frozen=True)
class WikiSetupResult:
    """Finalization changes and the normal live-wiki validation outcomes."""

    changed_paths: tuple[str, ...]
    validations: tuple[dict[str, object], ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors and all(
            record["exit_code"] == 0 for record in self.validations
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "transaction": "working-tree-changes",
            "changed_paths": list(self.changed_paths),
            "validations": list(self.validations),
            "errors": list(self.errors),
            "valid": self.valid,
        }


def _load_setup_presets(repo_root: Path, catalog: EntityCatalog) -> dict[str, tuple[str, ...]]:
    path = repo_root / "scripts/wiki-setup-presets.json"
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_setup_keys,
        )
    except WikiSetupInitializerError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WikiSetupInitializerError(f"cannot read setup presets: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "presets"}:
        raise WikiSetupInitializerError("setup preset fields differ")
    if raw.get("schema_version") != 1 or isinstance(raw.get("schema_version"), bool):
        raise WikiSetupInitializerError("setup preset schema_version must be integer 1")
    presets_value = raw.get("presets")
    if not isinstance(presets_value, dict) or tuple(presets_value) != (
        "organization", "personal", "hybrid"
    ):
        raise WikiSetupInitializerError("setup presets must be organization, personal, and hybrid")
    catalog_order = tuple(entry.type_name for entry in catalog.entries)
    memberships: dict[str, tuple[str, ...]] = {}
    for name, values in presets_value.items():
        membership = _setup_string_list(values, f"presets.{name}")
        if set(membership) - set(catalog_order):
            raise WikiSetupInitializerError(f"preset {name!r} contains an unknown type")
        if membership != tuple(value for value in catalog_order if value in membership):
            raise WikiSetupInitializerError(f"preset {name!r} order differs from the catalog")
        memberships[name] = membership
    if set(memberships["hybrid"]) != set(catalog_order):
        raise WikiSetupInitializerError("hybrid preset must contain every catalog type")
    return memberships


def _placeholder_only(folder: Path) -> bool:
    if folder.is_symlink():
        return False
    try:
        entries = list(folder.iterdir())
    except OSError:
        return False
    return not entries or (
        len(entries) == 1
        and entries[0].name == ".gitkeep"
        and entries[0].is_file()
        and not entries[0].is_symlink()
    )


def _reject_duplicate_setup_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WikiSetupInitializerError(f"duplicate setup-answer key {key!r}")
        result[key] = value
    return result


def _setup_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise WikiSetupInitializerError(f"{label} must be a nonempty trimmed string")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise WikiSetupInitializerError(f"{label} contains a control character")
    return value


def _setup_string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise WikiSetupInitializerError(f"{label} must be a nonempty string list")
    values = tuple(_setup_text(item, label) for item in value)
    if len(set(values)) != len(values):
        raise WikiSetupInitializerError(f"{label} must not contain duplicates")
    return values


def load_wiki_setup_answers(answers_path: Path) -> WikiSetupAnswers:
    """Load the exact temporary answers file used by preview and apply."""
    try:
        answer_bytes = answers_path.read_bytes()
        raw = json.loads(
            answer_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_setup_keys,
        )
    except WikiSetupInitializerError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WikiSetupInitializerError(f"cannot read setup answers: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != SETUP_ANSWERS_FIELDS:
        raise WikiSetupInitializerError("setup-answer fields differ from the contract")
    canonical = json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8") + b"\n"
    if canonical != answer_bytes:
        raise WikiSetupInitializerError("setup answers must be canonical JSON with one newline")
    if raw.get("schema_version") != 1 or isinstance(raw.get("schema_version"), bool):
        raise WikiSetupInitializerError("schema_version must be integer 1")
    if raw.get("privacy_acknowledged") is not True:
        raise WikiSetupInitializerError("privacy_acknowledged must be true")
    raw_buckets_value = raw.get("raw_buckets")
    if not isinstance(raw_buckets_value, dict) or not raw_buckets_value:
        raise WikiSetupInitializerError("raw_buckets must be a nonempty object")
    if list(raw_buckets_value) != sorted(raw_buckets_value):
        raise WikiSetupInitializerError("raw_buckets must use lexical key order")
    raw_buckets: dict[str, str] = {}
    for name, description in raw_buckets_value.items():
        if not isinstance(name, str) or not KEBAB_CASE_RE.fullmatch(name):
            raise WikiSetupInitializerError(f"raw bucket is not kebab-case: {name!r}")
        raw_buckets[name] = _setup_text(description, f"raw_buckets.{name}")
    queries = _setup_string_list(raw.get("example_queries"), "example_queries")
    if not 3 <= len(queries) <= 5:
        raise WikiSetupInitializerError("example_queries must contain 3 to 5 questions")
    return WikiSetupAnswers(
        context_name=_setup_text(raw.get("context_name"), "context_name"),
        domain=_setup_text(raw.get("domain"), "domain"),
        preset=_setup_text(raw.get("preset"), "preset"),
        active_types=_setup_string_list(raw.get("active_types"), "active_types"),
        raw_buckets=raw_buckets,
        example_queries=queries,
    )


def preview_wiki_setup(
    repo_root: Path,
    answers_path: Path,
    catalog: Optional[EntityCatalog] = None,
) -> WikiSetupPreview:
    """Calculate the complete one-way setup effect without writing."""
    root = repo_root.resolve()
    answers = load_wiki_setup_answers(answers_path)
    entity_catalog = catalog or load_entity_catalog(root / "scripts/entity-catalog.json")
    presets = _load_setup_presets(root, entity_catalog)
    errors: list[str] = []
    try:
        domain = read_domain_configuration(root)
        if domain.status != "unconfigured":
            errors.append("wiki is already configured; setup cannot run again")
    except CatalogError as exc:
        errors.append(str(exc))
    if answers.preset not in presets:
        errors.append(f"unknown setup preset {answers.preset!r}")
    catalog_order = tuple(entry.type_name for entry in entity_catalog.entries)
    unknown_types = sorted(set(answers.active_types) - set(catalog_order))
    if unknown_types:
        errors.append("unsupported active types: " + ", ".join(unknown_types))
    active_types = tuple(value for value in catalog_order if value in answers.active_types)
    if answers.active_types != active_types:
        errors.append("active_types must follow catalog order")
    try:
        _render_live_documents(root, answers, date.today().isoformat())
    except WikiSetupInitializerError as exc:
        errors.append(str(exc))
    active_folders = {entity_catalog.type_folders[value] for value in active_types}
    existing_folders = {
        path.name for path in (root / "wiki").iterdir()
        if path.is_dir() and path.name in entity_catalog.folder_types
    }
    inactive = sorted(existing_folders - active_folders)
    remove_folders = tuple(
        folder for folder in inactive if _placeholder_only(root / "wiki" / folder)
    )
    blocked_removals = tuple(
        folder for folder in inactive if not _placeholder_only(root / "wiki" / folder)
    )
    return WikiSetupPreview(
        context_name=answers.context_name,
        preset=answers.preset,
        active_types=active_types,
        create_folders=tuple(sorted(active_folders - existing_folders)),
        remove_folders=remove_folders,
        blocked_removals=blocked_removals,
        raw_buckets=tuple(answers.raw_buckets),
        write_paths=SETUP_WRITE_PATHS,
        delete_paths=SETUP_DELETE_PATHS + ("tmp/wiki-setup-answers.json",),
        errors=tuple(dict.fromkeys(errors)),
    )


def _git_output(repo_root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise WikiSetupInitializerError("setup requires a normal Git clone")
    return process.stdout.strip()


def _render_domain_page(answers: WikiSetupAnswers, finalized_on: str) -> str:
    active = "\n".join(f"  - {value}" for value in answers.active_types)
    buckets = "\n".join(f"  - {value}" for value in answers.raw_buckets)
    queries = "\n".join(
        f"  - {json.dumps(value, ensure_ascii=False)}"
        for value in answers.example_queries
    )
    return (
        "---\n"
        "title: Domain Config\n"
        "type: domain\n"
        f"created: {finalized_on}\n"
        f"updated: {finalized_on}\n"
        "status: configured\n"
        f"org: {json.dumps(answers.context_name, ensure_ascii=False)}\n"
        f"domain: {json.dumps(answers.domain, ensure_ascii=False)}\n"
        "entity_types_active:\n"
        f"{active}\n"
        "raw_buckets:\n"
        f"{buckets}\n"
        "example_queries:\n"
        f"{queries}\n"
        "---\n\n"
        "# Domain Config\n\n"
        f"This wiki is the durable context layer for {answers.context_name}.\n"
    )


def _render_raw_readme(answers: WikiSetupAnswers) -> str:
    rows = "\n".join(
        f"| `{name}/` | {description.replace('|', '&#124;')} |"
        for name, description in answers.raw_buckets.items()
    )
    return (
        "# raw/\n\n"
        "Source artifacts live here. Put each new source in the matching bucket, "
        "then treat its bytes as immutable.\n\n"
        "This wiki assumes a private Git repository whose access is limited "
        "to the wiki's intended users. Source artifacts are tracked with the rest "
        "of the repository and may be pushed to its remote. Review sensitive files "
        "before adding or pushing them.\n\n"
        "## Subfolders\n\n"
        "| Folder | Holds |\n|---|---|\n"
        f"{rows}\n"
    )


def _configured_wiki_title(context_name: str) -> str:
    """Append Wiki only when the configured context name does not already include it."""
    return context_name if context_name.casefold().endswith(" wiki") else f"{context_name} Wiki"


def _replace_single_wiki_setup_block(
    text: str,
    marker_name: str,
    replacement: str,
    marker_syntax: tuple[str, str] = MARKDOWN_SETUP_MARKER_SYNTAX,
) -> str:
    """Replace one named setup-owned block and reject marker drift."""
    prefix, suffix = marker_syntax
    start_marker = f"{prefix}wiki-setup:{marker_name}:start{suffix}"
    end_marker = f"{prefix}wiki-setup:{marker_name}:end{suffix}"
    start_count = text.count(start_marker)
    end_count = text.count(end_marker)
    if start_count != 1 or end_count != 1:
        raise WikiSetupInitializerError(
            f"setup marker {marker_name!r} must have exactly one start and one end; "
            f"found {start_count} start and {end_count} end"
        )
    start = text.index(start_marker)
    end = text.index(end_marker)
    if end < start:
        raise WikiSetupInitializerError(
            f"setup marker {marker_name!r} ends before it starts"
        )
    return text[:start] + replacement + text[end + len(end_marker):]


def _replace_single_wiki_setup_line(
    text: str,
    marker_name: str,
    replacement: str,
    marker_syntax: tuple[str, str] = MARKDOWN_SETUP_MARKER_SYNTAX,
) -> str:
    """Replace one setup-owned line without depending on its human-readable text."""
    prefix, suffix = marker_syntax
    marker = f"{prefix}wiki-setup:{marker_name}:line{suffix}"
    marker_count = text.count(marker)
    if marker_count != 1:
        raise WikiSetupInitializerError(
            f"setup line marker {marker_name!r} must appear exactly once; "
            f"found {marker_count}"
        )
    marker_index = text.index(marker)
    line_start = text.rfind("\n", 0, marker_index) + 1
    line_end = text.find("\n", marker_index)
    if line_end < 0:
        line_end = len(text)
        suffix_text = ""
    else:
        line_end += 1
        suffix_text = text[line_end:]
    replacement_line = replacement.rstrip("\n") + "\n" if replacement else ""
    return text[:line_start] + replacement_line + suffix_text


def _remove_single_setup_path_line(text: str, path_token: str, document: str) -> str:
    """Remove one structural path row without depending on its description."""
    lines = text.splitlines(keepends=True)
    matching_indexes = [index for index, line in enumerate(lines) if path_token in line]
    if len(matching_indexes) != 1:
        raise WikiSetupInitializerError(
            f"{document} must contain exactly one structural line for {path_token!r}; "
            f"found {len(matching_indexes)}"
        )
    del lines[matching_indexes[0]]
    return "".join(lines)


def _render_live_readme(text: str, answers: WikiSetupAnswers) -> str:
    wiki_title = _configured_wiki_title(answers.context_name)
    text = _replace_single_wiki_setup_block(
        text,
        "readme-identity",
        f"# {wiki_title}\n\n"
        f"An agent-readable wiki for {answers.domain}, based on the "
        "[Karpathy LLM-wiki pattern]"
        "(https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).",
    )
    text = _replace_single_wiki_setup_block(
        text,
        "readme-getting-started",
        "## Getting Started\n\n"
        "The deterministic tooling requires Python 3.9 or newer and `ripgrep` (`rg`).\n\n"
        "1. Add source files under `raw/`.\n"
        "2. Ask an agent to ingest them.\n"
        "3. Ask questions in plain language.\n",
    )
    text = _replace_single_wiki_setup_block(text, "readme-agent-setup-prompt", "")
    text = _replace_single_wiki_setup_line(
        text,
        "readme-private-repository",
        "1. **Preserve the evidence.** Original files, notes, transcripts, and "
        "exported source files live in `raw/`. Once added, they are treated as "
        "read-only so later conclusions can always be traced back to the source. "
        "This wiki assumes a private Git repository whose access is limited to its "
        "intended users. Git tracks raw files with the rest of the wiki, so review "
        "sensitive material before pushing them to any remote.",
    )
    text = _replace_single_wiki_setup_line(
        text,
        "readme-source-pages",
        "2. **Turn sources into wiki pages.** When the `source` type is active, "
        "each important source gets a page in `wiki/sources/`. Other pages cite "
        "those source pages instead of relying on loose files, memory, or uncaptured "
        "links.",
    )
    text = _replace_single_wiki_setup_line(
        text,
        "readme-ci-row",
        "| CI checks | GitHub Actions validates repository mechanics on pushes and pull requests. |",
    )
    text = _replace_single_wiki_setup_line(
        text,
        "readme-route-row",
        "| Route-first workflows | Point agents from `AGENTS.md` through "
        "`wiki/domain.md`, then to `CONTEXT.md` and the routed workflow. |",
    )
    text = _remove_single_setup_path_line(
        text, "|-- SETUP.md", "README.md repository tree"
    )
    text = _replace_single_wiki_setup_block(
        text,
        "readme-configuration",
        "## Domain\n\n"
        "[`wiki/domain.md`](wiki/domain.md) records what this wiki covers and which entity types are active. "
        "[`wiki/SCHEMA.md`](wiki/SCHEMA.md) defines the available page types and page rules.\n",
    )
    return text


def _render_live_agents(text: str, answers: WikiSetupAnswers) -> str:
    wiki_title = _configured_wiki_title(answers.context_name)
    text = _replace_single_wiki_setup_block(
        text,
        "agents-identity",
        f"# {wiki_title}\n\n"
        f"An agent-readable durable context layer for {answers.domain}. Grounded in "
        "sources. Structured for downstream agents. Designed to compound instead of "
        "re-deriving context from raw documents.\n\n"
        "`AGENTS.md` is canonical and agent-agnostic. Codex, Cursor, Claude, ChatGPT, "
        "or a raw API harness should drive this wiki the same way: read `AGENTS.md`, "
        "check `wiki/domain.md`, route through `CONTEXT.md`, then follow the "
        "vendor-neutral prose in `workflows/`. Claude Code reaches the same guidance "
        "through the thin `CLAUDE.md` wrapper and tracked `.claude/commands/`. Codex "
        "reaches the same guidance through tracked repo-local `.agents/skills/` "
        "wrappers. Nothing about core operation depends on either wrapper surface.\n\n"
        "Read `wiki/domain.md`, then continue through `CONTEXT.md`.",
    )
    text = _replace_single_wiki_setup_line(text, "agents-setup-file", "")
    text = _replace_single_wiki_setup_block(text, "agents-initializer-files", "")
    text = _replace_single_wiki_setup_line(
        text,
        "agents-private-repository",
        "- `raw/` - tracked source artifacts in the wiki's intended "
        "private-repository operating model. Existing files are immutable, and new "
        "user-provided sources may be placed once during ingest before becoming "
        "immutable. Review sensitive content before adding or pushing it.",
    )
    text = _replace_single_wiki_setup_line(
        text,
        "agents-entity-folder",
        "- `wiki/<entity-type>/` - one folder per active entity type.",
    )
    text = _replace_single_wiki_setup_line(
        text,
        "agents-catalog-selection",
        "The active folders come from this governed catalog. Adding a type outside it "
        "requires an explicit schema, tooling, documentation, and evaluation change.",
    )
    text = _replace_single_wiki_setup_block(
        text,
        "agents-capture-free-routes",
        "Every other route skips the gate, including ordinary source ingest, routine "
        "page updates, decision capture, experience capture, and workflow updates, "
        "unless the work is part of one of those approval boundaries.",
    )
    text = _replace_single_wiki_setup_block(
        text,
        "agents-session-start",
        "## Session Start\n\n"
        "1. Read this file.\n"
        "2. Read `wiki/domain.md` for the configured context and active types.\n"
        "3. Read `CONTEXT.md` to route the task.\n"
        "4. Open the routed workspace and follow its Load / Skip list.\n",
    )
    text = _replace_single_wiki_setup_block(
        text,
        "agents-raw-bucket-lint",
        "Repo structure is linted. `scripts/lint.py --tier1` fails on unknown "
        "repo-root entries, unknown `wiki/` root entries, unknown top-level `raw/` "
        "buckets, loose top-level `raw/` or `deliverables/` files, non-kebab-case "
        "`deliverables/` subfolders, and Finder `.DS_Store` metadata outside `.git`. "
        "Fix those as structural violations; do not work around them.",
    )
    return text


def _render_live_documents(
    repo_root: Path,
    answers: WikiSetupAnswers,
    finalized_on: str,
) -> dict[str, str]:
    documents: dict[str, str] = {}
    documents["AGENTS.md"] = _render_live_agents(
        (repo_root / "AGENTS.md").read_text(encoding="utf-8"), answers
    )
    context = (repo_root / "CONTEXT.md").read_text(encoding="utf-8")
    context = _replace_single_wiki_setup_block(
        context,
        "context-identity",
        f"# {_configured_wiki_title(answers.context_name)} - Task Router",
    )
    context = _replace_single_wiki_setup_block(
        context,
        "context-status-routing",
        "Start with `AGENTS.md`, read `wiki/domain.md`, then read this file and "
        "open the selected workspace `CONTEXT.md`.",
    )
    context = _replace_single_wiki_setup_line(context, "context-setup-route", "")
    documents["CONTEXT.md"] = context
    documents["README.md"] = _render_live_readme(
        (repo_root / "README.md").read_text(encoding="utf-8"), answers
    )
    references = (repo_root / "REFERENCES.md").read_text(encoding="utf-8")
    references = _replace_single_wiki_setup_line(
        references, "references-setup-workflow", ""
    )
    references = _replace_single_wiki_setup_line(
        references, "references-initializer-files", ""
    )
    references = _replace_single_wiki_setup_line(
        references,
        "references-domain-summary",
        "| `wiki/domain.md` | Context name, scope, active entity types, and raw buckets |",
    )
    references = _replace_single_wiki_setup_line(
        references,
        "references-layer-one",
        "| **L1** | Route entry: selected by task | `CONTEXT.md` and then "
        "`workflows/<workspace>/CONTEXT.md`; `wiki/index.md` only for browsing |",
    )
    references = _replace_single_wiki_setup_block(
        references,
        "references-loading-principle",
        "Loading principle: an agent starting a task should load L0. Use "
        "`CONTEXT.md` to choose the route, then open only the routed workflow's "
        "Load / Skip list. Pull L3 references only when the workflow calls for "
        "them. `wiki/index.md` is on-demand for browsing, research, promotion, "
        "explicit lookup, and ingest link/index steps; it is not startup context.",
    )
    documents["REFERENCES.md"] = references
    primer = (repo_root / "wiki/primer.md").read_text(encoding="utf-8")
    primer = _replace_single_wiki_setup_line(
        primer,
        "primer-status-route",
        "1. Read [`domain.md`](domain.md) for the configured context and active "
        "types.",
    )
    documents["wiki/primer.md"] = primer
    index = (repo_root / "wiki/index.md").read_text(encoding="utf-8")
    documents["wiki/index.md"] = _replace_single_wiki_setup_line(
        index,
        "index-domain-summary",
        "| [domain.md](domain.md) | Configured context, active entity types, raw "
        "buckets, and example queries |",
    )
    design = (repo_root / "wiki/design-notes.md").read_text(encoding="utf-8")
    design = _replace_single_wiki_setup_block(
        design, "design-initializer-decision", ""
    )
    design = _replace_single_wiki_setup_block(
        design,
        "design-catalog-owner",
        "Chosen seam: `scripts/entity-catalog.json` defines the exact 24 supported\n"
        "entity records, while `scripts/wiki_entity_catalog.py` is the only production\n"
        "interface for loading and validating the catalog, looking up folder/type pairs,\n"
        "and validating configured layouts. Lint, parity, and eval code call that\n"
        "interface.",
    )
    design = _replace_single_wiki_setup_block(
        design,
        "design-configured-layout",
        "A configured wiki contains exactly the folders mapped from its explicit active\n"
        "types. The live catalog contains only runtime folder/type mappings and authoring\n"
        "guidance.",
    )
    documents["wiki/design-notes.md"] = design
    lint_contract = (repo_root / "scripts/wiki_lint_contract.py").read_text(
        encoding="utf-8"
    )
    documents["scripts/wiki_lint_contract.py"] = _replace_single_wiki_setup_block(
        lint_contract,
        "lint-contract-setup-root",
        "",
        HASH_SETUP_MARKER_SYNTAX,
    )
    ci = (repo_root / ".github/workflows/wiki-ci.yml").read_text(encoding="utf-8")
    ci = _replace_single_wiki_setup_block(
        ci,
        "ci-initializer-test",
        "",
        HASH_SETUP_MARKER_SYNTAX,
    )
    documents[".github/workflows/wiki-ci.yml"] = ci
    log = (repo_root / "wiki/log.md").read_text(encoding="utf-8")
    documents["wiki/log.md"] = _replace_single_wiki_setup_block(
        log,
        "log-template-entry",
        f"## {finalized_on} | wiki initialized\n\n"
        f"Context: {answers.context_name}\n\n"
        f"Domain: {answers.domain}\n\n"
        f"Active entity types: {', '.join(answers.active_types)}\n",
    )
    marker_residue = sorted(
        relative for relative, content in documents.items() if "wiki-setup:" in content
    )
    if marker_residue:
        raise WikiSetupInitializerError(
            "unconsumed setup markers remain in: " + ", ".join(marker_residue)
        )
    return documents


def _run_live_validations(repo_root: Path) -> tuple[dict[str, object], ...]:
    commands = (
        (sys.executable, "scripts/wiki_eval.py"),
        (sys.executable, "scripts/lint.py", "--tier1"),
    )
    records: list[dict[str, object]] = []
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for command in commands:
        process = subprocess.run(
            list(command), cwd=repo_root, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        records.append({
            "argv": list(command),
            "exit_code": process.returncode,
            "stdout_sha256": hashlib.sha256(process.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(process.stderr).hexdigest(),
        })
    return tuple(records)


def finalize_wiki_setup(
    repo_root: Path,
    answers_path: Path,
) -> WikiSetupResult:
    """Apply the approved initializer once and leave ordinary Git changes."""
    root = repo_root.resolve()
    preview = preview_wiki_setup(root, answers_path)
    if not preview.valid:
        raise WikiSetupInitializerError(
            "setup preview is blocked: "
            + "; ".join(preview.errors + preview.blocked_removals)
        )
    if _git_output(root, "status", "--porcelain", "--untracked-files=no"):
        raise WikiSetupInitializerError(
            "tracked worktree changes must be committed or restored first"
        )
    if (root / "archive/setup").exists():
        raise WikiSetupInitializerError("archive/setup already exists")
    for relative in SETUP_DELETE_PATHS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise WikiSetupInitializerError(f"setup path is missing or unsafe: {relative}")
    answers = load_wiki_setup_answers(answers_path)
    finalized_on = date.today().isoformat()
    live_documents = _render_live_documents(root, answers, finalized_on)
    template_commit = _git_output(root, "rev-parse", "HEAD")
    answer_bytes = answers_path.read_bytes()
    changed: set[str] = set()

    (root / "wiki/domain.md").write_text(
        _render_domain_page(answers, finalized_on), encoding="utf-8"
    )
    changed.add("wiki/domain.md")
    for relative, content in live_documents.items():
        (root / relative).write_text(content, encoding="utf-8")
        changed.add(relative)
    (root / "raw/README.md").write_text(_render_raw_readme(answers), encoding="utf-8")
    changed.add("raw/README.md")
    raw_registry = {
        "description": "Canonical raw source-artifact bucket taxonomy for this wiki.",
        "policy": "Raw source artifacts are immutable and may be tracked with the rest of the wiki.",
        "buckets": answers.raw_buckets,
    }
    (root / "scripts/raw-buckets.json").write_text(
        json.dumps(raw_registry, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    changed.add("scripts/raw-buckets.json")
    for folder in answers.raw_buckets:
        (root / "raw" / folder).mkdir(exist_ok=True)
    for folder in preview.create_folders:
        destination = root / "wiki" / folder
        destination.mkdir()
        (destination / ".gitkeep").write_bytes(b"")
        changed.add(f"wiki/{folder}/.gitkeep")
    for folder in preview.remove_folders:
        destination = root / "wiki" / folder
        if not _placeholder_only(destination):
            raise WikiSetupInitializerError(
                f"inactive entity folder changed after preview: {folder}"
            )
        placeholder = destination / ".gitkeep"
        if placeholder.exists():
            placeholder.unlink()
            changed.add(f"wiki/{folder}/.gitkeep")
        destination.rmdir()

    manifest_path = root / "scripts/document-reachability.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["roots"] = [value for value in manifest["roots"] if value != "SETUP.md"]
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    changed.add("scripts/document-reachability.json")

    archive = root / "archive/setup"
    archive.mkdir(parents=True)
    (archive / "answers.json").write_bytes(answer_bytes)
    receipt = {
        "schema_version": 1,
        "template_commit": template_commit,
        "finalized_on": finalized_on,
        "context_name": answers.context_name,
        "answers_sha256": hashlib.sha256(answer_bytes).hexdigest(),
        "history_preserved": True,
    }
    (archive / "finalization-receipt.json").write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    changed.update(("archive/setup/answers.json", "archive/setup/finalization-receipt.json"))
    for relative in SETUP_DELETE_PATHS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise WikiSetupInitializerError(f"setup path is missing or unsafe: {relative}")
        path.unlink()
        changed.add(relative)
    answers_path.unlink()
    changed.add("tmp/wiki-setup-answers.json")
    validations = _run_live_validations(root)
    errors = tuple(
        "live validation failed: " + " ".join(record["argv"])
        for record in validations if record["exit_code"] != 0
    )
    return WikiSetupResult(
        changed_paths=tuple(sorted(changed)),
        validations=validations,
        errors=errors,
    )


__all__ = [
    "SETUP_DELETE_PATHS",
    "SETUP_WRITE_PATHS",
    "WikiSetupAnswers",
    "WikiSetupInitializerError",
    "WikiSetupPreview",
    "WikiSetupResult",
    "finalize_wiki_setup",
    "load_wiki_setup_answers",
    "preview_wiki_setup",
]
