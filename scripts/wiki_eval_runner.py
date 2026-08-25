#!/usr/bin/env python3
"""Hermetic self-tests for the live eval registry and result accounting."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import wiki_eval
from eval_lib import Results


def main() -> int:
    results = Results()
    check = results.record

    registered_helper = getattr(wiki_eval, "registered_eval_scripts", None)
    check(
        "registered-eval-scripts-helper-exists",
        callable(registered_helper),
        "wiki_eval.registered_eval_scripts is missing",
    )

    with tempfile.TemporaryDirectory(prefix="wiki-eval-runner-") as td:
        scripts_dir = Path(td)
        real = scripts_dir / "wiki_eval_real.py"
        decoy = scripts_dir / "wiki_eval_decoy.py"
        real.write_text("raise SystemExit(0)\n", encoding="utf-8")
        decoy.write_text("raise SystemExit(0)\n", encoding="utf-8")
        suites = {
            "real": [sys.executable, str(real)],
            "decoy-argument": [sys.executable, "runner.py", str(decoy)],
        }
        if callable(registered_helper):
            registered = registered_helper(suites)
            check(
                "only-command-position-one-registers",
                registered == {real.name},
                f"registered={sorted(registered)}",
            )
        else:
            check(
                "only-command-position-one-registers",
                False,
                "registration helper unavailable",
            )
        try:
            orphans = wiki_eval.unregistered_suites(
                scripts_dir=scripts_dir,
                suites=suites,
            )
        except TypeError as exc:
            check("orphan-check-is-injectable", False, str(exc))
        else:
            check(
                "orphan-check-is-injectable",
                orphans == [decoy.name],
                f"orphans={orphans}",
            )

    result_failure = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from eval_lib import Results; "
                "r = Results(); r.record('forced-failure', False); "
                "raise SystemExit(r.finish())"
            ),
        ],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
    )
    check(
        "results-false-record-exits-one",
        result_failure.returncode == 1,
        f"exit={result_failure.returncode}; stderr={result_failure.stderr!r}",
    )
    check(
        "results-false-record-reports-exact-summary",
        "Summary: 0 passed, 1 failed" in result_failure.stdout,
        result_failure.stdout.strip(),
    )

    complete_profiles = wiki_eval.suite_profile_errors(
        wiki_eval.SUITES,
        wiki_eval.SUITE_PROFILES,
        wiki_eval.PORTABLE_COMMAND_OVERRIDES,
    )
    check("all-suites-declare-profiles", not complete_profiles, repr(complete_profiles))
    missing_profile = dict(wiki_eval.SUITE_PROFILES)
    missing_profile.pop(next(iter(missing_profile)))
    check(
        "new-suite-without-profile-fails",
        bool(
            wiki_eval.suite_profile_errors(
                wiki_eval.SUITES,
                missing_profile,
                wiki_eval.PORTABLE_COMMAND_OVERRIDES,
            )
        ),
    )
    portable = wiki_eval.suite_commands_for_profile(wiki_eval.PORTABLE_PROFILE)
    check("portable-excludes-live-tier1", "tier1" not in portable)
    check(
        "portable-export-uses-explicit-override",
        portable["export"] == wiki_eval.PORTABLE_COMMAND_OVERRIDES["export"],
        repr(portable["export"]),
    )

    runtime_result = subprocess.run(
        [sys.executable, "scripts/wiki_eval.py", "--suite", "capture-runs"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    expected_runtime = (
        f"Python runtime: {sys.version_info.major}."
        f"{sys.version_info.minor}.{sys.version_info.micro}"
    )
    check(
        "cli-reports-python-runtime-version",
        runtime_result.returncode == 0
        and runtime_result.stdout.startswith(expected_runtime + "\n"),
        f"exit={runtime_result.returncode}; stdout={runtime_result.stdout!r}",
    )
    return results.finish()


if __name__ == "__main__":
    sys.exit(main())
