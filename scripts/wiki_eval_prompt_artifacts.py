#!/usr/bin/env python3
"""Regression checks for prompt-artifact ownership and review clocks."""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

from eval_lib import Results
from wiki_prompt_artifacts import (
    load_prompt_artifact_registry,
    prompt_artifact_registry_errors,
    prompt_artifact_reviews_due,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
results = Results()
registry = load_prompt_artifact_registry(REPO_ROOT / "scripts/prompt-artifacts.json")


def errors_for(mutated: dict[str, object]) -> list[str]:
    return prompt_artifact_registry_errors(mutated, repo_root=REPO_ROOT)


results.record("live-registry-is-valid-and-complete", not errors_for(registry))
results.record(
    "fresh-review-clock-is-not-due",
    not prompt_artifact_reviews_due(registry, as_of=date(2026, 8, 25)),
)
results.record(
    "expired-review-clock-is-due",
    bool(prompt_artifact_reviews_due(registry, as_of=date(2027, 8, 25))),
)

cases: list[tuple[str, dict[str, object], str]] = []

missing_file = copy.deepcopy(registry)
missing_file["collections"][0]["paths"].append("workflows/missing.md")
missing_file["collections"][0]["paths"].sort()
cases.append(("missing-file-fails", missing_file, "missing file"))

duplicate_owner = copy.deepcopy(registry)
duplicate_owner["collections"][1]["paths"].append("AGENTS.md")
duplicate_owner["collections"][1]["paths"].sort()
cases.append(("duplicate-ownership-fails", duplicate_owner, "globally unique"))

incomplete = copy.deepcopy(registry)
incomplete["collections"][-1]["paths"].pop()
cases.append(("incomplete-coverage-fails", incomplete, "coverage differs"))

unknown_field = copy.deepcopy(registry)
unknown_field["collections"][0]["extra"] = True
cases.append(("unknown-field-fails", unknown_field, "unknown fields"))

malformed_date = copy.deepcopy(registry)
malformed_date["collections"][0]["last_reviewed"] = "not-a-date"
cases.append(("malformed-date-fails", malformed_date, "ISO date"))

missing_owner = copy.deepcopy(registry)
missing_owner["collections"][0]["owner"] = ""
cases.append(("missing-owner-fails", missing_owner, "owner"))

missing_removal = copy.deepcopy(registry)
missing_removal["collections"][0]["removal_test"] = ""
cases.append(("missing-removal-test-fails", missing_removal, "removal_test"))

missing_trigger = copy.deepcopy(registry)
missing_trigger["review_triggers"] = ["model-change"]
cases.append(("missing-review-trigger-fails", missing_trigger, "review_triggers"))

for name, mutated, fragment in cases:
    errors = errors_for(mutated)
    results.record(name, any(fragment in error for error in errors), repr(errors))

raise SystemExit(results.finish())
