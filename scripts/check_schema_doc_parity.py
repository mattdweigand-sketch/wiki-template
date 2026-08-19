#!/usr/bin/env python3
"""Verify schema vocabulary docs stay in parity with the lint contract.

The frontmatter vocabularies are canonical in scripts/wiki_lint_contract.py and
re-exported by the stable scripts/lint.py facade.
The documentation enumerations in AGENTS.md, wiki/SCHEMA.md, and REFERENCES.md
must carry <!-- parity:enum key=... --> markers and match those constants by
set equality. This is the checkable half of the Schema Doc Parity Contract in
workflows/maintenance/eval.md.

Run directly, or via the schema-docs suite in scripts/wiki_eval.py (which also
runs seeded negative cases from scripts/wiki_eval_schema_docs.py):
    python3 scripts/check_schema_doc_parity.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

SITES = (
    # key,                   file,             constant,                    mode
    ("entity-folders",       "AGENTS.md",      "FOLDER_TYPE_KEYS",          "inline-list"),
    ("entity-table-folders", "wiki/SCHEMA.md", "FOLDER_TYPE_KEYS",          "table-location"),
    ("entity-type",          "wiki/SCHEMA.md", "FOLDER_TYPE_VALUES",        "pipe-enum"),
    ("source-type",          "wiki/SCHEMA.md", "VALID_SOURCE_TYPE",         "pipe-enum"),
    ("confidence",           "wiki/SCHEMA.md", "VALID_CONFIDENCE",          "pipe-enum"),
    ("authority-kind",       "wiki/SCHEMA.md", "VALID_AUTHORITY_KIND",      "pipe-enum"),
    ("authority-freshness",  "wiki/SCHEMA.md", "VALID_AUTHORITY_FRESHNESS", "pipe-enum"),
    ("freshness-defaults",   "wiki/SCHEMA.md", "VALID_AUTHORITY_FRESHNESS", "table-first-column"),
    ("source-type-table",    "wiki/SCHEMA.md", "VALID_SOURCE_TYPE",         "table-first-column"),
    ("confidence-values",    "wiki/SCHEMA.md", "VALID_CONFIDENCE",          "bullet-enum"),
    ("related-labels",       "REFERENCES.md",  "RELATED_LABELS",            "table-first-column"),
)

MARKER_RE = re.compile(
    r"<!--\s*parity:enum\s+key=(?P<key>[a-z0-9]+(?:-[a-z0-9]+)*)\s*-->"
)
COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
PIPE_ENUM_RE = re.compile(r"^(?P<field>[A-Za-z_][A-Za-z0-9_-]*):\s*(?P<values>.+)$")
FOLDER_RE = re.compile(r"wiki/([a-z0-9]+(?:-[a-z0-9]+)*)/")


def _live_constants() -> dict[str, set[str]]:
    import lint

    return {
        "FOLDER_TYPE_KEYS": set(lint.FOLDER_TYPE),
        "FOLDER_TYPE_VALUES": set(lint.FOLDER_TYPE.values()),
        "VALID_CONFIDENCE": set(lint.VALID_CONFIDENCE),
        "VALID_SOURCE_TYPE": set(lint.VALID_SOURCE_TYPE),
        "VALID_AUTHORITY_KIND": set(lint.VALID_AUTHORITY_KIND),
        "VALID_AUTHORITY_FRESHNESS": set(lint.VALID_AUTHORITY_FRESHNESS),
        "RELATED_LABELS": set(lint.RELATED_LABELS),
    }


def _site_registry() -> dict[str, tuple[str, str, str]]:
    return {key: (file_name, constant, mode) for key, file_name, constant, mode in SITES}


def _markdown_files(repo_root: Path) -> list[str]:
    """Return tracked markdown files, falling back to a tree walk for fixtures."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--", "*.md"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return sorted(
            path.relative_to(repo_root).as_posix()
            for path in repo_root.rglob("*.md")
            if ".git" not in path.relative_to(repo_root).parts
        )
    return sorted(line for line in proc.stdout.splitlines() if line)


def _standalone_parity_enum_comment(line: str) -> str | None:
    stripped = line.strip()
    if not COMMENT_RE.fullmatch(stripped):
        return None
    lowered = stripped.lower()
    if "parity" in lowered and "enum" in lowered:
        return stripped
    return None


def _clean_token(token: str) -> str:
    token = token.strip()
    token = token.replace("\\`", "`").replace("**", "")
    while len(token) >= 2 and token.startswith("`") and token.endswith("`"):
        token = token[1:-1].strip()
    return token


def _first_nonblank_after(lines: list[str], marker_index: int) -> tuple[int, str] | None:
    for i in range(marker_index + 1, len(lines)):
        if lines[i].strip():
            return i, lines[i]
    return None


def _normalize_pipe_line(line: str) -> str:
    line = line.strip()
    if line.startswith("- "):
        line = line[2:].strip()
    line = line.replace("\\`", "`").strip()
    if line.startswith("`") and line.endswith("`"):
        line = line[1:-1].strip()
    line = line.split("#", 1)[0].strip()
    return line


def _extract_pipe_enum(lines: list[str], marker_index: int) -> tuple[set[str] | None, str | None]:
    found = _first_nonblank_after(lines, marker_index)
    if not found:
        return None, "expected a non-blank pipe-enum line after marker"
    _line_no, line = found
    normalized = _normalize_pipe_line(line)
    match = PIPE_ENUM_RE.match(normalized)
    if not match or "|" not in match.group("values"):
        return None, "expected '<field>: v1 | v2 | ...' after marker"
    values = {
        _clean_token(part)
        for part in match.group("values").split("|")
        if _clean_token(part)
    }
    if not values:
        return None, "pipe-enum line yielded no values"
    return values, None


def _table_rows_after(lines: list[str], marker_index: int) -> tuple[list[list[str]] | None, str | None]:
    start = None
    for i in range(marker_index + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            start = i
            break
        return None, "expected a markdown table after marker"
    if start is None:
        return None, "expected a markdown table after marker"

    table_lines: list[str] = []
    for line in lines[start:]:
        if not line.strip().startswith("|"):
            break
        table_lines.append(line)
    rows = [
        [_clean_token(cell) for cell in line.strip().strip("|").split("|")]
        for line in table_lines
    ]
    if len(rows) < 3:
        return None, "markdown table must include header, divider, and data rows"
    return rows, None


def _is_divider_row(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)


def _extract_table_first_column(lines: list[str], marker_index: int) -> tuple[set[str] | None, str | None]:
    rows, err = _table_rows_after(lines, marker_index)
    if err:
        return None, err
    assert rows is not None
    data = [
        row for row in rows[1:]
        if row and not _is_divider_row(row)
    ]
    values = {row[0] for row in data if row[0]}
    if not values:
        return None, "table first column yielded no values"
    return values, None


def _extract_table_location(lines: list[str], marker_index: int) -> tuple[set[str] | None, str | None]:
    rows, err = _table_rows_after(lines, marker_index)
    if err:
        return None, err
    assert rows is not None
    header = [cell.lower() for cell in rows[0]]
    try:
        location_index = header.index("location")
    except ValueError:
        return None, "table header has no Location column"

    values: set[str] = set()
    for row in rows[1:]:
        if _is_divider_row(row):
            continue
        if len(row) <= location_index:
            return None, "table row is missing the Location column"
        match = FOLDER_RE.search(row[location_index])
        if not match:
            return None, f"Location cell lacks wiki/<folder>/ value: {row[location_index]!r}"
        values.add(match.group(1))
    if not values:
        return None, "table Location column yielded no folder values"
    return values, None


def _extract_bullet_enum(lines: list[str], marker_index: int) -> tuple[set[str] | None, str | None]:
    start = None
    for i in range(marker_index + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            start = i
            break
        return None, "expected bullet list after marker"
    if start is None:
        return None, "expected bullet list after marker"

    values: set[str] = set()
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            break
        if not stripped.startswith("- "):
            break
        normalized = stripped.replace("\\`", "`")
        match = re.match(r"-\s+`([^`]+)`", normalized)
        if not match:
            return None, f"bullet line lacks leading backticked token: {stripped!r}"
        values.add(_clean_token(match.group(1)))
    if not values:
        return None, "bullet list yielded no values"
    return values, None


def _extract_inline_list(lines: list[str], marker_index: int) -> tuple[set[str] | None, str | None]:
    found = _first_nonblank_after(lines, marker_index)
    if not found:
        return None, "expected an inline list after marker"
    _line_no, line = found
    match = re.match(r"\*\*[^*]+:\*\*\s*(?P<values>.+)$", line.strip())
    if not match:
        return None, "expected bold-prefix comma-separated inline list after marker"
    values = {
        _clean_token(part)
        for part in match.group("values").split(",")
        if _clean_token(part)
    }
    if not values:
        return None, "inline list yielded no values"
    return values, None


def _extract_values(
    mode: str,
    lines: list[str],
    marker_index: int,
) -> tuple[set[str] | None, str | None]:
    if mode == "pipe-enum":
        return _extract_pipe_enum(lines, marker_index)
    if mode == "table-first-column":
        return _extract_table_first_column(lines, marker_index)
    if mode == "table-location":
        return _extract_table_location(lines, marker_index)
    if mode == "bullet-enum":
        return _extract_bullet_enum(lines, marker_index)
    if mode == "inline-list":
        return _extract_inline_list(lines, marker_index)
    return None, f"unknown extraction mode {mode!r}"


def _format_values(values: set[str]) -> str:
    return ", ".join(sorted(values))


def schema_doc_parity_problems(
    repo_root: Path = REPO_ROOT,
    constants: dict | None = None,
) -> list[str]:
    """Check marked doc enumerations against their canonical constants.

    Returns a list of human-readable problems (empty when all marked doc sites
    match). Catches drift, missing/duplicate/unknown markers, malformed marker
    comments, and extraction failures at registered sites.
    """
    problems: list[str] = []
    constant_sets = _live_constants() if constants is None else {
        key: set(value) for key, value in constants.items()
    }
    registry = _site_registry()
    expected_keys = set(registry)
    registered_files = sorted({file_name for _key, file_name, _constant, _mode in SITES})
    markers_by_file: dict[str, dict[str, list[int]]] = {}
    lines_by_file: dict[str, list[str]] = {}

    for file_name in _markdown_files(repo_root):
        if file_name in registered_files:
            continue
        path = repo_root / file_name
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, UnicodeDecodeError):
            continue
        for line in lines:
            comment = _standalone_parity_enum_comment(line)
            if comment:
                problems.append(
                    f"{file_name}: unregistered parity enum marker: {comment}"
                )

    for file_name in registered_files:
        path = repo_root / file_name
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            problems.append(f"{file_name}: registered schema-doc parity file missing")
            lines_by_file[file_name] = []
            markers_by_file[file_name] = {}
            continue
        except UnicodeDecodeError as e:
            problems.append(f"{file_name}: not valid UTF-8: {e}")
            lines_by_file[file_name] = []
            markers_by_file[file_name] = {}
            continue

        lines = text.splitlines()
        lines_by_file[file_name] = lines
        markers: dict[str, list[int]] = {}
        for i, line in enumerate(lines):
            stripped = line.strip()
            marker_match = MARKER_RE.fullmatch(stripped)
            if marker_match:
                key = marker_match.group("key")
                if key not in expected_keys:
                    problems.append(f"{file_name}: {key}: unknown parity marker key")
                markers.setdefault(key, []).append(i)
                continue

            for comment in COMMENT_RE.findall(line):
                lowered = comment.lower()
                if "parity" in lowered and "enum" in lowered:
                    problems.append(
                        f"{file_name}: malformed parity enum marker: {comment.strip()}"
                    )
        markers_by_file[file_name] = markers

    for key, file_name, constant_name, mode in SITES:
        markers = markers_by_file.get(file_name, {}).get(key, [])
        if not markers:
            problems.append(f"{file_name}: {key}: missing parity marker")
            continue
        if len(markers) > 1:
            problems.append(
                f"{file_name}: {key}: duplicate parity marker ({len(markers)} occurrences)"
            )
            continue
        if constant_name not in constant_sets:
            problems.append(f"{file_name}: {key}: missing checker constant {constant_name}")
            continue

        values, err = _extract_values(mode, lines_by_file[file_name], markers[0])
        if err:
            problems.append(f"{file_name}: {key}: extraction failure for {mode}: {err}")
            continue
        assert values is not None
        expected = constant_sets[constant_name]
        missing = expected - values
        extra = values - expected
        if missing:
            problems.append(
                f"{file_name}: {key}: enum drift missing-from-doc: {_format_values(missing)}"
            )
        if extra:
            problems.append(
                f"{file_name}: {key}: enum drift extra-in-doc: {_format_values(extra)}"
            )

    return problems


def main() -> int:
    argparse.ArgumentParser(
        description="Verify marked schema-document enumerations match lint contract constants.",
    ).parse_args()
    problems = schema_doc_parity_problems()
    if problems:
        print("Schema-doc parity problems found:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Schema-doc enumerations match lint contract constants.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
