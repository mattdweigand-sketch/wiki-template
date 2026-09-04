#!/usr/bin/env python3
"""Create or render an answer bound to a current reviewed evidence run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from _durable_files import atomic_replace_bytes, read_regular_bytes, stable_lock
from _repo_paths import RepoPathError, resolve_repo_path

from _evidence_fidelity import canonical_json, load_json, safe_run_dir
from _strict_json import reject_duplicate_json_keys
from _wiki_parse import split_frontmatter
from wiki_evidence import EvidenceRunError, validate_evidence_run


REPO_ROOT = Path(__file__).resolve().parents[1]
DRAFT_FIELDS = {"schema_version", "run_id", "manifest_sha256", "statements"}
STATEMENT_FIELDS = {"claim_id"}
RESPONSE_FIELDS = {
    "schema_version", "run_id", "manifest_sha256", "draft_sha256",
    "review_sha256", "statements",
}
RESPONSE_STATEMENT_FIELDS = {"claim_id", "text", "citations"}


class EvidenceResponseError(ValueError):
    """The response draft is not bound to current verified evidence."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_json_bytes(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        content, _ = read_regular_bytes(path)
        assert content is not None
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=reject_duplicate_json_keys
        )
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise EvidenceResponseError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceResponseError(f"{path.name} must contain one JSON object")
    return value, content


def _review_identity_and_verified_claims(run_dir: Path) -> tuple[str, set[str]]:
    batch_dir = run_dir / "batches"
    verdict_dir = run_dir / "verdicts"
    item_to_claim: dict[str, str] = {}
    for batch_path in sorted(batch_dir.glob("batch-*.json")):
        batch = load_json(batch_path)
        for item in batch.get("items", []):
            if (
                isinstance(item, dict)
                and item.get("kind") == "claim"
                and isinstance(item.get("item_id"), str)
                and isinstance(item.get("source_id"), str)
            ):
                item_to_claim[item["item_id"]] = item["source_id"]

    verified: set[str] = set()
    review_projection: list[dict[str, object]] = []
    for verdict_path in sorted(verdict_dir.glob("batch-*.json")):
        verdict_bytes = verdict_path.read_bytes()
        verdict = load_json(verdict_path)
        review_projection.append({
            "path": verdict_path.name,
            "sha256": _sha256_bytes(verdict_bytes),
        })
        for item in verdict.get("verdicts", []):
            if not isinstance(item, dict) or item.get("verdict") != "VERIFIED":
                continue
            item_id = item.get("item_id")
            if isinstance(item_id, str) and item_id in item_to_claim:
                verified.add(item_to_claim[item_id])
    return _sha256_bytes(canonical_json(review_projection)), verified


def _authority_ref(repo_root: Path, source_slug: str) -> str | None:
    """Add only supported authority links; the captured source remains the citation."""
    source_path = repo_root / f"wiki/sources/{source_slug}.md"
    fields, _ = split_frontmatter(source_path.read_text(encoding="utf-8"))
    value = (fields or {}).get("authority_ref", "").strip().strip("\"'")
    if not value or any(char.isspace() or char in '<>"' for char in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme in {"http", "https"} and url.hostname and not url.username:
            return value
    except ValueError:
        return None
    try:
        relative = resolve_repo_path(
            value, repo_root=repo_root,
            allowed_prefixes=(value.split("/")[0],) if "/" in value else (),
            allowed_root_files=(value,) if "/" not in value else (),
        )
    except RepoPathError:
        return None
    return (repo_root / relative).as_posix()


def build_reviewed_evidence_response(
    repo_root: Path,
    run_directory: str,
) -> dict[str, object]:
    """Build the exact response packet without writing it."""
    root = repo_root.resolve()
    run_dir = safe_run_dir(root, run_directory, create=False)
    validation = validate_evidence_run(root, Path(run_directory))
    if validation.structure != "VALID" or validation.snapshot != "CURRENT":
        raise EvidenceResponseError(
            f"evidence run is not current and structurally valid: {validation.status}"
        )
    sample = load_json(run_dir / "sample.json")
    draft, draft_bytes = _strict_json_bytes(run_dir / "response-draft.json")
    if set(draft) != DRAFT_FIELDS or type(draft.get("schema_version")) is not int or draft.get("schema_version") != 1:
        raise EvidenceResponseError("response-draft.json fields differ from schema version 1")
    if draft.get("run_id") != sample.get("run_id"):
        raise EvidenceResponseError("response draft run_id differs from the sample")
    if draft.get("manifest_sha256") != sample.get("manifest_sha256"):
        raise EvidenceResponseError("response draft manifest hash differs from the sample")

    claims = sample.get("claims")
    if not isinstance(claims, list):
        raise EvidenceResponseError("sample claims are invalid")
    claims_by_id = {
        claim.get("claim_id"): claim
        for claim in claims
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    review_sha256, verified_claims = _review_identity_and_verified_claims(run_dir)
    raw_statements = draft.get("statements")
    if not isinstance(raw_statements, list) or not raw_statements:
        raise EvidenceResponseError("response draft statements must be a nonempty list")
    response_statements: list[dict[str, object]] = []
    seen_claims: set[str] = set()
    for index, statement in enumerate(raw_statements):
        if not isinstance(statement, dict) or set(statement) != STATEMENT_FIELDS:
            raise EvidenceResponseError(f"statements[{index}] has invalid fields")
        claim_id = statement.get("claim_id")
        if not isinstance(claim_id, str) or claim_id not in claims_by_id:
            raise EvidenceResponseError(f"statements[{index}] names an unknown claim")
        if claim_id in seen_claims:
            raise EvidenceResponseError(f"statements[{index}] repeats a claim")
        if claim_id not in verified_claims:
            raise EvidenceResponseError(f"statements[{index}] claim is not VERIFIED")
        claim = claims_by_id[claim_id]
        # The model selects reviewed claims; it cannot author replacement text.
        text = claim["line_text"].strip()
        cited_slugs = claim.get("cited_slugs")
        if not isinstance(cited_slugs, list) or not cited_slugs:
            raise EvidenceResponseError(f"statements[{index}] claim has no citations")
        citations = [
            {"source_slug": slug, "source_path": f"wiki/sources/{slug}.md",
             "authority_ref": _authority_ref(root, slug)}
            for slug in cited_slugs
            if isinstance(slug, str)
        ]
        if len(citations) != len(cited_slugs):
            raise EvidenceResponseError(f"statements[{index}] citations are invalid")
        response_statements.append({
            "claim_id": claim_id,
            "text": text,
            "citations": citations,
        })
        seen_claims.add(claim_id)
    return {
        "schema_version": 1,
        "run_id": draft["run_id"],
        "manifest_sha256": draft["manifest_sha256"],
        "draft_sha256": _sha256_bytes(draft_bytes),
        "review_sha256": review_sha256,
        "statements": response_statements,
    }


def create_reviewed_evidence_response(repo_root: Path, run_directory: str) -> Path:
    """Write response.json once after binding the draft to current reviews."""
    root = repo_root.resolve()
    run_dir = safe_run_dir(root, run_directory, create=False)
    response_path = run_dir / "response.json"
    if response_path.exists() or response_path.is_symlink():
        raise EvidenceResponseError("response.json already exists; use a fresh run")
    packet = build_reviewed_evidence_response(root, run_directory)
    with stable_lock(run_dir / ".response.lock"):
        atomic_replace_bytes(response_path, canonical_json(packet) + b"\n",
                             expected_sha256=None)
    return response_path


def render_reviewed_evidence_response(repo_root: Path, run_directory: str) -> str:
    """Render response.json only while its draft, review, and source snapshot match."""
    root = repo_root.resolve()
    run_dir = safe_run_dir(root, run_directory, create=False)
    response, response_bytes = _strict_json_bytes(run_dir / "response.json")
    expected = build_reviewed_evidence_response(root, run_directory)
    if (response != expected or set(response) != RESPONSE_FIELDS
            or response_bytes != canonical_json(expected) + b"\n"):
        raise EvidenceResponseError("response.json is stale or differs from the reviewed packet")
    rendered: list[str] = []
    for index, statement in enumerate(response["statements"]):
        if not isinstance(statement, dict) or set(statement) != RESPONSE_STATEMENT_FIELDS:
            raise EvidenceResponseError(f"response statements[{index}] is invalid")
        links = {
            citation["source_slug"]:
            f"[{citation['source_slug']}](<{root / citation['source_path']}>)"
            + (f" [authority](<{citation['authority_ref']}>)" if citation['authority_ref'] else "")
            for citation in statement["citations"]
        }
        rendered.append(re.sub(r"\(source:\s*\[\[([^\]]+)\]\]\)",
                               lambda match: links[match[1]], statement["text"]))
    return "\n\n".join(rendered) + "\n"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("action", choices=("create", "render"))
    command.add_argument("--run-dir", required=True)
    command.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        if args.action == "create":
            path = create_reviewed_evidence_response(args.repo_root, args.run_dir)
            print(path.relative_to(args.repo_root.resolve()))
        else:
            sys.stdout.write(render_reviewed_evidence_response(args.repo_root, args.run_dir))
        return 0
    except (EvidenceRunError, EvidenceResponseError, OSError, ValueError) as exc:
        print(f"evidence_response.py: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "EvidenceResponseError",
    "build_reviewed_evidence_response",
    "create_reviewed_evidence_response",
    "render_reviewed_evidence_response",
]


if __name__ == "__main__":
    raise SystemExit(main())
