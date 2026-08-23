#!/usr/bin/env python3
"""Public-behavior evals for raw artifact provenance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from wiki_provenance import (
    validate_ci_provenance,
    validate_live_provenance,
    validate_staged_provenance,
)


results: list[tuple[str, bool]] = []


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments], cwd=root, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _source_page(raw_path: str) -> str:
    return (
        "---\n"
        "title: Fixture source\n"
        "type: source\n"
        "sources: [\"" + raw_path + "\"]\n"
        "---\n\nFixture source.\n"
    )


def _initialize_repository(root: Path, *, manifest: bool = True) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "eval@example.invalid")
    _git(root, "config", "user.name", "Wiki Eval")
    (root / "scripts").mkdir()
    (root / "wiki/sources").mkdir(parents=True)
    (root / "raw/fixtures").mkdir(parents=True)
    _write_json(root / "scripts/raw-buckets.json", {
        "description": "fixture",
        "policy": "fixture",
        "buckets": {"fixtures": "fixture sources"},
    })
    (root / "wiki/domain.md").write_text("---\nstatus: configured\n---\n")
    if manifest:
        _write_json(root / "scripts/raw-artifacts.json", {
            "artifacts": [], "schema_version": 1,
        })


def _commit_all(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(root, "commit", "-qm", message)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _install_artifact(root: Path, content: bytes = b"source bytes\n") -> None:
    raw_path = "raw/fixtures/source.txt"
    (root / raw_path).write_bytes(content)
    (root / "wiki/sources/fixture-source.md").write_text(_source_page(raw_path))
    _write_json(root / "scripts/raw-artifacts.json", {
        "artifacts": [{
            "captured_at": "2026-08-22",
            "files": [{
                "path": raw_path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }],
            "source_slug": "fixture-source",
        }],
        "schema_version": 1,
    })


def _record(name: str, passed: bool) -> None:
    results.append((name, passed))
    print(("PASS " if passed else "FAIL ") + name)


with tempfile.TemporaryDirectory(prefix="wiki-provenance-live-") as directory:
    repository = Path(directory)
    _initialize_repository(repository)
    _install_artifact(repository)
    _commit_all(repository, "accepted fixture")
    _record("valid-live-closure-passes", validate_live_provenance(repository) == ())


with tempfile.TemporaryDirectory(prefix="wiki-provenance-mutation-") as directory:
    repository = Path(directory)
    _initialize_repository(repository)
    _install_artifact(repository)
    _commit_all(repository, "accepted fixture")
    (repository / "raw/fixtures/source.txt").write_bytes(b"changed bytes\n")
    _record("raw-byte-mutation-fails", bool(validate_live_provenance(repository)))


with tempfile.TemporaryDirectory(prefix="wiki-provenance-coordinated-") as directory:
    repository = Path(directory)
    _initialize_repository(repository)
    _install_artifact(repository)
    _commit_all(repository, "accepted fixture")
    changed = b"coordinated change\n"
    (repository / "raw/fixtures/source.txt").write_bytes(changed)
    manifest = json.loads((repository / "scripts/raw-artifacts.json").read_text())
    manifest["artifacts"][0]["files"][0]["size"] = len(changed)
    manifest["artifacts"][0]["files"][0]["sha256"] = hashlib.sha256(changed).hexdigest()
    _write_json(repository / "scripts/raw-artifacts.json", manifest)
    issues = validate_live_provenance(repository)
    _record(
        "coordinated-mutation-still-fails-against-head",
        any("changed or rebound" in issue for issue in issues),
    )


with tempfile.TemporaryDirectory(prefix="wiki-provenance-delete-") as directory:
    repository = Path(directory)
    _initialize_repository(repository)
    _install_artifact(repository)
    _commit_all(repository, "accepted fixture")
    _write_json(repository / "scripts/raw-artifacts.json", {
        "artifacts": [], "schema_version": 1,
    })
    issues = validate_live_provenance(repository)
    _record(
        "accepted-deletion-fails",
        any("accepted raw artifact was deleted" in issue for issue in issues),
    )


with tempfile.TemporaryDirectory(prefix="wiki-provenance-staged-") as directory:
    repository = Path(directory)
    _initialize_repository(repository, manifest=False)
    _commit_all(repository, "pre-manifest baseline")
    _install_artifact(repository)
    _git(repository, "add", "scripts/raw-artifacts.json", "wiki/sources/fixture-source.md", "raw/fixtures/source.txt")
    (repository / "raw/fixtures/source.txt").write_bytes(b"unstaged worktree bytes\n")
    (repository / "wiki/sources/fixture-source.md").write_text("unstaged worktree page\n")
    _record(
        "complete-staged-record-uses-only-index-bytes",
        validate_staged_provenance(repository) == (),
    )


def _partial_case(root: Path) -> None:
    _install_artifact(root)
    (root / "raw/fixtures/source.txt").unlink()


def _duplicate_case(root: Path) -> None:
    _install_artifact(root)
    manifest = json.loads((root / "scripts/raw-artifacts.json").read_text())
    duplicate = json.loads(json.dumps(manifest["artifacts"][0]))
    duplicate["source_slug"] = "second-source"
    manifest["artifacts"].append(duplicate)
    (root / "wiki/sources/second-source.md").write_text(_source_page("raw/fixtures/source.txt"))
    _write_json(root / "scripts/raw-artifacts.json", manifest)


def _unsafe_case(root: Path) -> None:
    _install_artifact(root)
    manifest = json.loads((root / "scripts/raw-artifacts.json").read_text())
    manifest["artifacts"][0]["files"][0]["path"] = "raw/fixtures/../escape.txt"
    _write_json(root / "scripts/raw-artifacts.json", manifest)


def _mismatch_case(root: Path) -> None:
    _install_artifact(root)
    manifest = json.loads((root / "scripts/raw-artifacts.json").read_text())
    manifest["artifacts"][0]["files"][0]["sha256"] = "0" * 64
    _write_json(root / "scripts/raw-artifacts.json", manifest)


def _backslash_case(root: Path) -> None:
    _install_artifact(root)
    manifest = json.loads((root / "scripts/raw-artifacts.json").read_text())
    manifest["artifacts"][0]["files"][0]["path"] = "raw/fixtures/name\\with-backslash.txt"
    _write_json(root / "scripts/raw-artifacts.json", manifest)


for case_name, mutate in (
    ("partial-record-fails", _partial_case),
    ("duplicate-record-fails", _duplicate_case),
    ("unsafe-record-fails", _unsafe_case),
    ("backslash-path-fails", _backslash_case),
    ("mismatched-record-fails", _mismatch_case),
):
    with tempfile.TemporaryDirectory(prefix="wiki-provenance-invalid-") as directory:
        repository = Path(directory)
        _initialize_repository(repository)
        _commit_all(repository, "empty baseline")
        mutate(repository)
        case_issues = validate_live_provenance(repository)
        if case_name == "backslash-path-fails":
            passed = any("unsafe or outside" in issue for issue in case_issues)
        else:
            passed = bool(case_issues)
        _record(case_name, passed)


with tempfile.TemporaryDirectory(prefix="wiki-provenance-ci-base-") as directory:
    repository = Path(directory)
    _initialize_repository(repository, manifest=False)
    _write_json(repository / "scripts/raw-artifacts.json", {"legacy": True})
    _commit_all(repository, "obsolete historical contract")
    _write_json(repository / "scripts/raw-artifacts.json", {
        "artifacts": [], "schema_version": 1,
    })
    trusted_base = _commit_all(repository, "trusted contract base")
    _install_artifact(repository)
    _commit_all(repository, "new accepted artifact")
    _record(
        "ci-uses-only-trusted-base-and-proposal",
        validate_ci_provenance(repository, trusted_base) == (),
    )


with tempfile.TemporaryDirectory(prefix="wiki-provenance-unrelated-") as directory:
    repository = Path(directory)
    _initialize_repository(repository)
    _install_artifact(repository)
    trusted_base = _commit_all(repository, "accepted fixture")
    (repository / "README.md").write_text("unrelated contract change\n")
    _commit_all(repository, "unrelated change")
    _record(
        "later-unrelated-change-keeps-identity-valid",
        validate_ci_provenance(repository, trusted_base) == (),
    )


failed = [name for name, passed in results if not passed]
print(f"\nSummary: {len(results) - len(failed)} passed, {len(failed)} failed")
raise SystemExit(1 if failed else 0)
