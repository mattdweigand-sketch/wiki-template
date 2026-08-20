#!/usr/bin/env python3
"""Regression evals for the structured approval ledger validator."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from eval_lib import Results


REPO_ROOT = Path(__file__).resolve().parents[1]
APPROVAL_VALIDATOR = REPO_ROOT / "scripts" / "validate_capture_runs.py"

results = Results()


def run_validator(name: str, lines: list[object | str], expect_code: int,
                  expect: tuple[str, ...] = ()) -> None:
    with tempfile.TemporaryDirectory(prefix="wiki-ledger-eval-") as td:
        path = Path(td) / "ledger.jsonl"
        rendered = []
        for line in lines:
            if isinstance(line, str):
                rendered.append(line)
            else:
                rendered.append(json.dumps(line, sort_keys=True, separators=(",", ":")))
        path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(APPROVAL_VALIDATOR), str(path)],
            text=True,
            capture_output=True,
            check=False,
        )
    output = proc.stdout + proc.stderr
    ok = proc.returncode == expect_code and all(marker in output for marker in expect)
    missing = [marker for marker in expect if marker not in output]
    detail = f"exit {proc.returncode} (expected {expect_code}); missing {missing}; output: " + output.replace("\n", " | ")
    results.record(name, ok, detail)


def approval_schema() -> dict[str, object]:
    return {
        "record_type": "schema",
        "schema_version": 1,
        "description": "approval ledger fixture",
    }


def capture_record() -> dict[str, object]:
    return {
        "record_type": "capture_approval",
        "schema_version": 1,
        "approval_status": "approved",
        "artifact": "Fixture analysis",
        "route": "analysis-capture",
        "phase": "accepted",
        "primary_home": "wiki/analyses/fixture.md",
        "pages_touched": ["wiki/analyses/fixture.md", "wiki/index.md"],
        "source_path": "",
        "synthesized_pages": 3,
        "word_count": 301,
        "domain_context": True,
        "triggers": [],
        "approved_at": "2026-06-15T00:00:00+00:00",
    }


def synthesis_record() -> dict[str, object]:
    return {
        "record_type": "synthesis_approval",
        "schema_version": 1,
        "approval_status": "approved",
        "artifact": "Fixture synthesis",
        "drafts": "wiki/overview.md draft",
        "primary_home": "wiki/synthesis.md",
        "pages_touched": ["wiki/synthesis.md", "wiki/overview.md"],
        "ledger_update_required": True,
        "approved_at": "2026-06-15T00:00:00+00:00",
    }


def commissioned_capture(**updates: object) -> dict[str, object]:
    record = capture_record()
    record.update({
        "approved_at": "2026-07-10T03:23:58Z",
        "word_count_source": "measured",
        "word_count_path": "/tmp/fixture-draft.md",
        "draft_sha256": "a" * 64,
        "authored_sha256": "b" * 64,
        "authored_hash_policy": "strip_referenced_by_v1",
    })
    record.update(updates)
    return record


run_validator(
    "capture-valid-passes",
    [approval_schema(), capture_record()],
    0,
    ("validation passed",),
)
post_cutoff_analysis_unmeasured = commissioned_capture(
    word_count_source="unmeasured",
    word_count_path="",
)
del post_cutoff_analysis_unmeasured["draft_sha256"]
del post_cutoff_analysis_unmeasured["authored_sha256"]
del post_cutoff_analysis_unmeasured["authored_hash_policy"]
run_validator(
    "post-cutoff-analysis-requires-measurement-provenance",
    [approval_schema(), post_cutoff_analysis_unmeasured],
    1,
    ("analyses-targeting", "measured"),
)
post_cutoff_analysis_promotion = commissioned_capture(
    route="promotion-audit",
    triggers=["existing_page_update"],
    word_count_source="unmeasured",
    word_count_path="",
)
del post_cutoff_analysis_promotion["draft_sha256"]
del post_cutoff_analysis_promotion["authored_sha256"]
del post_cutoff_analysis_promotion["authored_hash_policy"]
run_validator(
    "post-cutoff-analysis-promotion-requires-measurement-provenance",
    [approval_schema(), post_cutoff_analysis_promotion],
    1,
    ("analyses-targeting", "measured"),
)
measured_missing_evidence = commissioned_capture(
    route="promotion-audit",
    primary_home="wiki/concepts/fixture.md",
    pages_touched=["wiki/concepts/fixture.md"],
    triggers=["existing_page_update"],
    word_count_source="measured",
    word_count_path="",
)
del measured_missing_evidence["draft_sha256"]
del measured_missing_evidence["authored_sha256"]
del measured_missing_evidence["authored_hash_policy"]
run_validator(
    "measured-capture-requires-path-and-hash",
    [approval_schema(), measured_missing_evidence],
    1,
    ("measured", "word_count_path", "draft_sha256"),
)
unmeasured_with_evidence = commissioned_capture(
    route="promotion-audit",
    primary_home="wiki/concepts/fixture.md",
    pages_touched=["wiki/concepts/fixture.md"],
    triggers=["existing_page_update"],
    word_count_source="unmeasured",
)
del unmeasured_with_evidence["authored_sha256"]
del unmeasured_with_evidence["authored_hash_policy"]
run_validator(
    "unmeasured-capture-rejects-path-and-hash",
    [approval_schema(), unmeasured_with_evidence],
    1,
    ("unmeasured", "word_count_path", "draft_sha256"),
)
unmeasured_missing_path = commissioned_capture(
    route="promotion-audit",
    primary_home="wiki/concepts/fixture.md",
    pages_touched=["wiki/concepts/fixture.md"],
    triggers=["existing_page_update"],
    word_count_source="unmeasured",
)
for key in (
    "word_count_path",
    "draft_sha256",
    "authored_sha256",
    "authored_hash_policy",
):
    del unmeasured_missing_path[key]
run_validator(
    "unmeasured-capture-requires-explicit-empty-path",
    [approval_schema(), unmeasured_missing_path],
    1,
    ("unmeasured", "empty word_count_path"),
)
bad_measurement_enum = commissioned_capture(word_count_source="estimated")
run_validator(
    "capture-measurement-source-enum-fails",
    [approval_schema(), bad_measurement_enum],
    1,
    ("word_count_source", "measured", "unmeasured"),
)
unsorted_duplicate_triggers = commissioned_capture(
    route="promotion-audit",
    primary_home="wiki/concepts/fixture.md",
    pages_touched=["wiki/concepts/fixture.md"],
    triggers=["reusable_distinction", "existing_page_update", "reusable_distinction"],
)
run_validator(
    "new-trigger-list-must-be-sorted-and-unique",
    [approval_schema(), unsorted_duplicate_triggers],
    1,
    ("triggers", "sorted", "unique"),
)
draft_cutoff_unsorted_triggers = commissioned_capture(
    approved_at="2026-07-09T00:00:00Z",
    route="promotion-audit",
    primary_home="wiki/concepts/fixture.md",
    pages_touched=["wiki/concepts/fixture.md"],
    triggers=["reusable_distinction", "existing_page_update"],
)
del draft_cutoff_unsorted_triggers["authored_sha256"]
del draft_cutoff_unsorted_triggers["authored_hash_policy"]
run_validator(
    "draft-cutoff-trigger-list-must-be-sorted-and-unique",
    [approval_schema(), draft_cutoff_unsorted_triggers],
    1,
    ("triggers", "sorted", "unique"),
)
authored_hash_missing = commissioned_capture()
del authored_hash_missing["authored_sha256"]
del authored_hash_missing["authored_hash_policy"]
run_validator(
    "commissioned-analysis-requires-authored-hash",
    [approval_schema(), authored_hash_missing],
    1,
    ("authored_sha256", "strip_referenced_by_v1"),
)
valid_unmeasured_promotion = commissioned_capture(
    route="promotion-audit",
    primary_home="wiki/concepts/fixture.md",
    pages_touched=["wiki/concepts/fixture.md"],
    triggers=["existing_page_update"],
    synthesized_pages=0,
    word_count=0,
    word_count_source="unmeasured",
    word_count_path="",
)
for key in ("draft_sha256", "authored_sha256", "authored_hash_policy"):
    del valid_unmeasured_promotion[key]
run_validator(
    "post-cutoff-non-analysis-unmeasured-passes",
    [approval_schema(), valid_unmeasured_promotion],
    0,
    ("validation passed",),
)
run_validator(
    "capture-malformed-json-fails",
    [approval_schema(), "{not json"],
    1,
    ("invalid JSON",),
)
duplicate_key_line = json.dumps(
    capture_record(), sort_keys=True, separators=(",", ":")
).replace('"route":"analysis-capture"', '"route":"evil","route":"analysis-capture"', 1)
run_validator(
    "capture-duplicate-json-key-fails",
    [approval_schema(), duplicate_key_line],
    1,
    ("duplicate JSON key: route",),
)
nested_duplicate_key_line = json.dumps(
    capture_record(), sort_keys=True, separators=(",", ":")
).replace(
    '"pages_touched":[',
    '"evidence":{"claim":"first","claim":"second"},"pages_touched":[',
    1,
)
run_validator(
    "capture-nested-duplicate-json-key-fails",
    [approval_schema(), nested_duplicate_key_line],
    1,
    ("duplicate JSON key: claim",),
)
run_validator(
    "unhashable-record-type-fails-cleanly",
    [approval_schema(), {"record_type": []}],
    1,
    ("unsupported record_type",),
)
unhashable_capture_fields = commissioned_capture(
    route=[],
    phase=[],
    word_count_source=[],
    triggers=[[]],
)
run_validator(
    "unhashable-capture-fields-fail-cleanly",
    [approval_schema(), unhashable_capture_fields],
    1,
    ("route must be", "phase must be", "word_count_source", "triggers must be"),
)
duplicate_capture = capture_record()
duplicate_capture_later = capture_record()
duplicate_capture_later["approved_at"] = "2026-06-16T00:00:00+00:00"
run_validator(
    "capture-duplicate-approval-fails",
    [approval_schema(), duplicate_capture, duplicate_capture_later],
    1,
    ("duplicate approval record",),
)
invalid_trigger_capture = capture_record()
invalid_trigger_capture["triggers"] = ["not_a_valid_trigger"]
run_validator(
    "capture-invalid-trigger-fails",
    [approval_schema(), invalid_trigger_capture],
    1,
    ("triggers must be a list of valid promotion triggers",),
)
out_of_root_capture = capture_record()
out_of_root_capture["pages_touched"] = ["wiki/analyses/fixture.md", "secret/leak.md"]
run_validator(
    "capture-out-of-root-scope-fails",
    [approval_schema(), out_of_root_capture],
    1,
    ("allowed root",),
)
for unsafe_name, unsafe_path, marker in (
    ("dot-component", "wiki/./analyses/fixture.md", "allowed root"),
    ("parent-component", "wiki/analyses/../fixture.md", "allowed root"),
    ("absolute", "/tmp/fixture.md", "allowed root"),
    ("backslash", "wiki\\analyses\\fixture.md", "allowed root"),
    ("uri", "file:wiki/analyses/fixture.md", "allowed root"),
    ("duplicate-separator", "wiki//analyses/fixture.md", "allowed root"),
    ("removed-archive-root", "archive/new.md", "allowed root"),
):
    unsafe_record = capture_record()
    unsafe_record["primary_home"] = unsafe_path
    unsafe_record["pages_touched"] = [unsafe_path]
    run_validator(
        f"capture-{unsafe_name}-scope-fails",
        [approval_schema(), unsafe_record],
        1,
        (marker,),
    )
home_not_touched_capture = capture_record()
home_not_touched_capture["primary_home"] = "wiki/analyses/other.md"
run_validator(
    "capture-primary-home-not-in-pages-touched-fails",
    [approval_schema(), home_not_touched_capture],
    1,
    ("primary_home must be included in pages_touched",),
)
run_validator(
    "capture-missing-schema-fails",
    [capture_record()],
    1,
    ("expected exactly one schema record",),
)
run_validator(
    "capture-duplicate-schema-fails",
    [approval_schema(), approval_schema(), capture_record()],
    1,
    ("expected exactly one schema record",),
)
run_validator(
    "capture-schema-not-first-fails",
    [capture_record(), approval_schema()],
    1,
    ("schema record must be the first line",),
)

run_validator(
    "synthesis-valid-passes",
    [approval_schema(), synthesis_record()],
    0,
    ("validation passed",),
)
synthesis_with_capture_fields = synthesis_record()
synthesis_with_capture_fields.update({
    "word_count_source": "unmeasured",
    "word_count_path": "",
    "draft_sha256": "a" * 64,
    "authored_sha256": "b" * 64,
    "authored_hash_policy": "strip_referenced_by_v1",
})
run_validator(
    "synthesis-rejects-capture-measurement-fields",
    [approval_schema(), synthesis_with_capture_fields],
    1,
    ("must not carry capture measurement fields",),
)
run_validator(
    "synthesis-malformed-json-fails",
    [approval_schema(), "{not json"],
    1,
    ("invalid JSON",),
)
duplicate_synthesis = synthesis_record()
duplicate_synthesis_later = synthesis_record()
duplicate_synthesis_later["approved_at"] = "2026-06-16T00:00:00+00:00"
run_validator(
    "synthesis-duplicate-approval-fails",
    [approval_schema(), duplicate_synthesis, duplicate_synthesis_later],
    1,
    ("duplicate approval record",),
)
pending_synthesis = synthesis_record()
pending_synthesis["approval_status"] = "pending"
run_validator(
    "synthesis-pending-status-fails",
    [approval_schema(), pending_synthesis],
    1,
    ("approval_status must be approved",),
)
bad_synthesis_ledger = synthesis_record()
bad_synthesis_ledger["ledger_update_required"] = False
run_validator(
    "synthesis-home-ledger-flag-fails",
    [approval_schema(), bad_synthesis_ledger],
    1,
    ("ledger_update_required true",),
)
synthesis_home_not_touched = synthesis_record()
synthesis_home_not_touched["primary_home"] = "wiki/overview.md"
synthesis_home_not_touched["pages_touched"] = ["wiki/synthesis.md", "wiki/log.md"]
synthesis_home_not_touched["ledger_update_required"] = False
run_validator(
    "synthesis-primary-home-not-in-pages-touched-fails",
    [approval_schema(), synthesis_home_not_touched],
    1,
    ("primary_home must be included in pages_touched",),
)
missing_ledger_flag = synthesis_record()
missing_ledger_flag["primary_home"] = "wiki/overview.md"
missing_ledger_flag["pages_touched"] = ["wiki/overview.md", "wiki/index.md"]
del missing_ledger_flag["ledger_update_required"]
run_validator(
    "synthesis-ledger-flag-not-boolean-fails",
    [approval_schema(), missing_ledger_flag],
    1,
    ("ledger_update_required must be a boolean",),
)
out_of_root_synthesis = synthesis_record()
out_of_root_synthesis["pages_touched"] = ["wiki/synthesis.md", "secret/leak.md"]
run_validator(
    "synthesis-out-of-root-scope-fails",
    [approval_schema(), out_of_root_synthesis],
    1,
    ("allowed root",),
)
# Reverse ledger-flag check: a non-synthesis.md home may not claim a ledger
# update is required.
reverse_ledger_flag = synthesis_record()
reverse_ledger_flag["primary_home"] = "wiki/overview.md"
reverse_ledger_flag["pages_touched"] = ["wiki/overview.md", "wiki/log.md"]
reverse_ledger_flag["ledger_update_required"] = True
run_validator(
    "synthesis-reverse-ledger-flag-fails",
    [approval_schema(), reverse_ledger_flag],
    1,
    ("unless primary_home is wiki/synthesis.md",),
)
run_validator(
    "synthesis-missing-schema-fails",
    [synthesis_record()],
    1,
    ("expected exactly one schema record",),
)
run_validator(
    "synthesis-duplicate-schema-fails",
    [approval_schema(), approval_schema(), synthesis_record()],
    1,
    ("expected exactly one schema record",),
)
run_validator(
    "synthesis-schema-not-first-fails",
    [synthesis_record(), approval_schema()],
    1,
    ("schema record must be the first line",),
)

# Structural and per-field branches: blank lines, timestamps, analysis
# thresholds, promotion triggers, backfill rules, and placeholder scopes.
run_validator(
    "blank-line-fails",
    [approval_schema(), "", capture_record()],
    1,
    ("blank lines are not allowed",),
)
bad_timestamp = capture_record()
bad_timestamp["approved_at"] = "mid-June sometime"
run_validator(
    "capture-bad-timestamp-fails",
    [approval_schema(), bad_timestamp],
    1,
    ("ISO-8601",),
)
below_bar = capture_record()
below_bar["word_count"] = 200
run_validator(
    "analysis-below-word-bar-fails",
    [approval_schema(), below_bar],
    1,
    ("3+ pages, >300 words",),
)
empty_trigger_promo = capture_record()
empty_trigger_promo["route"] = "promotion-audit"
empty_trigger_promo["triggers"] = []
run_validator(
    "promotion-empty-triggers-fails",
    [approval_schema(), empty_trigger_promo],
    1,
    ("at least one trigger",),
)
backfill_no_source = capture_record()
backfill_no_source["backfilled"] = True
run_validator(
    "backfill-without-source-fails",
    [approval_schema(), backfill_no_source],
    1,
    ("backfill_source",),
)
backfill_not_bool = capture_record()
backfill_not_bool["backfilled"] = "yes"
run_validator(
    "backfill-non-boolean-fails",
    [approval_schema(), backfill_not_bool],
    1,
    ("backfilled must be a boolean",),
)
# Backfilled records may reference paths that predate the current roots.
backfill_legacy_root = capture_record()
backfill_legacy_root["backfilled"] = True
backfill_legacy_root["backfill_source"] = "wiki/log.md entry 2026-05-01"
backfill_legacy_root["pages_touched"] = ["wiki/analyses/fixture.md", "legacy/old.md"]
run_validator(
    "backfill-legacy-root-passes",
    [approval_schema(), backfill_legacy_root],
    0,
    ("validation passed",),
)
# bool subclasses int in Python (True == 1), so integer-shaped fields must
# reject booleans explicitly; these would all pass under bare isinstance/==.
bool_word_count = capture_record()
bool_word_count["synthesized_pages"] = True
bool_word_count["word_count"] = True
run_validator(
    "capture-boolean-counts-fail",
    [approval_schema(), bool_word_count],
    1,
    ("synthesized_pages must be a non-negative integer",
     "word_count must be a non-negative integer"),
)
bool_schema_version = capture_record()
bool_schema_version["schema_version"] = True
run_validator(
    "capture-boolean-schema-version-fails",
    [approval_schema(), bool_schema_version],
    1,
    ("approval record must have schema_version 1",),
)
placeholder_pages = capture_record()
placeholder_pages["pages_touched"] = ["wiki/analyses/fixture.md", "wiki/<entity>/x.md"]
run_validator(
    "capture-placeholder-pages-fails",
    [approval_schema(), placeholder_pages],
    1,
    ("placeholder paths",),
)
placeholder_home = capture_record()
placeholder_home["primary_home"] = "wiki/analyses/<slug>.md"
placeholder_home["pages_touched"] = ["wiki/analyses/<slug>.md", "wiki/index.md"]
run_validator(
    "capture-placeholder-home-fails",
    [approval_schema(), placeholder_home],
    1,
    ("primary_home must not be a placeholder",),
)

# The unparseable-cutoff guard must survive python -O. The probe breaks the
# cutoff constant in the module source and executes it under -O: the plain
# raise fails loudly with the marker; the old assert version is stripped by -O
# and the probe completes silently (or dies later with a different error),
# so this distinguishes the two implementations.
GUARD_PROBE = (
    "import sys\n"
    "sys.path.insert(0, 'scripts')\n"
    "src = open('scripts/validate_capture_runs.py').read()\n"
    "src = src.replace('\"2026-07-08T17:11:14Z\"', '\"junk\"', 1)\n"
    "exec(compile(src, 'probe', 'exec'), {'__name__': 'probe'})\n"
)
probe = subprocess.run(
    [sys.executable, "-O", "-c", GUARD_PROBE],
    text=True, capture_output=True, check=False, cwd=REPO_ROOT,
)
results.record(
    "cutoff-guard-survives-python-O",
    probe.returncode != 0 and "not a parseable timestamp" in probe.stderr,
    f"exit {probe.returncode}; stderr tail: {probe.stderr.strip()[-200:]}",
)
live_o = subprocess.run(
    [sys.executable, "-O", str(APPROVAL_VALIDATOR)],
    text=True, capture_output=True, check=False, cwd=REPO_ROOT,
)
results.record(
    "live-ledger-validates-under-python-O",
    live_o.returncode == 0 and "validation passed" in live_o.stdout,
    f"exit {live_o.returncode}; output: {live_o.stdout.strip()}",
)

sys.exit(results.finish())
