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
        "Only `.gitkeep` and this README are tracked. Source artifacts remain "
        "gitignored and are included only in explicit exports.\n\n"
        "## Subfolders\n\n"
        "| Folder | Holds |\n|---|---|\n"
        f"{rows}\n"
    )


def _remove_markdown_section(text: str, heading: str) -> str:
    start = text.find(heading + "\n")
    if start < 0:
        return text
    next_heading = text.find("\n## ", start + len(heading))
    if next_heading < 0:
        return text[:start].rstrip() + "\n"
    return text[:start].rstrip() + "\n\n" + text[next_heading + 1:]


def _render_live_readme(text: str, answers: WikiSetupAnswers) -> str:
    text = text.replace("# <Organization> Wiki", f"# {answers.context_name} Wiki", 1)
    text = text.replace(
        "A clonable, agent-readable wiki template for company, project, or personal context, based on the [Karpathy LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).",
        f"An agent-readable wiki for {answers.domain}, based on the [Karpathy LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).",
    )
    shortcut_start = text.find("The repo has seven common workflow shortcuts.")
    shortcut_end = text.find("\n---", shortcut_start)
    shortcut_block = ""
    if shortcut_start >= 0 and shortcut_end > shortcut_start:
        shortcut_block = text[shortcut_start:shortcut_end].strip() + "\n\n"
    text = _remove_markdown_section(text, "## Agent Setup Prompt")
    text = _remove_markdown_section(text, "## Getting Started")
    how_it_works = "## How It Works"
    live_start = (
        "## Getting Started\n\n"
        "The deterministic tooling requires Python 3.9 or newer and `ripgrep` (`rg`).\n\n"
        "1. Add source files under `raw/`.\n"
        "2. Ask an agent to ingest them.\n"
        "3. Ask questions in plain language.\n\n"
    )
    text = text.replace(how_it_works, live_start + shortcut_block + how_it_works, 1)
    text = re.sub(
        r"^\| (?:Setup and CI checks|One-time initialization and CI) \|.*$",
        "| CI checks | GitHub Actions validates repository mechanics on pushes and pull requests. |",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"^\|-- SETUP\.md.*\n", "", text, flags=re.MULTILINE)
    text = _remove_markdown_section(text, "## Configuration")
    domain_section = (
        "## Domain\n\n"
        "[`wiki/domain.md`](wiki/domain.md) records what this wiki covers and which entity types are active. "
        "[`wiki/SCHEMA.md`](wiki/SCHEMA.md) defines the available page types and page rules.\n\n"
    )
    text = text.replace("## Credits", domain_section + "## Credits", 1)
    return text


def _render_live_agents(text: str, answers: WikiSetupAnswers) -> str:
    text = text.replace("# <Organization> Wiki", f"# {answers.context_name} Wiki", 1)
    text = text.replace(
        "A clonable, agent-readable wiki template for an organization, project, or person's durable context layer.",
        f"An agent-readable durable context layer for {answers.domain}.",
    )
    text = text.replace(
        "read `AGENTS.md`, check `wiki/domain.md` for setup status, route through `CONTEXT.md`",
        "read `AGENTS.md`, check `wiki/domain.md`, route through `CONTEXT.md`",
    )
    text = re.sub(
        r"^Start by reading `wiki/domain\.md`.*\n",
        "Read `wiki/domain.md`, then continue through `CONTEXT.md`.\n",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(r"^- `SETUP\.md`.*\n", "", text, flags=re.MULTILINE)
    text = text.replace(
        " `finalize_wiki_setup.py` and `wiki_setup_initializer.py` are disposable "
        "initializer files removed after approved setup.",
        "",
    )
    text = text.replace(
        "Setup selects from this governed catalog.",
        "The active folders come from this governed catalog.",
    )
    text = text.replace("workflow updates, and setup updates", "and workflow updates")
    session_start = text.find("## Session Start\n")
    if session_start >= 0:
        session_end = text.find("\n---", session_start)
        if session_end >= 0:
            replacement = (
                "## Session Start\n\n"
                "1. Read this file.\n"
                "2. Read `wiki/domain.md` for the configured context and active types.\n"
                "3. Read `CONTEXT.md` to route the task.\n"
                "4. Open the routed workspace and follow its Load / Skip list.\n"
            )
            text = text[:session_start] + replacement + text[session_end:]
    text = text.replace("unknown top-level `raw/` buckets after setup", "unknown top-level `raw/` buckets")
    return text


def _render_live_documents(repo_root: Path, answers: WikiSetupAnswers) -> dict[str, str]:
    documents: dict[str, str] = {}
    documents["AGENTS.md"] = _render_live_agents(
        (repo_root / "AGENTS.md").read_text(encoding="utf-8"), answers
    )
    context = (repo_root / "CONTEXT.md").read_text(encoding="utf-8")
    context = context.replace("check `wiki/domain.md` for setup status, ", "read `wiki/domain.md`, ")
    context = re.sub(r"^\| Configure a fresh clone \|.*\n", "", context, flags=re.MULTILINE)
    documents["CONTEXT.md"] = context
    documents["README.md"] = _render_live_readme(
        (repo_root / "README.md").read_text(encoding="utf-8"), answers
    )
    references = (repo_root / "REFERENCES.md").read_text(encoding="utf-8")
    references = re.sub(r"^\| One-time initialization \|.*\n", "", references, flags=re.MULTILINE)
    references = re.sub(r"^\| `scripts/finalize_wiki_setup\.py`.*\n", "", references, flags=re.MULTILINE)
    references = references.replace(
        "Context name, scope, active entity types, raw buckets, and "
        "template/configured status",
        "Context name, scope, active entity types, and raw buckets",
    )
    references = references.replace(
        "`workflows/<workspace>/CONTEXT.md`, one-time `SETUP.md`, or "
        "`wiki/index.md` only for browsing",
        "`workflows/<workspace>/CONTEXT.md` or `wiki/index.md` only for browsing",
    )
    documents["REFERENCES.md"] = references
    primer = (repo_root / "wiki/primer.md").read_text(encoding="utf-8")
    primer = primer.replace("Setup state, schema", "Domain declaration, schema")
    primer = primer.replace("configured raw taxonomy", "configured raw buckets")
    primer = re.sub(
        r"^1\. Check \[`domain\.md`\].*\n",
        "1. Read [`domain.md`](domain.md) for the configured context and active "
        "types.\n",
        primer,
        flags=re.MULTILINE,
    )
    primer = primer.replace("such as setup, ingest, capture", "such as ingest, capture")
    documents["wiki/primer.md"] = primer
    index = (repo_root / "wiki/index.md").read_text(encoding="utf-8")
    documents["wiki/index.md"] = index.replace(
        "Template status, configured context, active entity types, raw buckets, and example queries",
        "Configured context, active entity types, raw buckets, and example queries",
    )
    design = (repo_root / "wiki/design-notes.md").read_text(encoding="utf-8")
    initializer_start = design.find("## 2026-08-20: One-Time Wiki Initialization")
    catalog_start = design.find("## 2026-08-19: Governed Entity Catalog")
    if initializer_start >= 0 and catalog_start > initializer_start:
        design = design[:initializer_start] + design[catalog_start:]
    design = design.replace(
        "interface. Setup presets live only in the disposable initializer.\n",
        "interface.\n",
    )
    design = design.replace(
        "The live\ncatalog has no presets, migration mode, or reconfiguration behavior.\n",
        "The live catalog contains only runtime folder/type mappings and authoring\n"
        "guidance.\n",
    )
    documents["wiki/design-notes.md"] = design
    lint_contract = (repo_root / "scripts/wiki_lint_contract.py").read_text(
        encoding="utf-8"
    )
    documents["scripts/wiki_lint_contract.py"] = lint_contract.replace(
        '    "README.md", "REFERENCES.md", "SETUP.md",\n',
        '    "README.md", "REFERENCES.md",\n',
    )
    ci = (repo_root / ".github/workflows/wiki-ci.yml").read_text(encoding="utf-8")
    ci = ci.replace(
        "      - name: Test one-time initializer\n"
        "        run: PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/wiki_setup_initializer_test.py\n\n",
        "",
    )
    documents[".github/workflows/wiki-ci.yml"] = ci
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
    template_commit = _git_output(root, "rev-parse", "HEAD")
    answer_bytes = answers_path.read_bytes()
    changed: set[str] = set()

    (root / "wiki/domain.md").write_text(
        _render_domain_page(answers, finalized_on), encoding="utf-8"
    )
    changed.add("wiki/domain.md")
    for relative, content in _render_live_documents(root, answers).items():
        (root / relative).write_text(content, encoding="utf-8")
        changed.add(relative)
    (root / "raw/README.md").write_text(_render_raw_readme(answers), encoding="utf-8")
    changed.add("raw/README.md")
    raw_registry = {
        "description": "Canonical raw source-artifact bucket taxonomy for this wiki.",
        "policy": "Raw source artifacts are immutable, gitignored, and included only in explicit exports.",
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
    log_path = root / "wiki/log.md"
    log_text = log_path.read_text(encoding="utf-8")
    template_entry = (
        "\n---\n\n## [2026-05-17] template initialized\n\n"
        "Template state. Awaiting domain configuration — see "
        "[`SETUP.md`](../SETUP.md) and [`domain.md`](domain.md).\n"
    )
    if not log_text.endswith(template_entry):
        raise WikiSetupInitializerError("wiki/log.md lacks the expected template entry")
    log_path.write_text(
        log_text[:-len(template_entry)].rstrip()
        + f"\n\n---\n\n## {finalized_on} | wiki initialized\n\n"
        + f"Context: {answers.context_name}\n\n"
        + f"Domain: {answers.domain}\n\n"
        + f"Active entity types: {', '.join(answers.active_types)}\n",
        encoding="utf-8",
    )
    changed.add("wiki/log.md")
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
