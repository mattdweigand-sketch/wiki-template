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
    "prompt-artifacts": [sys.executable, "scripts/wiki_eval_prompt_artifacts.py"],
    "entity-catalog": [sys.executable, "scripts/wiki_eval_entity_catalog.py"],
    "wiki-log": [sys.executable, "scripts/wiki_eval_log.py"],
    "capture-diff": [sys.executable, "scripts/wiki_eval_capture_diff.py"],
    "finalize": [sys.executable, "scripts/wiki_eval_finalize.py"],
    "lookup": [sys.executable, "scripts/wiki_eval_lookup.py"],
    "evidence-fidelity": [sys.executable, "scripts/wiki_eval_evidence.py"],
    "provenance": [sys.executable, "scripts/wiki_eval_provenance.py"],
    "tier1": [sys.executable, "scripts/lint.py", "--tier1"],
}

FULL_PROFILE = "full"
PORTABLE_PROFILE = "portable"
SUITE_PROFILES = {
    "eval-runner": {FULL_PROFILE, PORTABLE_PROFILE},
    "parse-primitives": {FULL_PROFILE, PORTABLE_PROFILE},
    "repo-paths": {FULL_PROFILE, PORTABLE_PROFILE},
    "parse-callers": {FULL_PROFILE, PORTABLE_PROFILE},
    "rebuild": {FULL_PROFILE, PORTABLE_PROFILE},
    "lint-pages": {FULL_PROFILE, PORTABLE_PROFILE},
    "lint-repository": {FULL_PROFILE, PORTABLE_PROFILE},
    "lint-signals": {FULL_PROFILE, PORTABLE_PROFILE},
    "application": {FULL_PROFILE, PORTABLE_PROFILE},
    "capture-runs": {FULL_PROFILE, PORTABLE_PROFILE},
    "export": {FULL_PROFILE, PORTABLE_PROFILE},
    "backup-state": {FULL_PROFILE, PORTABLE_PROFILE},
    "rotate-log": {FULL_PROFILE, PORTABLE_PROFILE},
    "review-due": {FULL_PROFILE, PORTABLE_PROFILE},
    "wrapper-parity": {FULL_PROFILE, PORTABLE_PROFILE},
    "schema-vocabularies": {FULL_PROFILE, PORTABLE_PROFILE},
    "durable-files": {FULL_PROFILE, PORTABLE_PROFILE},
    "transactions": {FULL_PROFILE, PORTABLE_PROFILE},
    "document-reachability": {FULL_PROFILE, PORTABLE_PROFILE},
    "prompt-artifacts": {FULL_PROFILE, PORTABLE_PROFILE},
    "entity-catalog": {FULL_PROFILE, PORTABLE_PROFILE},
    "wiki-log": {FULL_PROFILE, PORTABLE_PROFILE},
    "capture-diff": {FULL_PROFILE, PORTABLE_PROFILE},
    "finalize": {FULL_PROFILE, PORTABLE_PROFILE},
    "lookup": {FULL_PROFILE, PORTABLE_PROFILE},
    "evidence-fidelity": {FULL_PROFILE, PORTABLE_PROFILE},
    "provenance": {FULL_PROFILE, PORTABLE_PROFILE},
    "tier1": {FULL_PROFILE},
}
PORTABLE_COMMAND_OVERRIDES = {
    "export": [
        sys.executable,
        "scripts/wiki_eval_export.py",
        "--profile",
        "portable",
    ],
}


def suite_profile_errors(
    suites: dict[str, list[str]],
    suite_profiles: dict[str, set[str]],
    portable_overrides: dict[str, list[str]],
) -> list[str]:
    """Return incomplete or invalid eval-profile classification errors."""
    errors: list[str] = []
    missing = sorted(set(suites) - set(suite_profiles))
    unknown = sorted(set(suite_profiles) - set(suites))
    if missing or unknown:
        errors.append(f"suite profile coverage differs; missing={missing}; unknown={unknown}")
    allowed_profiles = {FULL_PROFILE, PORTABLE_PROFILE}
    for name, profiles in suite_profiles.items():
        if not profiles or not profiles <= allowed_profiles or FULL_PROFILE not in profiles:
            errors.append(f"suite {name} has invalid profiles: {sorted(profiles)}")
    for name in portable_overrides:
        if name not in suites or PORTABLE_PROFILE not in suite_profiles.get(name, set()):
            errors.append(f"portable override is not classified portable: {name}")
    return errors


def suite_commands_for_profile(profile: str) -> dict[str, list[str]]:
    """Return exact suite commands allowed for one eval profile."""
    if profile not in {FULL_PROFILE, PORTABLE_PROFILE}:
        raise ValueError(f"unknown eval profile: {profile}")
    commands: dict[str, list[str]] = {}
    for name, command in SUITES.items():
        if profile not in SUITE_PROFILES[name]:
            continue
        commands[name] = (
            PORTABLE_COMMAND_OVERRIDES[name]
            if profile == PORTABLE_PROFILE and name in PORTABLE_COMMAND_OVERRIDES
            else command
        )
    return commands


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
        "--profile",
        choices=(FULL_PROFILE, PORTABLE_PROFILE),
        default=FULL_PROFILE,
        help="Use full local checks or the explicit no-private-raw profile.",
    )
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
    profile_errors = suite_profile_errors(SUITES, SUITE_PROFILES, PORTABLE_COMMAND_OVERRIDES)
    if profile_errors:
        for error in profile_errors:
            print(f"Wiki eval profile error: {error}")
        return 1
    profile_commands = suite_commands_for_profile(args.profile)
    # Default to every suite, derived from SUITES so a newly registered suite can
    # never be silently dropped from the default run by a forgotten list entry.
    suite_names = args.suite or list(profile_commands)

    unavailable = sorted(name for name in suite_names if name not in profile_commands)
    if unavailable:
        print(
            f"Wiki eval profile {args.profile} does not allow suite(s): "
            + ", ".join(unavailable)
        )
        return 2

    failures: list[str] = []
    orphans = unregistered_suites()
    if orphans:
        failures.append(
            "unregistered suite file(s) not in SUITES: " + ", ".join(orphans)
        )
    for name in suite_names:
        code = run_suite(name, profile_commands[name])
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
