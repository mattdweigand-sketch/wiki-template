#!/usr/bin/env python3
"""Typed production interface for exact evidence-fidelity runs."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence, cast

from _evidence_fidelity import (
    EvidenceError as EvidenceRunError,
    VERDICTS,
    atomic_json,
    build_batches,
    build_sample_data,
    canonical_json,
    load_json,
    render_prompt,
    safe_run_dir,
    validate_sample,
)
from _evidence_validation import validate_run


EvidenceRunStatus = Literal["PASSED", "FAILED", "STALE SNAPSHOT"]
EvidenceStructure = Literal["VALID", "INVALID"]
EvidenceSnapshot = Literal["CURRENT", "STALE"]
EvidenceReview = Literal["CLEAR", "FLAGGED", "INCOMPLETE"]


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
    verified: int
    flagged: int
    missing: int
    plant_verdict: str


@dataclass(frozen=True)
class EvidenceRunValidation:
    run_id: str
    manifest_sha256: str | None
    status: EvidenceRunStatus
    structure: EvidenceStructure
    snapshot: EvidenceSnapshot
    review: EvidenceReview
    flagged_ids: tuple[str, ...]
    errors: tuple[str, ...]
    metrics: EvidenceRunMetrics | None


@dataclass(frozen=True)
class EvidenceResponseStatement:
    text: str
    claim_ids: tuple[str, ...]


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


def create_targeted_evidence_sample(
    repo_root: Path,
    run_id: str,
    page_paths: Sequence[str],
) -> EvidenceSampleManifest:
    """Create an immutable sample of every cited claim on exact entity pages."""
    root = repo_root.resolve()
    payload = build_sample_data(root, run_id, included_paths=page_paths)
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
            verified=_required_int(raw_metrics, "verified"),
            flagged=_required_int(raw_metrics, "flagged"),
            missing=_required_int(raw_metrics, "missing"),
            plant_verdict=_required_string(raw_metrics, "plant_verdict"),
        )
    manifest = payload.get("manifest_sha256")
    if manifest is not None and not isinstance(manifest, str):
        raise EvidenceRunError("evidence validation returned an invalid manifest hash")
    structure = payload.get("structure")
    snapshot = payload.get("snapshot")
    review = payload.get("review")
    flagged_ids = payload.get("flagged_ids")
    if structure not in {"VALID", "INVALID"}:
        raise EvidenceRunError("evidence validation returned an invalid structure")
    if snapshot not in {"CURRENT", "STALE"}:
        raise EvidenceRunError("evidence validation returned an invalid snapshot")
    if review not in {"CLEAR", "FLAGGED", "INCOMPLETE"}:
        raise EvidenceRunError("evidence validation returned an invalid review")
    if not isinstance(flagged_ids, list) or not all(
        isinstance(claim_id, str) for claim_id in flagged_ids
    ):
        raise EvidenceRunError("evidence validation returned invalid flagged_ids")
    return EvidenceRunValidation(
        run_id=_required_string(payload, "run_id"),
        manifest_sha256=manifest,
        status=cast(EvidenceRunStatus, raw_status),
        structure=cast(EvidenceStructure, structure),
        snapshot=cast(EvidenceSnapshot, snapshot),
        review=cast(EvidenceReview, review),
        flagged_ids=tuple(flagged_ids),
        errors=tuple(raw_errors),
        metrics=metrics,
    )


def _response_statement_digest(text: str, claim_ids: Sequence[str]) -> str:
    return hashlib.sha256(
        canonical_json({"claim_ids": list(claim_ids), "text": text})
    ).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def create_evidence_response_packet(
    repo_root: Path,
    run_dir: Path,
    question: str,
    statements: Sequence[EvidenceResponseStatement],
) -> Path:
    """Write one exact response packet bound to sampled claims and raw closure."""
    root = repo_root.resolve()
    resolved_run = safe_run_dir(root, run_dir.as_posix())
    if not question.strip():
        raise EvidenceRunError("response question must be nonempty")
    if not statements:
        raise EvidenceRunError("response packet requires at least one statement")
    sample = cast(dict[str, object], load_json(resolved_run / "sample.json"))
    sample_errors = validate_sample(sample)
    if sample_errors:
        raise EvidenceRunError("invalid evidence sample: " + "; ".join(sample_errors))
    claims = {
        claim["claim_id"]: claim
        for claim in sample["claims"]
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    response_statements: list[dict[str, object]] = []
    used_claims: list[dict[str, object]] = []
    for index, statement in enumerate(statements, start=1):
        if not statement.text.strip():
            raise EvidenceRunError(f"statement {index} text must be nonempty")
        if not statement.claim_ids or len(statement.claim_ids) != len(set(statement.claim_ids)):
            raise EvidenceRunError(f"statement {index} claim_ids must be nonempty and unique")
        missing = [claim_id for claim_id in statement.claim_ids if claim_id not in claims]
        if missing:
            raise EvidenceRunError(f"statement {index} has unknown claim IDs: {missing}")
        used_claims.extend(claims[claim_id] for claim_id in statement.claim_ids)
        response_statements.append({
            "statement_id": f"statement-{index:03d}",
            "text": statement.text,
            "claim_ids": list(statement.claim_ids),
            "statement_sha256": _response_statement_digest(
                statement.text, statement.claim_ids,
            ),
        })
    closures: dict[str, dict[str, object]] = {}
    for claim in used_claims:
        for source in claim.get("source_closure", []):
            if isinstance(source, dict) and isinstance(source.get("source_slug"), str):
                closures[source["source_slug"]] = source
    packet = {
        "schema_version": 1,
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "evidence_snapshot_sha256": sample["manifest_sha256"],
        "statements": response_statements,
        "source_closure": [closures[slug] for slug in sorted(closures)],
    }
    path = resolved_run / "response.json"
    if path.exists() or path.is_symlink():
        raise EvidenceRunError("response.json already exists; use a fresh run")
    atomic_json(path, packet)
    return path


def _validated_response_artifacts(
    run_dir: Path, sample: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    packet = load_json(run_dir / "response.json")
    review = load_json(run_dir / "response-review.json")
    if not isinstance(packet, dict) or set(packet) != {
        "schema_version", "question_sha256", "evidence_snapshot_sha256",
        "statements", "source_closure",
    }:
        raise EvidenceRunError("response packet fields are invalid")
    if packet.get("schema_version") != 1:
        raise EvidenceRunError("response packet schema_version must be 1")
    if not _is_sha256(packet.get("question_sha256")):
        raise EvidenceRunError("response packet question_sha256 is invalid")
    if packet.get("evidence_snapshot_sha256") != sample.get("manifest_sha256"):
        raise EvidenceRunError("response packet evidence snapshot is stale")
    statements = packet.get("statements")
    if not isinstance(statements, list) or not statements:
        raise EvidenceRunError("response packet statements are invalid")
    expected_ids: list[str] = []
    claims = {
        claim["claim_id"]: claim
        for claim in sample["claims"]
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    expected_closures: dict[str, dict[str, object]] = {}
    for index, statement in enumerate(statements, start=1):
        expected_id = f"statement-{index:03d}"
        if not isinstance(statement, dict) or set(statement) != {
            "statement_id", "text", "claim_ids", "statement_sha256"
        }:
            raise EvidenceRunError(f"{expected_id} fields are invalid")
        text = statement.get("text")
        claim_ids = statement.get("claim_ids")
        if statement.get("statement_id") != expected_id:
            raise EvidenceRunError("response statement IDs must be ordered and contiguous")
        if not isinstance(text, str) or not text.strip():
            raise EvidenceRunError(f"{expected_id} text is invalid")
        if not isinstance(claim_ids, list) or not claim_ids or not all(
            isinstance(claim_id, str) for claim_id in claim_ids
        ):
            raise EvidenceRunError(f"{expected_id} claim_ids are invalid")
        if len(claim_ids) != len(set(claim_ids)) or any(
            claim_id not in claims for claim_id in claim_ids
        ):
            raise EvidenceRunError(f"{expected_id} claim_ids are unknown or duplicated")
        for claim_id in claim_ids:
            for source in claims[claim_id].get("source_closure", []):
                if isinstance(source, dict) and isinstance(source.get("source_slug"), str):
                    expected_closures[source["source_slug"]] = source
        if statement.get("statement_sha256") != _response_statement_digest(text, claim_ids):
            raise EvidenceRunError(f"{expected_id} content changed after packet creation")
        expected_ids.append(expected_id)
    if packet.get("source_closure") != [
        expected_closures[slug] for slug in sorted(expected_closures)
    ]:
        raise EvidenceRunError("response packet source closure is incomplete or changed")
    if not isinstance(review, dict) or set(review) != {
        "schema_version", "evidence_snapshot_sha256", "statements"
    }:
        raise EvidenceRunError("response review fields are invalid")
    if review.get("schema_version") != 1:
        raise EvidenceRunError("response review schema_version must be 1")
    if review.get("evidence_snapshot_sha256") != sample.get("manifest_sha256"):
        raise EvidenceRunError("response review evidence snapshot is stale")
    review_items = review.get("statements")
    if not isinstance(review_items, list):
        raise EvidenceRunError("response review statements are invalid")
    reviews: dict[str, dict[str, object]] = {}
    for item in review_items:
        if not isinstance(item, dict) or set(item) != {
            "statement_id", "statement_sha256", "verdict"
        }:
            raise EvidenceRunError("response review statement fields are invalid")
        statement_id = item.get("statement_id")
        if not isinstance(statement_id, str) or statement_id in reviews:
            raise EvidenceRunError("response review statement IDs are invalid")
        if item.get("verdict") not in VERDICTS:
            raise EvidenceRunError(f"{statement_id} has an invalid response verdict")
        reviews[statement_id] = item
    if list(reviews) != expected_ids:
        raise EvidenceRunError("response review must cover every statement exactly once")
    for statement in statements:
        review_item = reviews[statement["statement_id"]]
        if review_item.get("statement_sha256") != statement.get("statement_sha256"):
            raise EvidenceRunError(f"{statement['statement_id']} changed after response review")
    return statements, reviews


def render_verified_evidence_response(repo_root: Path, run_dir: Path) -> str:
    """Render current, independently reviewed statements with adjacent citations."""
    root = repo_root.resolve()
    resolved_run = safe_run_dir(root, run_dir.as_posix())
    validation = validate_evidence_run(root, resolved_run.relative_to(root))
    if validation.structure != "VALID" or validation.snapshot != "CURRENT":
        raise EvidenceRunError("evidence run is invalid or stale")
    sample = cast(dict[str, object], load_json(resolved_run / "sample.json"))
    claims = {
        claim["claim_id"]: claim
        for claim in sample["claims"]
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    statements, reviews = _validated_response_artifacts(resolved_run, sample)
    rendered: list[str] = []
    withheld = 0
    flagged_claims = set(validation.flagged_ids)
    for statement in statements:
        claim_ids = cast(list[str], statement["claim_ids"])
        review = reviews[cast(str, statement["statement_id"])]
        if review["verdict"] != "VERIFIED" or any(
            claim_id in flagged_claims for claim_id in claim_ids
        ):
            withheld += 1
            continue
        pages: list[str] = []
        sources: list[str] = []
        for claim_id in claim_ids:
            claim = claims.get(claim_id)
            if claim is None:
                raise EvidenceRunError(f"response references unknown claim {claim_id}")
            page_slug = Path(cast(str, claim["path"])).stem
            if page_slug not in pages:
                pages.append(page_slug)
            for slug in cast(list[str], claim["cited_slugs"]):
                if slug not in sources:
                    sources.append(slug)
        citations = " ".join(
            [*(f"(wiki: [[{slug}]])" for slug in pages),
             *(f"(source: [[{slug}]])" for slug in sources)]
        )
        rendered.append(f"{statement['text']} {citations}")
    if withheld:
        rendered.append(
            f"Withheld {withheld} statement{'s' if withheld != 1 else ''} "
            "because the evidence or response review was not VERIFIED."
        )
    if not rendered:
        rendered.append("No verified statement could be returned from the current evidence.")
    return "\n\n".join(rendered) + "\n"


__all__ = [
    "EvidenceBatchPlan",
    "EvidenceResponseStatement",
    "EvidenceRunError",
    "EvidenceRunMetrics",
    "EvidenceReview",
    "EvidenceSnapshot",
    "EvidenceStructure",
    "EvidenceRunStatus",
    "EvidenceRunValidation",
    "EvidenceSampleManifest",
    "create_evidence_response_packet",
    "create_evidence_sample",
    "create_targeted_evidence_sample",
    "publish_evidence_batches",
    "render_verified_evidence_response",
    "validate_evidence_run",
]
