#!/usr/bin/env python3
"""Check production Python interfaces for discoverability regressions.

The production inventory is intentionally narrow: direct ``scripts/*.py``
modules, excluding evaluation and test programs. Test sources are reported in
a separate bucket so fixture exceptions cannot silently weaken production
enforcement.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_RELATIVE = Path("scripts")
ALLOWED_FIXTURE_NAMES = frozenset({"scripts/fixtures/wiki-lint/wiki/index.md"})
GENERIC_CALLABLE_NAMES = frozenset(
    {"check", "collect", "create", "do", "get", "handle", "process", "run", "set", "validate"}
)
GENERIC_FILE_STEMS = frozenset(
    {"common", "core", "helpers", "index", "models", "types", "utils"}
)
INTENTIONAL_ENTRYPOINT_NAMES = frozenset({"main", "parser"})


Finding = dict[str, object]
DiscoverabilityReport = dict[str, list[Finding]]


def is_production_module(relative_path: Path) -> bool:
    """Return whether a path belongs to the enforced production inventory."""
    return (
        relative_path.parent == SCRIPTS_RELATIVE
        and relative_path.suffix == ".py"
        and not relative_path.name.startswith(("test_", "wiki_eval_"))
    )


def is_test_or_fixture(relative_path: Path) -> bool:
    """Return whether a path belongs to test-only source support."""
    return (
        "fixtures" in relative_path.parts
        or relative_path.parent == SCRIPTS_RELATIVE
        and relative_path.name.startswith(("test_", "wiki_eval_"))
    )


def annotation_contains_any(annotation: ast.expr | None) -> bool:
    """Return whether an annotation tree contains the name ``Any``."""
    return annotation is not None and any(
        isinstance(node, ast.Name) and node.id == "Any"
        for node in ast.walk(annotation)
    )


def is_bare_any(annotation: ast.expr | None) -> bool:
    """Return whether an annotation is exactly ``Any``."""
    return isinstance(annotation, ast.Name) and annotation.id == "Any"


def is_dict_str_any(annotation: ast.expr | None) -> bool:
    """Return whether an annotation contains ``dict[str, Any]``."""
    if annotation is None:
        return False
    for node in ast.walk(annotation):
        if not isinstance(node, ast.Subscript):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id != "dict":
            continue
        elements = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if (
            len(elements) == 2
            and isinstance(elements[0], ast.Name)
            and elements[0].id == "str"
            and annotation_contains_any(elements[1])
        ):
            return True
    return False


def declared_public_names(tree: ast.Module) -> frozenset[str] | None:
    """Return a literal ``__all__`` inventory, or ``None`` when undeclared."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return None
        names = [
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        return frozenset(names) if len(names) == len(node.value.elts) else None
    return None


def public_top_level_functions(
    tree: ast.Module,
) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield intentional top-level interfaces in source order.

    A literal ``__all__`` is the authoritative interface when present;
    otherwise normal underscore visibility applies. This lets a concept module
    make its boundary mechanically explicit without forcing internal registry
    callbacks onto the public API.
    """
    declared = declared_public_names(tree)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if declared is not None and node.name in declared:
            yield node
        elif declared is None and not node.name.startswith("_"):
            yield node


def explicitly_exported_classes(tree: ast.Module) -> Iterable[ast.ClassDef]:
    """Yield classes named by a literal ``__all__`` declaration."""
    declared = declared_public_names(tree)
    if declared is None:
        return
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in declared:
            yield node


def function_annotations(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterable[tuple[str, ast.expr | None]]:
    """Yield every audited parameter and return annotation."""
    arguments = function.args
    for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]:
        yield argument.arg, argument.annotation
    if arguments.vararg is not None:
        yield "*" + arguments.vararg.arg, arguments.vararg.annotation
    if arguments.kwarg is not None:
        yield "**" + arguments.kwarg.arg, arguments.kwarg.annotation
    yield "return", function.returns


def build_finding(relative_path: Path, line: int, kind: str, symbol: str) -> Finding:
    """Build one stable machine-readable finding."""
    return {
        "kind": kind,
        "line": line,
        "path": relative_path.as_posix(),
        "symbol": symbol,
    }


def inspect_python_source(relative_path: Path, text: str) -> tuple[list[Finding], list[str]]:
    """Return interface findings and public names for one Python module."""
    try:
        tree = ast.parse(text, filename=relative_path.as_posix())
    except SyntaxError as exc:
        return [build_finding(relative_path, exc.lineno or 0, "syntax-error", "<module>")], []

    findings: list[Finding] = []
    public_names: list[str] = []
    for function in public_top_level_functions(tree):
        public_names.append(function.name)
        annotations = list(function_annotations(function))
        incomplete = [name for name, annotation in annotations if annotation is None]
        if incomplete:
            findings.append(
                build_finding(
                    relative_path,
                    function.lineno,
                    "incomplete-public-signature",
                    function.name + " (" + ", ".join(incomplete) + ")",
                )
            )
        for name, annotation in annotations:
            symbol = function.name + "." + name
            if is_bare_any(annotation):
                findings.append(build_finding(relative_path, function.lineno, "bare-any", symbol))
            if annotation_contains_any(annotation):
                findings.append(
                    build_finding(relative_path, function.lineno, "any-containing-signature", symbol)
                )
            if is_dict_str_any(annotation):
                findings.append(
                    build_finding(relative_path, function.lineno, "dict-str-any-signature", symbol)
                )

    for function in public_top_level_functions(tree):
        if function.name in GENERIC_CALLABLE_NAMES:
            findings.append(
                build_finding(relative_path, function.lineno, "generic-callable", function.name)
            )

    for class_definition in explicitly_exported_classes(tree):
        public_names.append(class_definition.name)
        constructor = next(
            (
                node
                for node in class_definition.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "__init__"
            ),
            None,
        )
        if constructor is None:
            continue
        annotations = [
            (name, annotation)
            for name, annotation in function_annotations(constructor)
            if name not in {"self", "cls"}
        ]
        symbol_prefix = f"{class_definition.name}.__init__"
        incomplete = [name for name, annotation in annotations if annotation is None]
        if incomplete:
            findings.append(
                build_finding(
                    relative_path,
                    constructor.lineno,
                    "incomplete-public-signature",
                    symbol_prefix + " (" + ", ".join(incomplete) + ")",
                )
            )
        for name, annotation in annotations:
            symbol = symbol_prefix + "." + name
            if is_bare_any(annotation):
                findings.append(build_finding(relative_path, constructor.lineno, "bare-any", symbol))
            if annotation_contains_any(annotation):
                findings.append(
                    build_finding(
                        relative_path,
                        constructor.lineno,
                        "any-containing-signature",
                        symbol,
                    )
                )
            if is_dict_str_any(annotation):
                findings.append(
                    build_finding(
                        relative_path,
                        constructor.lineno,
                        "dict-str-any-signature",
                        symbol,
                    )
                )
    return findings, public_names


def collect_discoverability_report(repo_root: Path) -> DiscoverabilityReport:
    """Classify discoverability findings under ``repo_root`` by audited scope."""
    scripts_dir = repo_root / SCRIPTS_RELATIVE
    report: DiscoverabilityReport = {
        "allowed_fixture_names": [],
        "fixture_test_observations": [],
        "production_advisories": [],
        "production_blockers": [],
    }
    if not scripts_dir.is_dir():
        report["production_blockers"].append(
            build_finding(SCRIPTS_RELATIVE, 0, "missing-scripts-directory", "<scripts>")
        )
        return report

    production_names: list[tuple[Path, str]] = []
    for path in sorted(item for item in scripts_dir.rglob("*") if item.is_file()):
        relative_path = path.relative_to(repo_root)
        if relative_path.as_posix() in ALLOWED_FIXTURE_NAMES:
            report["allowed_fixture_names"].append(
                build_finding(relative_path, 0, "allowed-fixture-name", path.name)
            )
            continue

        findings: list[Finding] = []
        public_names: list[str] = []
        if path.stem in GENERIC_FILE_STEMS:
            findings.append(build_finding(relative_path, 0, "generic-file-stem", path.stem))
        if path.suffix == ".py":
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                findings.append(build_finding(relative_path, 0, "non-utf8-python-source", "<module>"))
            else:
                python_findings, public_names = inspect_python_source(relative_path, text)
                findings.extend(python_findings)

        if is_production_module(relative_path):
            report["production_blockers"].extend(findings)
            production_names.extend((relative_path, name) for name in public_names)
        elif is_test_or_fixture(relative_path):
            report["fixture_test_observations"].extend(findings)

    name_counts = Counter(name for _, name in production_names)
    for relative_path, name in production_names:
        if name_counts[name] > 1 and name not in INTENTIONAL_ENTRYPOINT_NAMES:
            report["production_advisories"].append(
                build_finding(relative_path, 0, "duplicate-public-callable", name)
            )

    for findings in report.values():
        findings.sort(
            key=lambda finding: (
                str(finding["path"]),
                int(finding["line"]),
                str(finding["kind"]),
                str(finding["symbol"]),
            )
        )
    return report


def render_discoverability_report(report: DiscoverabilityReport) -> str:
    """Render a stable concise report for interactive use."""
    lines: list[str] = []
    for bucket in (
        "production_blockers",
        "production_advisories",
        "fixture_test_observations",
        "allowed_fixture_names",
    ):
        findings = report[bucket]
        lines.append(f"{bucket}: {len(findings)}")
        for finding in findings:
            lines.append("  {path}:{line}: {kind}: {symbol}".format(**finding))
    return "\n".join(lines)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    argument_parser = argparse.ArgumentParser(
        description="Check scoped production-script discoverability contracts."
    )
    argument_parser.add_argument(
        "--repo",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to inspect (default: this repository).",
    )
    argument_parser.add_argument(
        "--report",
        type=Path,
        help="Write the complete deterministic JSON report to this path.",
    )
    return argument_parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scoped check and fail only for production blockers."""
    args = build_argument_parser().parse_args(argv)
    report = collect_discoverability_report(args.repo)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render_discoverability_report(report))
    return 1 if report["production_blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
