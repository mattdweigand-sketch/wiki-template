#!/usr/bin/env python3
"""Strict schemas and pure helpers for one live wiki evidence-check run."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import secrets
import stat
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from _strict_json import reject_duplicate_json_keys
from _wiki_parse import evidentiary_line_views, get_entity_pages
from wiki_provenance import RawSourceClosure, resolve_live_source_closure


SCHEMA_VERSION = 1
VERDICTS = ("VERIFIED", "OVEREXTENDED", "CONFLATED", "MISMATCH", "NOT-FOUND")
SAMPLE_FIELDS = frozenset(
    {
        "schema_version", "run_id", "created_at", "seed", "requested_count",
        "population_count", "selected_count", "git", "claims",
        "raw_manifest_sha256", "manifest_sha256",
    }
)
CLAIM_FIELDS = frozenset(
    {
        "claim_id", "path", "line_number", "line_text", "line_sha256",
        "file_sha256", "cited_slugs", "source_closure",
    }
)
PLANT_FIELDS = frozenset(
    {"schema_version", "plant_id", "source_claim_id", "text", "path", "line_number", "cited_slugs", "invalid_verdict"}
)
BATCH_FIELDS = frozenset(
    {"schema_version", "run_id", "manifest_sha256", "batch_id", "item_count", "items"}
)
ITEM_FIELDS = frozenset(
    {"item_id", "kind", "source_id", "path", "line_number", "text", "cited_slugs"}
)
VERDICT_FILE_FIELDS = frozenset({"schema_version", "run_id", "batch_id", "verdicts"})
VERDICT_FIELDS = frozenset({"item_id", "verdict", "decisive_quote", "evidence_paths"})
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
CITATION_RE = re.compile(
    r"\(source:\s*\[\[([a-z0-9]+(?:-[a-z0-9]+)*)\]\]\)"
)


class EvidenceError(ValueError):
    """One evidence artifact or path violated the run contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def evidence_sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def manifest_hash(sample: dict[str, object]) -> str:
    without_hash = {key: value for key, value in sample.items() if key != "manifest_sha256"}
    return evidence_sha256_bytes(canonical_json(without_hash))


def atomic_json(path: Path, data: object) -> None:
    content = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            view = memoryview(content)
            while view:
                written = handle.write(view)
                if written is None or written <= 0:
                    raise OSError("zero-progress write")
                view = view[written:]
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def load_json(path: Path) -> object:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise EvidenceError(f"cannot parse {path}: artifact is not a regular file")
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    except EvidenceError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise EvidenceError(f"cannot parse {path}: {exc}") from exc


def _exact_fields(obj: dict[str, object], fields: frozenset[str], label: str) -> list[str]:
    errors: list[str] = []
    missing = fields - set(obj)
    extra = set(obj) - fields
    if missing:
        errors.append(f"{label}: missing fields {sorted(missing)}")
    if extra:
        errors.append(f"{label}: unknown fields {sorted(extra)}")
    return errors


def _strict_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _canonical_relative(value: object, prefix: str | None = None) -> bool:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    if path.as_posix() != value:
        return False
    return prefix is None or value.startswith(prefix)


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _validate_source_closure(value: object, cited_slugs: object, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list) or not value:
        return [f"{label}: source_closure must be a nonempty list"]
    closure_slugs: list[str] = []
    for index, source in enumerate(value):
        source_label = f"{label}.source_closure[{index}]"
        if not isinstance(source, dict) or set(source) != {
            "source_slug", "source_path", "source_sha256", "files"
        }:
            errors.append(f"{source_label}: invalid fields")
            continue
        slug = source.get("source_slug")
        closure_slugs.append(slug if isinstance(slug, str) else "")
        if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
            errors.append(f"{source_label}: invalid source_slug")
        if source.get("source_path") != f"wiki/sources/{slug}.md":
            errors.append(f"{source_label}: source_path does not match source_slug")
        if not _sha(source.get("source_sha256")):
            errors.append(f"{source_label}: invalid source_sha256")
        files = source.get("files")
        if not isinstance(files, list) or not files:
            errors.append(f"{source_label}: files must be a nonempty list")
            continue
        paths: list[str] = []
        for file_index, member in enumerate(files):
            file_label = f"{source_label}.files[{file_index}]"
            if not isinstance(member, dict) or set(member) != {"path", "size", "sha256"}:
                errors.append(f"{file_label}: invalid fields")
                continue
            path = member.get("path")
            if not _canonical_relative(path, "raw/"):
                errors.append(f"{file_label}: invalid raw path")
            else:
                paths.append(path)
            if not _strict_int(member.get("size")):
                errors.append(f"{file_label}: invalid size")
            if not _sha(member.get("sha256")):
                errors.append(f"{file_label}: invalid sha256")
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            errors.append(f"{source_label}: files must be sorted and unique")
    if isinstance(cited_slugs, list) and closure_slugs != cited_slugs:
        errors.append(f"{label}: source_closure does not match cited_slugs")
    return errors


def _closure_payload(closure: RawSourceClosure) -> dict[str, object]:
    return {
        "source_slug": closure.source_slug,
        "source_path": closure.source_path,
        "source_sha256": closure.source_sha256,
        "files": [
            {"path": member.path, "size": member.size, "sha256": member.sha256}
            for member in closure.files
        ],
    }


def validate_sample(sample: object) -> list[str]:
    if not isinstance(sample, dict):
        return ["sample must be an object"]
    errors = _exact_fields(sample, SAMPLE_FIELDS, "sample")
    if sample.get("schema_version") != SCHEMA_VERSION or isinstance(sample.get("schema_version"), bool):
        errors.append("sample: schema_version must be integer 1")
    if not isinstance(sample.get("run_id"), str) or not RUN_ID_RE.fullmatch(sample["run_id"]):
        errors.append("sample: invalid run_id")
    if not isinstance(sample.get("created_at"), str) or not sample["created_at"]:
        errors.append("sample: created_at must be nonempty")
    for key in ("seed", "requested_count", "population_count", "selected_count"):
        if not _strict_int(sample.get(key), minimum=0):
            errors.append(f"sample: {key} must be a nonnegative integer")
    git = sample.get("git")
    if not isinstance(git, dict) or set(git) != {"head", "dirty"}:
        errors.append("sample: git must contain exactly head and dirty")
    elif (git["head"] is not None and not _sha(git["head"])) or (
        git["dirty"] is not None and not isinstance(git["dirty"], bool)
    ):
        errors.append("sample: invalid diagnostic git metadata")
    if not _sha(sample.get("raw_manifest_sha256")):
        errors.append("sample: invalid raw_manifest_sha256")
    claims = sample.get("claims")
    if not isinstance(claims, list):
        errors.append("sample: claims must be a list")
        claims = []
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        label = f"claim {index + 1}"
        if not isinstance(claim, dict):
            errors.append(f"{label}: must be an object")
            continue
        errors.extend(_exact_fields(claim, CLAIM_FIELDS, label))
        claim_id = claim.get("claim_id")
        if not _sha(claim_id):
            errors.append(f"{label}: invalid claim_id")
        elif claim_id in seen:
            errors.append(f"{label}: duplicate claim_id {claim_id}")
        else:
            seen.add(claim_id)
        if not _canonical_relative(claim.get("path"), "wiki/"):
            errors.append(f"{label}: path must be canonical under wiki/")
        if not _strict_int(claim.get("line_number"), minimum=1):
            errors.append(f"{label}: line_number must be positive")
        if not isinstance(claim.get("line_text"), str):
            errors.append(f"{label}: line_text must be a string")
        if not _sha(claim.get("line_sha256")) or not _sha(claim.get("file_sha256")):
            errors.append(f"{label}: invalid content hash")
        slugs = claim.get("cited_slugs")
        if not isinstance(slugs, list) or not slugs or not all(isinstance(v, str) and SLUG_RE.fullmatch(v) for v in slugs):
            errors.append(f"{label}: cited_slugs must be a nonempty canonical slug list")
        elif len(slugs) != len(set(slugs)):
            errors.append(f"{label}: cited_slugs must not repeat")
        errors.extend(_validate_source_closure(claim.get("source_closure"), slugs, label))
        if isinstance(claim.get("line_text"), str):
            raw = claim["line_text"].encode("utf-8")
            if _sha(claim.get("line_sha256")) and evidence_sha256_bytes(raw) != claim["line_sha256"]:
                errors.append(f"{label}: line_sha256 mismatch")
            if isinstance(claim.get("path"), str) and _strict_int(claim.get("line_number"), minimum=1):
                identity = claim["path"].encode() + b"\0" + str(claim["line_number"]).encode() + b"\0" + raw
                if _sha(claim_id) and evidence_sha256_bytes(identity) != claim_id:
                    errors.append(f"{label}: claim_id mismatch")
    if _strict_int(sample.get("selected_count")) and sample["selected_count"] != len(claims):
        errors.append("sample: selected_count does not match claims")
    if _strict_int(sample.get("population_count")) and _strict_int(sample.get("selected_count")) and sample["selected_count"] > sample["population_count"]:
        errors.append("sample: selected_count exceeds population_count")
    if not _sha(sample.get("manifest_sha256")) or manifest_hash(sample) != sample.get("manifest_sha256"):
        errors.append("sample: manifest_sha256 mismatch")
    return errors


def validate_plant(plant: object, sample: dict[str, object]) -> list[str]:
    if not isinstance(plant, dict):
        return ["plant must be an object"]
    errors = _exact_fields(plant, PLANT_FIELDS, "plant")
    if plant.get("schema_version") != SCHEMA_VERSION or isinstance(plant.get("schema_version"), bool):
        errors.append("plant: schema_version must be integer 1")
    if plant.get("plant_id") != "plant-01":
        errors.append("plant: plant_id must be plant-01")
    if plant.get("invalid_verdict") != "VERIFIED":
        errors.append("plant: invalid_verdict must declare VERIFIED")
    claims = sample.get("claims")
    by_id = {
        claim.get("claim_id"): claim
        for claim in claims if isinstance(claim, dict)
    } if isinstance(claims, list) else {}
    source = by_id.get(plant.get("source_claim_id"))
    if source is None:
        errors.append("plant: source_claim_id is not in the sample")
    else:
        for plant_key, source_key in (("path", "path"), ("line_number", "line_number"), ("cited_slugs", "cited_slugs")):
            if plant.get(plant_key) != source.get(source_key):
                errors.append(f"plant: {plant_key} must match the source claim")
        if not isinstance(plant.get("text"), str) or not plant["text"].strip():
            errors.append("plant: text must be nonempty")
        elif plant["text"] == source.get("line_text"):
            errors.append("plant: text must differ from the source claim bytes")
    return errors


def validate_batch(batch: object) -> list[str]:
    if not isinstance(batch, dict):
        return ["batch must be an object"]
    errors = _exact_fields(batch, BATCH_FIELDS, "batch")
    if batch.get("schema_version") != 1 or isinstance(batch.get("schema_version"), bool):
        errors.append("batch: schema_version must be integer 1")
    if not isinstance(batch.get("run_id"), str) or not RUN_ID_RE.fullmatch(batch["run_id"]):
        errors.append("batch: invalid run_id")
    if not _sha(batch.get("manifest_sha256")):
        errors.append("batch: invalid manifest_sha256")
    if not isinstance(batch.get("batch_id"), str) or not re.fullmatch(r"batch-[0-9]{2}", batch["batch_id"]):
        errors.append("batch: invalid batch_id")
    items = batch.get("items")
    if not isinstance(items, list):
        errors.append("batch: items must be a list")
        items = []
    if not _strict_int(batch.get("item_count")) or batch.get("item_count") != len(items):
        errors.append("batch: item_count does not match items")
    for index, item in enumerate(items):
        label = f"batch item {index + 1}"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        errors.extend(_exact_fields(item, ITEM_FIELDS, label))
        if not isinstance(item.get("item_id"), str) or not re.fullmatch(r"item-[0-9]{3}", item["item_id"]):
            errors.append(f"{label}: invalid item_id")
        if item.get("kind") not in {"claim", "plant"}:
            errors.append(f"{label}: invalid kind")
        if not isinstance(item.get("source_id"), str) or not item["source_id"]:
            errors.append(f"{label}: source_id must be nonempty")
        if not _canonical_relative(item.get("path"), "wiki/"):
            errors.append(f"{label}: invalid path")
        if not _strict_int(item.get("line_number"), minimum=1):
            errors.append(f"{label}: invalid line_number")
        if not isinstance(item.get("text"), str) or not item["text"]:
            errors.append(f"{label}: text must be nonempty")
        slugs = item.get("cited_slugs")
        if not isinstance(slugs, list) or not slugs or not all(isinstance(v, str) and SLUG_RE.fullmatch(v) for v in slugs):
            errors.append(f"{label}: invalid cited_slugs")
    return errors


def validate_verdict_file(data: object) -> list[str]:
    if not isinstance(data, dict):
        return ["verdict file must be an object"]
    errors = _exact_fields(data, VERDICT_FILE_FIELDS, "verdict file")
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        errors.append("verdict file: schema_version must be integer 1")
    if not isinstance(data.get("run_id"), str) or not RUN_ID_RE.fullmatch(data["run_id"]):
        errors.append("verdict file: invalid run_id")
    if not isinstance(data.get("batch_id"), str) or not re.fullmatch(r"batch-[0-9]{2}", data["batch_id"]):
        errors.append("verdict file: invalid batch_id")
    verdicts = data.get("verdicts")
    if not isinstance(verdicts, list):
        errors.append("verdict file: verdicts must be a list")
        verdicts = []
    for index, verdict in enumerate(verdicts):
        label = f"verdict {index + 1}"
        if not isinstance(verdict, dict):
            errors.append(f"{label}: must be an object")
            continue
        errors.extend(_exact_fields(verdict, VERDICT_FIELDS, label))
        if not isinstance(verdict.get("item_id"), str) or not re.fullmatch(r"item-[0-9]{3}", verdict["item_id"]):
            errors.append(f"{label}: invalid item_id")
        if verdict.get("verdict") not in VERDICTS:
            errors.append(f"{label}: invalid verdict")
        if not isinstance(verdict.get("decisive_quote"), str) or not verdict["decisive_quote"].strip():
            errors.append(f"{label}: decisive_quote must be nonempty")
        paths = verdict.get("evidence_paths")
        if not isinstance(paths, list) or not paths or not all(_canonical_relative(path) for path in paths):
            errors.append(f"{label}: evidence_paths must be nonempty canonical relative paths")
    return errors


def safe_run_dir(repo_root: Path, value: str, *, create: bool = False) -> Path:
    if not _canonical_relative(value, "tmp/evidence-check/"):
        raise EvidenceError("run directory must be canonical under tmp/evidence-check/")
    relative = Path(value)
    if len(relative.parts) != 3 or not RUN_ID_RE.fullmatch(relative.parts[-1]):
        raise EvidenceError("run directory must be exactly tmp/evidence-check/<run-id>")
    current = repo_root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise EvidenceError(f"run directory path contains symlink: {current}")
        if current != repo_root / relative and not stat.S_ISDIR(mode):
            raise EvidenceError(f"run directory parent is not a directory: {current}")
        if current == repo_root / relative and not stat.S_ISDIR(mode):
            raise EvidenceError(f"run directory exists and is not a directory: {current}")
    target = repo_root / relative
    if create:
        target.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or not target.is_dir():
            raise EvidenceError("unsafe run directory")
    elif not target.is_dir():
        raise EvidenceError(f"run directory does not exist: {relative.as_posix()}")
    return target


def _git_metadata(repo_root: Path) -> dict[str, object]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=10
        )
        status_result = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return {"head": None, "dirty": None}
    return {
        "head": head.stdout.strip() if head.returncode == 0 and _sha(head.stdout.strip()) else None,
        "dirty": bool(status_result.stdout) if status_result.returncode == 0 else None,
    }


def build_sample_data(
    repo_root: Path,
    run_id: str,
    requested_count: int = 25,
    *,
    injected_seed: int | None = None,
    included_paths: Sequence[str] | None = None,
) -> dict[str, object]:
    if not RUN_ID_RE.fullmatch(run_id):
        raise EvidenceError("invalid run_id")
    if not _strict_int(requested_count, minimum=1):
        raise EvidenceError("requested_count must be positive")
    selected_paths: set[str] | None = None
    if included_paths is not None:
        if not included_paths:
            raise EvidenceError("included_paths must not be empty")
        if len(included_paths) != len(set(included_paths)):
            raise EvidenceError("included_paths must not contain duplicates")
        for value in included_paths:
            if not _canonical_relative(value, "wiki/") or Path(value).suffix != ".md":
                raise EvidenceError(f"invalid included path: {value!r}")
        selected_paths = set(included_paths)
    wiki_root = repo_root / "wiki"
    candidates: list[dict[str, object]] = []
    visited_paths: set[str] = set()
    closure_cache: dict[str, dict[str, object]] = {}
    for page in get_entity_pages(wiki_root):
        if page.parent.name == "sources":
            continue
        relative = page.relative_to(repo_root).as_posix()
        if selected_paths is not None and relative not in selected_paths:
            continue
        visited_paths.add(relative)
        try:
            mode = page.lstat().st_mode
        except OSError as exc:
            raise EvidenceError(f"cannot inspect {page}: {exc}") from exc
        if not stat.S_ISREG(mode):
            continue
        try:
            content = page.read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise EvidenceError(f"cannot read {page} as UTF-8: {exc}") from exc
        for line_number, line, visible_line in evidentiary_line_views(text):
            slugs = list(dict.fromkeys(CITATION_RE.findall(visible_line)))
            if not slugs:
                continue
            for slug in slugs:
                if slug not in closure_cache:
                    try:
                        closure_cache[slug] = _closure_payload(
                            resolve_live_source_closure(repo_root, slug)
                        )
                    except ValueError as exc:
                        raise EvidenceError(
                            f"claim source closure failed for {relative}:{line_number}: {exc}"
                        ) from exc
            line_bytes = line.encode("utf-8")
            identity = relative.encode() + b"\0" + str(line_number).encode() + b"\0" + line_bytes
            candidates.append(
                {
                    "claim_id": evidence_sha256_bytes(identity),
                    "path": relative,
                    "line_number": line_number,
                    "line_text": line,
                    "line_sha256": evidence_sha256_bytes(line_bytes),
                    "file_sha256": evidence_sha256_bytes(content),
                    "cited_slugs": slugs,
                    "source_closure": [closure_cache[slug] for slug in slugs],
                }
            )
    candidates.sort(key=lambda claim: (claim["path"], claim["line_number"], claim["claim_id"]))
    if selected_paths is not None:
        missing_paths = selected_paths - visited_paths
        if missing_paths:
            raise EvidenceError(
                "included paths are not non-source entity pages: "
                + ", ".join(sorted(missing_paths))
            )
        if not candidates:
            raise EvidenceError("included paths contain no citation-bearing claims")
        requested_count = len(candidates)
    seed = secrets.randbits(64) if injected_seed is None else injected_seed
    rng = random.Random(seed)
    selected = (
        list(candidates)
        if selected_paths is not None
        else rng.sample(candidates, min(requested_count, len(candidates)))
    )
    sample = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": utc_now(),
        "seed": seed,
        "requested_count": requested_count,
        "population_count": len(candidates),
        "selected_count": len(selected),
        "git": _git_metadata(repo_root),
        "claims": selected,
        "raw_manifest_sha256": evidence_sha256_bytes(
            (repo_root / "scripts/raw-artifacts.json").read_bytes()
        ),
        "manifest_sha256": "",
    }
    sample["manifest_sha256"] = manifest_hash(sample)
    errors = validate_sample(sample)
    if errors:
        raise EvidenceError("invalid generated sample: " + "; ".join(errors))
    return sample


def batch_items(sample: dict[str, object], plant: dict[str, object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for index, claim in enumerate(sample["claims"], start=1):
        items.append(
            {
                "item_id": f"item-{index:03d}",
                "kind": "claim",
                "source_id": claim["claim_id"],
                "path": claim["path"],
                "line_number": claim["line_number"],
                "text": claim["line_text"],
                "cited_slugs": claim["cited_slugs"],
            }
        )
    items.append(
        {
            "item_id": f"item-{len(items) + 1:03d}",
            "kind": "plant",
            "source_id": plant["plant_id"],
            "path": plant["path"],
            "line_number": plant["line_number"],
            "text": plant["text"],
            "cited_slugs": plant["cited_slugs"],
        }
    )
    return items


def build_batches(sample: dict[str, object], plant: dict[str, object], count: int) -> list[dict[str, object]]:
    if count not in {2, 3}:
        raise EvidenceError("batch count must be 2 or 3")
    sample_errors = validate_sample(sample)
    plant_errors = validate_plant(plant, sample)
    if sample_errors or plant_errors:
        raise EvidenceError("; ".join(sample_errors + plant_errors))
    items = batch_items(sample, plant)
    if len(items) < count:
        raise EvidenceError("not enough items for the requested batch count")
    buckets = [[] for _ in range(count)]
    for index, item in enumerate(items):
        buckets[index % count].append(item)
    batches: list[dict[str, object]] = []
    for index, assigned in enumerate(buckets, start=1):
        batch = {
            "schema_version": 1,
            "run_id": sample["run_id"],
            "manifest_sha256": sample["manifest_sha256"],
            "batch_id": f"batch-{index:02d}",
            "item_count": len(assigned),
            "items": assigned,
        }
        errors = validate_batch(batch)
        if errors:
            raise EvidenceError("invalid generated batch: " + "; ".join(errors))
        batches.append(batch)
    return batches


def render_prompt(batch: dict[str, object]) -> str:
    public_items = [
        {
            "item_id": item["item_id"],
            "path": item["path"],
            "line_number": item["line_number"],
            "text": item["text"],
            "cited_slugs": item["cited_slugs"],
        }
        for item in batch["items"]
    ]
    verdict_schema = {
        "schema_version": 1,
        "run_id": batch["run_id"],
        "batch_id": batch["batch_id"],
        "verdicts": [
            {
                "item_id": "exact assigned item ID",
                "verdict": "VERIFIED | OVEREXTENDED | CONFLATED | MISMATCH | NOT-FOUND",
                "decisive_quote": "quoted source text that decides the verdict",
                "evidence_paths": ["canonical/repo-relative/path"],
            }
        ],
    }
    return (
        "Try to refute each assigned claim against its cited wiki page and raw evidence where present. "
        "Judge only the assigned item IDs. Return strict JSON to the corresponding verdict file, with "
        "exactly one verdict per item. Do not add fields.\n\nAssigned items:\n"
        + json.dumps(public_items, sort_keys=True, indent=2, ensure_ascii=False)
        + "\n\nRequired output shape:\n"
        + json.dumps(verdict_schema, sort_keys=True, indent=2, ensure_ascii=False)
        + "\n"
    )


def counter_differences(expected: Counter, actual: Counter, label: str) -> list[str]:
    errors: list[str] = []
    missing = expected - actual
    excess = actual - expected
    if missing:
        errors.append(f"{label}: missing {dict(missing)}")
    if excess:
        errors.append(f"{label}: duplicated or excess {dict(excess)}")
    return errors


__all__ = [
    "EvidenceError",
    "VERDICTS",
    "atomic_json",
    "build_batches",
    "build_sample_data",
    "canonical_json",
    "counter_differences",
    "evidence_sha256_bytes",
    "load_json",
    "render_prompt",
    "safe_run_dir",
    "validate_batch",
    "validate_plant",
    "validate_sample",
    "validate_verdict_file",
]
