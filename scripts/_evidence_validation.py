#!/usr/bin/env python3
"""Validate exact sample, batch, prompt, verdict, and working-tree fidelity."""

from __future__ import annotations

import stat
from collections import Counter
from pathlib import Path

from _evidence_fidelity import (
    EvidenceError,
    counter_differences,
    load_json,
    render_prompt,
    evidence_sha256_bytes,
    validate_batch,
    validate_plant,
    validate_sample,
    validate_verdict_file,
)

def _load_collect(path: Path, label: str, errors: list[str]) -> object | None:
    try:
        return load_json(path)
    except EvidenceError as exc:
        errors.append(f"{label}: {exc}")
        return None


def _safe_file(root: Path, relative: str) -> tuple[bytes | None, str | None]:
    path = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            return None, f"cannot inspect {relative}: {exc}"
        if stat.S_ISLNK(mode):
            return None, f"sampled path contains symlink: {relative}"
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            return None, f"sampled path is not a regular file: {relative}"
        content = path.read_bytes()
        content.decode("utf-8")
        return content, None
    except (OSError, UnicodeError) as exc:
        return None, f"cannot reread {relative} as UTF-8: {exc}"


def _safe_artifact_directory(path: Path, label: str, errors: list[str]) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    except OSError as exc:
        errors.append(f"{label}: cannot inspect directory: {exc}")
        return False
    if not stat.S_ISDIR(mode):
        errors.append(f"{label}: artifact path is not a regular directory")
        return False
    return True


def _read_prompt(path: Path) -> tuple[str | None, str | None]:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None, "artifact is not a regular file"
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError) as exc:
        return None, str(exc)


def validate_snapshot(repo_root: Path, sample: dict[str, object]) -> list[str]:
    errors: list[str] = []
    cache: dict[str, bytes] = {}
    for claim in sample.get("claims", []):
        if not isinstance(claim, dict) or not isinstance(claim.get("path"), str):
            continue
        relative = claim["path"]
        if relative not in cache:
            content, error = _safe_file(repo_root, relative)
            if error:
                errors.append(error)
                continue
            assert content is not None
            cache[relative] = content
        content = cache.get(relative)
        if content is None:
            continue
        if evidence_sha256_bytes(content) != claim.get("file_sha256"):
            errors.append(f"STALE SNAPSHOT: file hash changed for {relative}")
            continue
        lines = content.decode("utf-8").splitlines(keepends=True)
        line_number = claim.get("line_number")
        if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 1 or line_number > len(lines):
            errors.append(f"STALE SNAPSHOT: line number missing for {relative}:{line_number}")
            continue
        line = lines[line_number - 1]
        if line != claim.get("line_text") or evidence_sha256_bytes(line.encode("utf-8")) != claim.get("line_sha256"):
            errors.append(f"STALE SNAPSHOT: line bytes changed for {relative}:{line_number}")
    return errors


def validate_run(repo_root: Path, run_dir: Path) -> dict[str, object]:
    errors: list[str] = []
    run_id = run_dir.name
    sample = _load_collect(run_dir / "sample.json", "sample", errors)
    plant = _load_collect(run_dir / "plant.json", "plant", errors)
    sample_errors: list[str] = []
    plant_errors: list[str] = []
    if sample is not None:
        sample_errors = validate_sample(sample)
        errors.extend(sample_errors)
        if sample.get("run_id") != run_id:
            errors.append("sample: run_id does not match run directory")
    if plant is not None and sample is not None:
        plant_errors = validate_plant(plant, sample)
        errors.extend(plant_errors)

    batch_dir = run_dir / "batches"
    prompt_dir = run_dir / "prompts"
    verdict_dir = run_dir / "verdicts"
    batch_safe = _safe_artifact_directory(batch_dir, "batches", errors)
    prompt_safe = _safe_artifact_directory(prompt_dir, "prompts", errors)
    verdict_safe = _safe_artifact_directory(verdict_dir, "verdicts", errors)
    batch_paths = sorted(batch_dir.glob("batch-*.json")) if batch_safe else []
    if len(batch_paths) not in {2, 3}:
        errors.append(f"batches: expected exactly 2 or 3 batch files, found {len(batch_paths)}")
    expected_batch_names = [f"batch-{index:02d}.json" for index in range(1, len(batch_paths) + 1)]
    if [path.name for path in batch_paths] != expected_batch_names:
        errors.append("batches: filenames must be contiguous from batch-01.json")
    if batch_safe:
        extras = sorted(path.name for path in batch_dir.iterdir() if path.name not in expected_batch_names)
        if extras:
            errors.append(f"batches: unknown entries {extras}")

    batches: list[dict[str, object]] = []
    all_items: list[dict[str, object]] = []
    for path in batch_paths:
        batch = _load_collect(path, path.name, errors)
        if batch is None:
            continue
        batch_errors = validate_batch(batch)
        errors.extend(f"{path.name}: {error}" for error in batch_errors)
        expected_id = path.stem
        if batch.get("batch_id") != expected_id:
            errors.append(f"{path.name}: batch_id does not match filename")
        if sample is not None:
            if batch.get("run_id") != sample.get("run_id"):
                errors.append(f"{path.name}: run_id does not match sample")
            if batch.get("manifest_sha256") != sample.get("manifest_sha256"):
                errors.append(f"{path.name}: manifest does not match sample")
        prompt_path = prompt_dir / f"{expected_id}.md"
        prompt, prompt_error = _read_prompt(prompt_path) if prompt_safe else (None, "prompt directory is unavailable")
        if prompt_error:
            errors.append(f"{prompt_path.name}: cannot read prompt: {prompt_error}")
        elif prompt is not None:
            if not batch_errors and prompt != render_prompt(batch):
                errors.append(f"{prompt_path.name}: prompt is not the exact batch render or reveals hidden metadata")
        batches.append(batch)
        if isinstance(batch.get("items"), list):
            all_items.extend(item for item in batch["items"] if isinstance(item, dict))

    if prompt_safe:
        expected_prompts = {path.with_suffix(".md").name for path in batch_paths}
        extras = sorted(path.name for path in prompt_dir.iterdir() if path.name not in expected_prompts)
        if extras:
            errors.append(f"prompts: unknown entries {extras}")

    if sample is not None and plant is not None and not sample_errors and not plant_errors:
        expected_claims = Counter(claim["claim_id"] for claim in sample["claims"])
        actual_claims = Counter(
            item.get("source_id") for item in all_items if item.get("kind") == "claim"
        )
        errors.extend(counter_differences(expected_claims, actual_claims, "sample-to-batch claims"))
        expected_plant = Counter({plant["plant_id"]: 1})
        actual_plant = Counter(
            item.get("source_id") for item in all_items if item.get("kind") == "plant"
        )
        errors.extend(counter_differences(expected_plant, actual_plant, "plant-to-batch"))
        claim_lookup = {claim["claim_id"]: claim for claim in sample["claims"]}
        for item in all_items:
            source = claim_lookup.get(item.get("source_id")) if item.get("kind") == "claim" else plant if item.get("kind") == "plant" else None
            if source is None:
                continue
            expected_text = source["line_text"] if item.get("kind") == "claim" else source["text"]
            for key, expected in (
                ("path", source["path"]),
                ("line_number", source["line_number"]),
                ("text", expected_text),
                ("cited_slugs", source["cited_slugs"]),
            ):
                if item.get(key) != expected:
                    errors.append(f"batch item {item.get('item_id')}: {key} differs from its source artifact")

    assigned_ids = Counter(item.get("item_id") for item in all_items)
    if any(count != 1 for count in assigned_ids.values()):
        errors.append(f"batches: duplicate item IDs {dict(assigned_ids)}")
    returned_ids: Counter = Counter()
    plant_verdict: str | None = None
    real_verdicts: list[str] = []
    verdict_paths = sorted(verdict_dir.glob("batch-*.json")) if verdict_safe else []
    expected_verdict_names = {path.name for path in batch_paths}
    if {path.name for path in verdict_paths} != expected_verdict_names:
        missing = expected_verdict_names - {path.name for path in verdict_paths}
        extra = {path.name for path in verdict_paths} - expected_verdict_names
        if missing:
            errors.append(f"verdicts: missing files {sorted(missing)}")
        if extra:
            errors.append(f"verdicts: unknown files {sorted(extra)}")
    item_by_id = {item.get("item_id"): item for item in all_items}
    for path in verdict_paths:
        data = _load_collect(path, path.name, errors)
        if data is None:
            continue
        errors.extend(f"{path.name}: {error}" for error in validate_verdict_file(data))
        if data.get("batch_id") != path.stem:
            errors.append(f"{path.name}: batch_id does not match filename")
        if sample is not None and data.get("run_id") != sample.get("run_id"):
            errors.append(f"{path.name}: run_id does not match sample")
        for verdict in data.get("verdicts", []) if isinstance(data.get("verdicts"), list) else []:
            if not isinstance(verdict, dict):
                continue
            item_id = verdict.get("item_id")
            returned_ids[item_id] += 1
            item = item_by_id.get(item_id)
            if item and item.get("kind") == "plant":
                plant_verdict = verdict.get("verdict")
            elif item and item.get("kind") == "claim" and isinstance(verdict.get("verdict"), str):
                real_verdicts.append(verdict["verdict"])
    errors.extend(counter_differences(assigned_ids, returned_ids, "batch-to-verdict item IDs"))
    if plant_verdict == "VERIFIED":
        errors.append("plant: returned VERIFIED instead of being caught")
    elif plant_verdict is None:
        errors.append("plant: no unique verdict was returned")

    stale_errors = validate_snapshot(repo_root, sample) if sample is not None and not sample_errors else []
    errors.extend(stale_errors)
    stale = bool(stale_errors)
    status = "STALE SNAPSHOT" if stale else ("PASSED" if not errors else "FAILED")
    metrics = None if errors else {
        "sampled": len(sample.get("claims", [])) if isinstance(sample, dict) else 0,
        "batches": len(batch_paths),
        "flagged": sum(verdict != "VERIFIED" for verdict in real_verdicts),
        "plant_verdict": plant_verdict,
    }
    return {
        "schema_version": 1,
        "run_id": run_id,
        "manifest_sha256": sample.get("manifest_sha256") if isinstance(sample, dict) else None,
        "status": status,
        "errors": errors,
        "metrics": metrics,
    }


__all__ = ["validate_run"]
