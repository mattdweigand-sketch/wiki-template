#!/usr/bin/env python3
"""Regression suite for exact evidence sample, batch, verdict, and snapshot fidelity."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

import wiki_evidence
from _evidence_fidelity import (
    EvidenceError,
    atomic_json,
    build_sample_data,
    load_json,
    manifest_hash,
    render_prompt,
    safe_run_dir,
    validate_plant,
)
from eval_lib import Results
from wiki_evidence import (
    create_evidence_sample,
    publish_evidence_batches,
    validate_evidence_run,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "scripts/fixtures/wiki-evidence"
results = Results()


def make_repo(root: Path, run_id: str = "fixture-run") -> tuple[Path, dict, dict, list[dict]]:
    wiki = root / "wiki"
    wiki.mkdir(parents=True)
    for source in FIXTURES.glob("*.md"):
        shutil.copyfile(source, wiki / source.name)
    manifest = create_evidence_sample(root, run_id, 25)
    run_dir = manifest.run_dir
    sample = load_json(run_dir / "sample.json")
    source = sample["claims"][0]
    plant = {
        "schema_version": 1,
        "plant_id": "plant-01",
        "source_claim_id": source["claim_id"],
        "text": source["line_text"].rstrip("\n") + " This proves the claim universally.\n",
        "path": source["path"],
        "line_number": source["line_number"],
        "cited_slugs": source["cited_slugs"],
        "invalid_verdict": "VERIFIED",
    }
    assert not validate_plant(plant, sample)
    atomic_json(run_dir / "plant.json", plant)
    publish_evidence_batches(root, run_dir.relative_to(root), 2)
    batches = [load_json(path) for path in sorted((run_dir / "batches").glob("*.json"))]
    verdict_dir = run_dir / "verdicts"
    verdict_dir.mkdir()
    for batch in batches:
        verdicts = []
        for item in batch["items"]:
            verdicts.append(
                {
                    "item_id": item["item_id"],
                    "verdict": "OVEREXTENDED" if item["kind"] == "plant" else "VERIFIED",
                    "decisive_quote": "Fixture decisive quote.",
                    "evidence_paths": [item["path"]],
                }
            )
        atomic_json(
            verdict_dir / f"{batch['batch_id']}.json",
            {"schema_version": 1, "run_id": run_id, "batch_id": batch["batch_id"], "verdicts": verdicts},
        )
    return run_dir, sample, plant, batches


def case(name: str, mutate=None, *, status: str = "FAILED", fragment: str | None = None) -> None:
    with tempfile.TemporaryDirectory(prefix="wiki-evidence-eval-") as td:
        root = Path(td)
        run_dir, sample, plant, batches = make_repo(root)
        if mutate:
            mutate(root, run_dir, sample, plant, batches)
        result = validate_evidence_run(root, run_dir.relative_to(root))
        ok = result.status == status and (
            fragment is None or any(fragment in error for error in result.errors)
        )
        results.record(name, ok, f"result={result}")


case("clean-run-passes", status="PASSED")


def duplicate_for_omitted(_root, run_dir, _sample, _plant, _batches):
    path = run_dir / "batches/batch-02.json"
    batch = load_json(path)
    first = load_json(run_dir / "batches/batch-01.json")["items"][0]
    target_index = next(i for i, item in enumerate(batch["items"]) if item["kind"] == "claim")
    replacement = copy.deepcopy(first)
    replacement["item_id"] = batch["items"][target_index]["item_id"]
    batch["items"][target_index] = replacement
    atomic_json(path, batch)
    (run_dir / "prompts/batch-02.md").write_text(render_prompt(batch), encoding="utf-8")


case("duplicate-for-omitted-fails", duplicate_for_omitted, fragment="sample-to-batch claims")


def missing_verdict(_root, run_dir, *_args):
    path = run_dir / "verdicts/batch-01.json"
    data = load_json(path)
    data["verdicts"].pop()
    atomic_json(path, data)


case("missing-verdict-fails", missing_verdict, fragment="batch-to-verdict item IDs")


def extra_verdict(_root, run_dir, *_args):
    path = run_dir / "verdicts/batch-01.json"
    data = load_json(path)
    duplicate = copy.deepcopy(data["verdicts"][0])
    data["verdicts"].append(duplicate)
    atomic_json(path, data)


case("duplicate-verdict-fails", extra_verdict, fragment="duplicated or excess")


def plant_verified(_root, run_dir, _sample, _plant, batches):
    plant_item = next(item for batch in batches for item in batch["items"] if item["kind"] == "plant")
    for path in (run_dir / "verdicts").glob("*.json"):
        data = load_json(path)
        for verdict in data["verdicts"]:
            if verdict["item_id"] == plant_item["item_id"]:
                verdict["verdict"] = "VERIFIED"
        atomic_json(path, data)


case("plant-verified-fails", plant_verified, fragment="returned VERIFIED")


def stale_source(root, _run_dir, sample, *_args):
    path = root / sample["claims"][0]["path"]
    path.write_text(path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")


case("stale-file-fails-without-metrics", stale_source, status="STALE SNAPSHOT", fragment="STALE SNAPSHOT")


def line_drift(root, _run_dir, sample, *_args):
    path = root / sample["claims"][0]["path"]
    path.write_text("inserted\n" + path.read_text(encoding="utf-8"), encoding="utf-8")


case("line-number-drift-fails", line_drift, status="STALE SNAPSHOT", fragment="STALE SNAPSHOT")


def reveal_plant(_root, run_dir, _sample, _plant, batches):
    plant_batch = next(batch for batch in batches if any(item["kind"] == "plant" for item in batch["items"]))
    path = run_dir / f"prompts/{plant_batch['batch_id']}.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nThe plant is item-005.\n", encoding="utf-8")


case("revealed-plant-prompt-fails", reveal_plant, fragment="prompt is not the exact batch render")


def altered_plant(_root, run_dir, *_args):
    plant = load_json(run_dir / "plant.json")
    plant["line_number"] += 1
    atomic_json(run_dir / "plant.json", plant)


case("altered-plant-location-fails", altered_plant, fragment="must match the source claim")


def bad_hash(_root, run_dir, *_args):
    sample = load_json(run_dir / "sample.json")
    sample["manifest_sha256"] = "0" * 64
    atomic_json(run_dir / "sample.json", sample)


case("bad-manifest-hash-fails", bad_hash, fragment="manifest_sha256 mismatch")


def unknown_field(_root, run_dir, *_args):
    sample = load_json(run_dir / "sample.json")
    sample["unknown"] = True
    sample["manifest_sha256"] = manifest_hash(sample)
    atomic_json(run_dir / "sample.json", sample)


case("unknown-sample-field-fails", unknown_field, fragment="unknown fields")


def duplicate_key(_root, run_dir, *_args):
    path = run_dir / "plant.json"
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace('"plant_id": "plant-01",', '"plant_id": "plant-01",\n  "plant_id": "plant-01",', 1), encoding="utf-8")


case("duplicate-json-key-fails", duplicate_key, fragment="duplicate JSON key")


def symlinked_plant(root, run_dir, *_args):
    outside = root / "outside-plant.json"
    shutil.copyfile(run_dir / "plant.json", outside)
    (run_dir / "plant.json").unlink()
    (run_dir / "plant.json").symlink_to(outside)


case("symlinked-artifact-file-fails", symlinked_plant, fragment="not a regular file")


def symlinked_verdict_directory(root, run_dir, *_args):
    outside = root / "outside-verdicts"
    shutil.move(run_dir / "verdicts", outside)
    (run_dir / "verdicts").symlink_to(outside, target_is_directory=True)


case("symlinked-artifact-directory-fails", symlinked_verdict_directory,
     fragment="not a regular directory")


with tempfile.TemporaryDirectory(prefix="wiki-evidence-determinism-") as td:
    root = Path(td)
    (root / "wiki").mkdir()
    for source in FIXTURES.glob("*.md"):
        shutil.copyfile(source, root / "wiki" / source.name)
    first = build_sample_data(root, "same", 25, injected_seed=42)
    second = build_sample_data(root, "same", 25, injected_seed=42)
    first["created_at"] = second["created_at"] = "fixed"
    first["manifest_sha256"] = manifest_hash(first)
    second["manifest_sha256"] = manifest_hash(second)
    results.record("injected-seed-is-deterministic", first == second, "sample draws differ")
    locations = {(claim["path"], claim["line_number"]) for claim in first["claims"]}
    duplicate_locations = [loc for loc in locations if "alpha.md" in loc[0] or "beta.md" in loc[0]]
    results.record("duplicate-text-locations-remain-distinct", len(locations) == len(first["claims"]) and len(duplicate_locations) >= 2, f"locations={locations}")


with tempfile.TemporaryDirectory(prefix="wiki-evidence-path-") as td:
    root = Path(td)
    for index, bad in enumerate(("/tmp/evidence-check/x", "tmp/evidence-check/../x", "tmp/evidence-check/x/y"), start=1):
        try:
            safe_run_dir(root, bad, create=True)
        except EvidenceError:
            ok = True
        else:
            ok = False
        results.record(f"unsafe-run-path-{index}", ok, f"accepted {bad}")
    (root / "tmp").mkdir(exist_ok=True)
    (root / "tmp/evidence-check").symlink_to(root / "elsewhere")
    try:
        safe_run_dir(root, "tmp/evidence-check/x", create=True)
    except EvidenceError as exc:
        ok = "symlink" in str(exc)
        detail = str(exc)
    else:
        ok = False
        detail = "symlinked run root accepted"
    results.record("symlinked-run-root-fails", ok, detail)


with tempfile.TemporaryDirectory(prefix="wiki-evidence-encoding-") as td:
    root = Path(td)
    (root / "wiki").mkdir()
    (root / "wiki/bad.md").write_bytes(b"\xff source: [[bad]]\n")
    try:
        create_evidence_sample(root, "bad-encoding")
    except EvidenceError as exc:
        ok = "UTF-8" in str(exc)
        detail = str(exc)
    else:
        ok = False
        detail = "non-UTF-8 page accepted"
    results.record("non-utf8-page-fails-before-sample", ok, detail)


with tempfile.TemporaryDirectory(prefix="wiki-evidence-install-fault-") as td:
    root = Path(td)
    run_dir, sample, plant, batches = make_repo(root, "install-fault-base")
    shutil.rmtree(run_dir / "batches")
    shutil.rmtree(run_dir / "prompts")
    shutil.rmtree(run_dir / "verdicts")
    original_replace = wiki_evidence.os.replace

    def fail_prompt_install(source, destination):
        if Path(destination).name == "prompts":
            raise OSError("injected prompt-directory install failure")
        return original_replace(source, destination)

    wiki_evidence.os.replace = fail_prompt_install
    try:
        try:
            publish_evidence_batches(root, run_dir.relative_to(root), 2)
        except EvidenceError:
            failed = True
        else:
            failed = False
    finally:
        wiki_evidence.os.replace = original_replace
    results.record(
        "batch-install-failure-leaves-no-partial-authority",
        failed and not (run_dir / "batches").exists() and not (run_dir / "prompts").exists(),
        f"batches={(run_dir / 'batches').exists()} prompts={(run_dir / 'prompts').exists()}",
    )

sys.exit(results.finish())
