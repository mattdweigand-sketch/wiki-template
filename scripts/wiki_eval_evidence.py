#!/usr/bin/env python3
"""Regression suite for exact evidence sample, batch, verdict, and snapshot fidelity."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
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
    EvidenceResponseStatement,
    create_evidence_response_packet,
    create_evidence_sample,
    publish_evidence_batches,
    render_verified_evidence_response,
    validate_evidence_run,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "scripts/fixtures/wiki-evidence"
RESPONSE_CLI = REPO_ROOT / "scripts/evidence_response.py"
results = Results()


def install_evidence_fixture(root: Path) -> None:
    wiki = root / "wiki/concepts"
    wiki.mkdir(parents=True)
    (root / "wiki/sources").mkdir()
    (root / "raw/evidence").mkdir(parents=True)
    (root / "scripts").mkdir()
    for source in FIXTURES.glob("*.md"):
        shutil.copyfile(source, wiki / source.name)
    artifacts = []
    for slug in ("alpha-source", "beta-source", "shared-source"):
        raw_path = f"raw/evidence/{slug}.txt"
        raw_bytes = f"Evidence for {slug}.\n".encode()
        (root / raw_path).write_bytes(raw_bytes)
        (root / f"wiki/sources/{slug}.md").write_text(
            f"---\ntitle: {slug}\ntype: source\nsources: [\"{raw_path}\"]\n---\n\n{slug}.\n",
            encoding="utf-8",
        )
        artifacts.append({
            "captured_at": "2026-08-22",
            "files": [{
                "path": raw_path,
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "size": len(raw_bytes),
            }],
            "source_slug": slug,
        })
    (root / "scripts/raw-buckets.json").write_text(
        json.dumps({
            "description": "fixture", "policy": "fixture",
            "buckets": {"evidence": "fixture evidence"},
        }, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (root / "scripts/raw-artifacts.json").write_text(
        json.dumps({"artifacts": artifacts, "schema_version": 1},
                   sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Wiki Eval"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "evidence fixture"], cwd=root, check=True)


def make_repo(root: Path, run_id: str = "fixture-run") -> tuple[Path, dict, dict, list[dict]]:
    install_evidence_fixture(root)
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
        root = Path(td).resolve()
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


with tempfile.TemporaryDirectory(prefix="wiki-evidence-missing-count-") as td:
    root = Path(td).resolve()
    run_dir, _sample, _plant, batches = make_repo(root, "missing-count")
    real_item = next(
        item for batch in batches for item in batch["items"] if item["kind"] == "claim"
    )
    for verdict_path in sorted((run_dir / "verdicts").glob("*.json")):
        verdict_file = load_json(verdict_path)
        original_count = len(verdict_file["verdicts"])
        verdict_file["verdicts"] = [
            verdict for verdict in verdict_file["verdicts"]
            if verdict["item_id"] != real_item["item_id"]
        ]
        if len(verdict_file["verdicts"]) != original_count:
            atomic_json(verdict_path, verdict_file)
            break
    result = validate_evidence_run(root, run_dir.relative_to(root))
    cli = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts/verify_evidence_run.py"),
            "--repo-root", str(root), "--run-dir", str(run_dir.relative_to(root)),
        ],
        cwd=root, text=True, capture_output=True,
    )
    results.record(
        "incomplete-run-reports-nonzero-missing-count",
        result.structure == "INVALID"
        and result.metrics is not None
        and result.metrics.missing == 1
        and "missing=1" in cli.stdout,
        f"result={result} cli={cli.stdout + cli.stderr}",
    )


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


def malformed_claims(_root, run_dir, _sample, _plant, _batches):
    sample = load_json(run_dir / "sample.json")
    sample["claims"] = 7
    sample["manifest_sha256"] = manifest_hash(sample)
    atomic_json(run_dir / "sample.json", sample)


case("malformed-sample-claims-fails-without-crash", malformed_claims, fragment="claims must be a list")


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
    root = Path(td).resolve()
    install_evidence_fixture(root)
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
    root = Path(td).resolve()
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
    root = Path(td).resolve()
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
    root = Path(td).resolve()
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


with tempfile.TemporaryDirectory(prefix="wiki-evidence-population-") as td:
    root = Path(td).resolve()
    (root / "wiki/concepts").mkdir(parents=True)
    (root / "wiki/sources").mkdir()
    (root / "raw/notes").mkdir(parents=True)
    (root / "scripts").mkdir()
    raw_bytes = b"Exact supporting source bytes.\n"
    (root / "raw/notes/source.txt").write_bytes(raw_bytes)
    (root / "wiki/sources/source-one.md").write_text(
        "---\ntitle: Source one\ntype: source\n"
        "sources: [\"raw/notes/source.txt\"]\n---\n\n"
        "Source-page claims are excluded. (source: [[source-one]])\n",
        encoding="utf-8",
    )
    (root / "wiki/concepts/claim-page.md").write_text(
        "---\ntitle: Claim page\ntype: concept\n---\n\n"
        "The supported statement is exact. (source: [[source-one]])\n\n"
        "```\nFenced text is excluded. (source: [[source-one]])\n```\n\n"
        "<!-- Commented text is excluded. (source: [[source-one]]) -->\n\n"
        "## Related pages\n\n"
        "Related-page evidence remains authored. (source: [[source-one]])\n\n"
        "## Referenced by\n\n- Generated claim. (source: [[source-one]])\n",
        encoding="utf-8",
    )
    (root / "wiki/SCHEMA.md").write_text(
        "Schema example is excluded. (source: [[source-one]])\n",
        encoding="utf-8",
    )
    (root / "scripts/raw-buckets.json").write_text(
        json.dumps({"description": "fixture", "policy": "fixture", "buckets": {"notes": "fixture"}},
                   sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (root / "scripts/raw-artifacts.json").write_text(
        json.dumps({
            "artifacts": [{
                "captured_at": "2026-08-22",
                "files": [{
                    "path": "raw/notes/source.txt",
                    "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                    "size": len(raw_bytes),
                }],
                "source_slug": "source-one",
            }],
            "schema_version": 1,
        }, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Wiki Eval"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "evidence fixture"], cwd=root, check=True)
    population = build_sample_data(root, "population", 25, injected_seed=7)
    claims = population["claims"]
    results.record(
        "population-is-only-cited-nonsource-entity-lines",
        population["population_count"] == 2
        and len(claims) == 2
        and {claim["path"] for claim in claims} == {"wiki/concepts/claim-page.md"}
        and all(claim.get("source_closure") == [{
            "source_slug": "source-one",
            "source_path": "wiki/sources/source-one.md",
            "source_sha256": hashlib.sha256(
                (root / "wiki/sources/source-one.md").read_bytes()
            ).hexdigest(),
            "files": [{
                "path": "raw/notes/source.txt",
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "size": len(raw_bytes),
            }],
        }] for claim in claims),
        f"claims={claims}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-evidence-raw-stale-") as td:
    root = Path(td).resolve()
    run_dir, sample, _plant, _batches = make_repo(root, "raw-stale")
    raw_path = sample["claims"][0]["source_closure"][0]["files"][0]["path"]
    (root / raw_path).write_bytes(b"changed raw evidence\n")
    result = validate_evidence_run(root, run_dir.relative_to(root))
    results.record(
        "changed-raw-closure-makes-snapshot-stale",
        result.structure == "VALID"
        and result.snapshot == "STALE"
        and result.status == "STALE SNAPSHOT",
        f"result={result}",
    )


with tempfile.TemporaryDirectory(prefix="wiki-evidence-flagged-") as td:
    root = Path(td).resolve()
    run_dir, sample, _plant, batches = make_repo(root, "flagged-real")
    real_item = next(
        item for batch in batches for item in batch["items"] if item["kind"] == "claim"
    )
    for verdict_path in sorted((run_dir / "verdicts").glob("*.json")):
        verdict_file = load_json(verdict_path)
        for verdict in verdict_file["verdicts"]:
            if verdict["item_id"] == real_item["item_id"]:
                verdict["verdict"] = "OVEREXTENDED"
        atomic_json(verdict_path, verdict_file)
    result = validate_evidence_run(root, run_dir.relative_to(root))
    results.record(
        "adverse-real-verdict-is-valid-but-flagged",
        result.structure == "VALID"
        and result.snapshot == "CURRENT"
        and result.review == "FLAGGED"
        and result.flagged_ids == (real_item["source_id"],),
        f"result={result}",
    )
    results.record(
        "caught-plant-cannot-hide-flagged-real-claim",
        result.metrics is not None
        and result.metrics.plant_verdict == "OVEREXTENDED"
        and result.metrics.flagged == 1
        and result.review == "FLAGGED",
        f"result={result}",
    )
    response_path = create_evidence_response_packet(
        root,
        run_dir.relative_to(root),
        "Can the flagged claim be returned?",
        (EvidenceResponseStatement(
            text="This must be withheld because its source claim is flagged.",
            claim_ids=(real_item["source_id"],),
        ),),
    )
    response_packet = load_json(response_path)
    atomic_json(run_dir / "response-review.json", {
        "schema_version": 1,
        "evidence_snapshot_sha256": sample["manifest_sha256"],
        "statements": [{
            "statement_id": "statement-001",
            "statement_sha256": response_packet["statements"][0]["statement_sha256"],
            "verdict": "VERIFIED",
        }],
    })
    flagged_render = render_verified_evidence_response(root, run_dir.relative_to(root))
    results.record(
        "verified-response-is-withheld-when-origin-claim-is-flagged",
        "This must be withheld" not in flagged_render
        and "Withheld 1 statement" in flagged_render,
        flagged_render,
    )


with tempfile.TemporaryDirectory(prefix="wiki-evidence-response-") as td:
    root = Path(td).resolve()
    run_dir, sample, _plant, _batches = make_repo(root, "response")
    claim = sample["claims"][0]
    statement = EvidenceResponseStatement(
        text="The response statement is supported.",
        claim_ids=(claim["claim_id"],),
    )
    response_path = create_evidence_response_packet(
        root, run_dir.relative_to(root), "What is supported?", (statement,),
    )
    packet = load_json(response_path)
    review = {
        "schema_version": 1,
        "evidence_snapshot_sha256": packet["evidence_snapshot_sha256"],
        "statements": [{
            "statement_id": "statement-001",
            "statement_sha256": packet["statements"][0]["statement_sha256"],
            "verdict": "VERIFIED",
        }],
    }
    atomic_json(run_dir / "response-review.json", review)
    rendered = render_verified_evidence_response(root, run_dir.relative_to(root))
    expected_page = Path(claim["path"]).stem
    expected_source = claim["cited_slugs"][0]
    results.record(
        "reviewed-response-renders-adjacent-citations",
        statement.text in rendered
        and f"(wiki: [[{expected_page}]])" in rendered
        and f"(source: [[{expected_source}]])" in rendered,
        rendered,
    )
    bad_question_packet = load_json(response_path)
    bad_question_packet["question_sha256"] = 7
    atomic_json(response_path, bad_question_packet)
    try:
        render_verified_evidence_response(root, run_dir.relative_to(root))
    except EvidenceError:
        bad_question_rejected = True
    else:
        bad_question_rejected = False
    results.record(
        "malformed-response-question-digest-fails",
        bad_question_rejected,
        "malformed question digest rendered" if not bad_question_rejected else "",
    )
    atomic_json(response_path, packet)
    review["statements"][0]["verdict"] = "MISMATCH"
    atomic_json(run_dir / "response-review.json", review)
    withheld = render_verified_evidence_response(root, run_dir.relative_to(root))
    results.record(
        "flagged-response-is-withheld-with-limitation",
        statement.text not in withheld and "Withheld 1 statement" in withheld,
        withheld,
    )
    review["statements"][0]["verdict"] = "VERIFIED"
    atomic_json(run_dir / "response-review.json", review)
    changed_packet = load_json(response_path)
    changed_packet["statements"][0]["text"] = "Changed after review."
    atomic_json(response_path, changed_packet)
    try:
        render_verified_evidence_response(root, run_dir.relative_to(root))
    except EvidenceError:
        changed_rejected = True
    else:
        changed_rejected = False
    results.record(
        "changed-response-text-requires-new-review", changed_rejected,
        "changed response rendered" if not changed_rejected else "",
    )
    atomic_json(response_path, packet)
    raw_path = claim["source_closure"][0]["files"][0]["path"]
    (root / raw_path).write_bytes(b"stale after response review\n")
    try:
        render_verified_evidence_response(root, run_dir.relative_to(root))
    except EvidenceError:
        stale_rejected = True
    else:
        stale_rejected = False
    results.record(
        "stale-evidence-cannot-render-verified-response", stale_rejected,
        "stale response rendered" if not stale_rejected else "",
    )


with tempfile.TemporaryDirectory(prefix="wiki-evidence-response-cli-") as td:
    root = Path(td).resolve()
    run_dir, sample, _plant, _batches = make_repo(root, "response-cli")
    claim = sample["claims"][0]
    atomic_json(run_dir / "response-draft.json", {
        "question": "What does the evidence support?",
        "statements": [{
            "text": "The CLI response is supported.",
            "claim_ids": [claim["claim_id"]],
        }],
    })
    create_proc = subprocess.run(
        [
            sys.executable, str(RESPONSE_CLI), "create",
            "--repo-root", str(root),
            "--run-dir", str(run_dir.relative_to(root)),
        ],
        cwd=root, text=True, capture_output=True, check=False,
    )
    response_path = run_dir / "response.json"
    results.record(
        "response-cli-creates-exact-packet",
        create_proc.returncode == 0 and response_path.is_file(),
        create_proc.stdout + create_proc.stderr,
    )
    if response_path.is_file():
        packet = load_json(response_path)
        atomic_json(run_dir / "response-review.json", {
            "schema_version": 1,
            "evidence_snapshot_sha256": packet["evidence_snapshot_sha256"],
            "statements": [{
                "statement_id": "statement-001",
                "statement_sha256": packet["statements"][0]["statement_sha256"],
                "verdict": "VERIFIED",
            }],
        })
        render_proc = subprocess.run(
            [
                sys.executable, str(RESPONSE_CLI), "render",
                "--repo-root", str(root),
                "--run-dir", str(run_dir.relative_to(root)),
            ],
            cwd=root, text=True, capture_output=True, check=False,
        )
        rendered = render_proc.stdout
    else:
        render_proc = None
        rendered = ""
    results.record(
        "response-cli-renders-only-reviewed-output",
        render_proc is not None
        and render_proc.returncode == 0
        and "The CLI response is supported." in rendered
        and f"(source: [[{claim['cited_slugs'][0]}]])" in rendered,
        rendered + (render_proc.stderr if render_proc is not None else "response missing"),
    )

sys.exit(results.finish())
