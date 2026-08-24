#!/usr/bin/env python3
"""Run the live wiki evaluation suites.

Entrypoint for the deterministic checks that guard live tooling. The SUITES
registry below is the single enumeration of what runs; each suite's own
docstring describes what it guards.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SUITES = {
    "eval-runner": [sys.executable, "scripts/wiki_eval_runner.py"],
    "parse-primitives": [sys.executable, "scripts/wiki_eval_parse_primitives.py"],
    "repo-paths": [sys.executable, "scripts/wiki_eval_repo_paths.py"],
    "parse-callers": [sys.executable, "scripts/wiki_eval_parse_callers.py"],
    "rebuild": [sys.executable, "scripts/wiki_eval_rebuild.py"],
    "lint-pages": [sys.executable, "scripts/wiki_eval_lint_pages.py"],
    "lint-repository": [sys.executable, "scripts/wiki_eval_lint_repository.py"],
    "lint-signals": [sys.executable, "scripts/wiki_eval_lint_signals.py"],
    "application": [sys.executable, "scripts/wiki_eval_application.py"],
    "capture-runs": [sys.executable, "scripts/validate_capture_runs.py"],
    "export": [sys.executable, "scripts/wiki_eval_export.py"],
    "backup-state": [sys.executable, "scripts/wiki_eval_backup.py"],
    "rotate-log": [sys.executable, "scripts/wiki_eval_rotate_log.py"],
    "review-due": [sys.executable, "scripts/wiki_eval_review.py"],
    "wrapper-parity": [sys.executable, "scripts/wiki_eval_wrappers.py"],
    "schema-vocabularies": [sys.executable, "scripts/wiki_eval_schema_vocabularies.py"],
    "durable-files": [sys.executable, "scripts/wiki_eval_durable_files.py"],
    "transactions": [sys.executable, "scripts/wiki_eval_transactions.py"],
    "document-reachability": [sys.executable, "scripts/wiki_eval_document_reachability.py"],
    "entity-catalog": [sys.executable, "scripts/wiki_eval_entity_catalog.py"],
    "evidence-fidelity": [sys.executable, "scripts/wiki_eval_evidence.py"],
    "provenance": [sys.executable, "scripts/wiki_eval_provenance.py"],
    "tier1": [sys.executable, "scripts/lint.py", "--tier1"],
}


def registered_eval_scripts(suites: dict[str, list[str]]) -> set[str]:
    """Eval script basenames registered as the executable's script argument.

    Python suite commands have the form ``[python, script, *args]``. Only the
    script at position 1 establishes registration; an eval-looking decoy in a
    later argument must not hide an orphaned suite file.
    """
    registered: set[str] = set()
    for command in suites.values():
        if len(command) < 2:
            continue
        candidate = Path(command[1]).name
        if candidate.startswith("wiki_eval_") and candidate.endswith(".py"):
            registered.add(candidate)
    return registered


def unregistered_suites(
    *,
    scripts_dir: Path | None = None,
    suites: dict[str, list[str]] | None = None,
) -> list[str]:
    """Return ``wiki_eval_*.py`` files absent from command position 1."""
    directory = scripts_dir or Path(__file__).resolve().parent
    registered = registered_eval_scripts(SUITES if suites is None else suites)
    return sorted(
        path.name
        for path in directory.glob("wiki_eval_*.py")
        if path.name not in registered
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run live wiki tooling evals.")
    p.add_argument(
        "--suite",
        action="append",
        choices=sorted(SUITES),
        help="Suite to run. Repeat for multiple suites. Defaults to all.",
    )
    return p


def run_suite(name: str, command: list[str]) -> int:
    print(f"== {name} ==", flush=True)
    result = subprocess.run(command, check=False)
    print()
    return result.returncode


def main() -> int:
    print(
        f"Python runtime: {sys.version_info.major}."
        f"{sys.version_info.minor}.{sys.version_info.micro}",
        flush=True,
    )
    args = parser().parse_args()
    # Default to every suite, derived from SUITES so a newly registered suite can
    # never be silently dropped from the default run by a forgotten list entry.
    suite_names = args.suite or list(SUITES)

    failures: list[str] = []
    orphans = unregistered_suites()
    if orphans:
        failures.append(
            "unregistered suite file(s) not in SUITES: " + ", ".join(orphans)
        )
    for name in suite_names:
        code = run_suite(name, SUITES[name])
        if code != 0:
            failures.append(f"{name} exited {code}")

    if failures:
        print("Wiki eval failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Wiki eval passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
