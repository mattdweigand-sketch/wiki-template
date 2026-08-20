#!/usr/bin/env python3
"""Typed production interface for exact evidence-fidelity runs."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from _evidence_fidelity import (
    EvidenceError as EvidenceRunError,
    atomic_json,
    build_batches,
    build_sample_data,
    load_json,
    render_prompt,
    safe_run_dir,
)
from _evidence_validation import validate_run


EvidenceRunStatus = Literal["PASSED", "FAILED", "STALE SNAPSHOT"]


@dataclass(frozen=True)
class EvidenceSampleManifest:
    run_dir: Path
    selected_count: int
    population_count: int
    manifest_sha256: str


@dataclass(frozen=True)
class EvidenceBatchPlan:
    run_dir: Path
    batch_count: int


@dataclass(frozen=True)
class EvidenceRunMetrics:
    sampled: int
    batches: int
    flagged: int
    plant_verdict: str


@dataclass(frozen=True)
class EvidenceRunValidation:
    run_id: str
    manifest_sha256: str | None
    status: EvidenceRunStatus
    errors: tuple[str, ...]
    metrics: EvidenceRunMetrics | None


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise EvidenceRunError(f"generated evidence payload has invalid {key}")
    return value


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise EvidenceRunError(f"generated evidence payload has invalid {key}")
    return value


def create_evidence_sample(
    repo_root: Path,
    run_id: str,
    requested_count: int = 25,
) -> EvidenceSampleManifest:
    """Create one OS-random, immutable evidence sample in a fresh run."""
    root = repo_root.resolve()
    payload = build_sample_data(root, run_id, requested_count)
    run_dir = safe_run_dir(root, f"tmp/evidence-check/{run_id}", create=True)
    sample_path = run_dir / "sample.json"
    if sample_path.exists() or sample_path.is_symlink():
        raise EvidenceRunError("sample.json already exists; use a fresh run-id")
    atomic_json(sample_path, payload)
    return EvidenceSampleManifest(
        run_dir=run_dir,
        selected_count=_required_int(payload, "selected_count"),
        population_count=_required_int(payload, "population_count"),
        manifest_sha256=_required_string(payload, "manifest_sha256"),
    )


def _write_batch_plan(run_dir: Path, batches: list[dict[str, object]]) -> None:
    if any(
        path.exists() or path.is_symlink()
        for path in (run_dir / "batches", run_dir / "prompts")
    ):
        raise EvidenceRunError(
            "batches or prompts already exist; use a fresh run or remove the incomplete run"
        )
    staging = Path(tempfile.mkdtemp(prefix=".batch-plan-", dir=run_dir))
    installed: list[Path] = []
    try:
        batch_dir = staging / "batches"
        prompt_dir = staging / "prompts"
        batch_dir.mkdir()
        prompt_dir.mkdir()
        for batch in batches:
            batch_id = _required_string(batch, "batch_id")
            atomic_json(batch_dir / f"{batch_id}.json", batch)
            (prompt_dir / f"{batch_id}.md").write_text(
                render_prompt(batch), encoding="utf-8"
            )
        os.replace(batch_dir, run_dir / "batches")
        installed.append(run_dir / "batches")
        os.replace(prompt_dir, run_dir / "prompts")
        installed.append(run_dir / "prompts")
    except OSError as exc:
        for path in reversed(installed):
            shutil.rmtree(path, ignore_errors=True)
        raise EvidenceRunError(f"cannot install complete batch plan: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def publish_evidence_batches(
    repo_root: Path,
    run_dir: Path,
    batch_count: int,
) -> EvidenceBatchPlan:
    """Validate a sample and manual plant, then atomically publish its batches."""
    root = repo_root.resolve()
    resolved_run = safe_run_dir(root, run_dir.as_posix())
    sample = cast(dict[str, object], load_json(resolved_run / "sample.json"))
    plant = cast(dict[str, object], load_json(resolved_run / "plant.json"))
    batches = build_batches(sample, plant, batch_count)
    _write_batch_plan(resolved_run, batches)
    return EvidenceBatchPlan(run_dir=resolved_run, batch_count=len(batches))


def validate_evidence_run(repo_root: Path, run_dir: Path) -> EvidenceRunValidation:
    """Validate exact artifacts and snapshot fidelity, then persist the result."""
    root = repo_root.resolve()
    resolved_run = safe_run_dir(root, run_dir.as_posix())
    payload = validate_run(root, resolved_run)
    atomic_json(resolved_run / "validation.json", payload)
    raw_status = payload.get("status")
    if raw_status not in {"PASSED", "FAILED", "STALE SNAPSHOT"}:
        raise EvidenceRunError("evidence validation returned an invalid status")
    raw_errors = payload.get("errors")
    if not isinstance(raw_errors, list) or not all(
        isinstance(error, str) for error in raw_errors
    ):
        raise EvidenceRunError("evidence validation returned invalid errors")
    raw_metrics = payload.get("metrics")
    metrics = None
    if isinstance(raw_metrics, dict):
        metrics = EvidenceRunMetrics(
            sampled=_required_int(raw_metrics, "sampled"),
            batches=_required_int(raw_metrics, "batches"),
            flagged=_required_int(raw_metrics, "flagged"),
            plant_verdict=_required_string(raw_metrics, "plant_verdict"),
        )
    manifest = payload.get("manifest_sha256")
    if manifest is not None and not isinstance(manifest, str):
        raise EvidenceRunError("evidence validation returned an invalid manifest hash")
    return EvidenceRunValidation(
        run_id=_required_string(payload, "run_id"),
        manifest_sha256=manifest,
        status=cast(EvidenceRunStatus, raw_status),
        errors=tuple(raw_errors),
        metrics=metrics,
    )


__all__ = [
    "EvidenceBatchPlan",
    "EvidenceRunError",
    "EvidenceRunMetrics",
    "EvidenceRunStatus",
    "EvidenceRunValidation",
    "EvidenceSampleManifest",
    "create_evidence_sample",
    "publish_evidence_batches",
    "validate_evidence_run",
]
