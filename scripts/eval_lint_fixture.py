#!/usr/bin/env python3
"""Shared fixture helpers for the split lint eval suites.

Guards lint's checks against going vacuous: every check in lint.py's
registries — TIER1_PATH_CHECKS, TIER1_PAGE_CHECKS, the repo/meta-level checks
inside tier1(), and TIER2_SIGNALS (those registries are authoritative; this
docstring deliberately does not enumerate them) — gets a seeded violation that
must fire, and the adjudication/suppression machinery gets positive and
negative cases. A check that cannot fail is indistinguishable from no check;
this suite exists so a future lint edit cannot silently disarm one.

Runs against the fixture mini-wiki in scripts/fixtures/wiki-lint/, copied to
a system temp directory per case. Writes nothing inside the repo.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from wiki_lint_contract import ADJUDICATION_CATEGORY_FIELDS, FOLDER_TYPE

REPO_ROOT = Path(__file__).resolve().parents[1]
LINT = REPO_ROOT / "scripts" / "lint.py"
FIXTURE = REPO_ROOT / "scripts" / "fixtures" / "wiki-lint"

results = []


def _build_lint_fixture_repository() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Build one configured Git baseline that individual lint cases can copy."""
    temporary = tempfile.TemporaryDirectory(prefix="wiki-lint-baseline-")
    root = Path(temporary.name) / "repo"
    shutil.copytree(FIXTURE / "wiki", root / "wiki")
    shutil.copytree(FIXTURE / "scripts", root / "scripts")
    for folder in FOLDER_TYPE:
        (root / "wiki" / folder).mkdir(exist_ok=True)
    raw_registry = json.loads(
        (root / "scripts/raw-buckets.json").read_text(encoding="utf-8")
    )
    for bucket in raw_registry["buckets"]:
        (root / "raw" / bucket).mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "lint-fixture@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Lint Fixture"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "lint fixture baseline"], cwd=root, check=True
    )
    return temporary, root


_FIXTURE_REPOSITORY_TEMP, _FIXTURE_REPOSITORY = _build_lint_fixture_repository()


def copy_fixture(root):
    """Materialize the fixture mini-wiki (wiki/ + scripts/) under `root`."""
    shutil.copytree(_FIXTURE_REPOSITORY, root, dirs_exist_ok=True)


def run_case(name, mutate, args=("--tier1",), expect_code=0, expect=(), absent=()):
    """Copy the fixture, apply `mutate(root)`, run lint, assert on output."""
    with tempfile.TemporaryDirectory(prefix="wiki-lint-eval-") as td:
        root = Path(td)
        copy_fixture(root)
        if mutate:
            mutate(root)
        proc = subprocess.run(
            [sys.executable, str(LINT), *args],
            cwd=root, text=True, capture_output=True,
        )
        output = proc.stdout + proc.stderr
        ok = proc.returncode == expect_code
        for marker in expect:
            ok = ok and marker in output
        for marker in absent:
            ok = ok and marker not in output
        results.append((name, ok))
        if not ok:
            print(f"FAIL {name}")
            print(f"  exit {proc.returncode} (expected {expect_code})")
            for marker in expect:
                if marker not in output:
                    print(f"  missing: {marker!r}")
            for marker in absent:
                if marker in output:
                    print(f"  unexpected: {marker!r}")
            print("  output: " + output[:2000].replace("\n", " | "))
        else:
            print(f"PASS {name}")


def append(root, rel, text):
    p = root / rel
    p.write_text(p.read_text() + text)


def edit(root, rel, old, new):
    p = root / rel
    t = p.read_text()
    assert old in t, f"fixture drift: {old!r} not in {rel}"
    p.write_text(t.replace(old, new, 1))


def add_index_row(root, rel, summary):
    append(root, "wiki/index.md", f"| [{Path(rel).name}]({rel}) | {summary} |\n")


def write_adjudications(root: Path, **kwargs: object) -> None:
    base = {field: [] for field in ADJUDICATION_CATEGORY_FIELDS.values()}
    base.update(kwargs)
    (root / "scripts" / "lint-adjudications.json").write_text(json.dumps(base))


def write_raw_buckets(root, value):
    (root / "scripts" / "raw-buckets.json").write_text(json.dumps(value))


def write_registered_raw_fixture(
    root: Path,
    relative: str,
    content: str = "raw fixture",
) -> None:
    """Write one raw file and bind it to the gamma source in the fixture manifest."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content_bytes = content.encode("utf-8")
    path.write_bytes(content_bytes)
    manifest = {
        "artifacts": [
            {
                "captured_at": "2026-06-01",
                "files": [
                    {
                        "path": relative,
                        "sha256": hashlib.sha256(content_bytes).hexdigest(),
                        "size": len(content_bytes),
                    }
                ],
                "source_slug": "gamma",
            }
        ],
        "schema_version": 1,
    }
    (root / "scripts/raw-artifacts.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    edit(
        root,
        "wiki/sources/gamma.md",
        'sources: ["experience: lint eval fixture"]',
        f"sources: [{relative}]",
    )


def add_authority(root: Path, rel: str, *lines: str) -> None:
    p = root / rel
    t = p.read_text()
    marker = "confidence: medium\n"
    assert marker in t, f"fixture drift: no confidence marker in {rel}"
    p.write_text(t.replace(marker, marker + "\n".join(lines) + "\n", 1))


def write_peer_source(root, source_name="gamma"):
    (root / "wiki" / "sources" / "peer-source.md").write_text(
        '---\ntitle: "Peer Source"\ntype: source\ncreated: 2026-06-01\n'
        'updated: 2026-06-01\nsources: ["experience: lint eval fixture"]\n'
        'tags: [fixture]\nconfidence: medium\nsource_type: other\n'
        'agent_use_cases:\n  - lint eval fixture\n---\n\n'
        f'This peer source links [[{source_name}]], but source-to-source links '
        'must not satisfy the source consumption invariant.\n\n'
        '## Open questions / gaps\n\n- Fixture page; no real questions.\n'
    )
    add_index_row(root, "sources/peer-source.md", "fixture peer source")
    append(root, "wiki/concepts/alpha.md", "\n- Related: [[peer-source]]\n")



def fail_prerequisite(name, detail, *, sink=None, emit=True):
    """Record an unavailable eval prerequisite as a real failed case."""
    target = results if sink is None else sink
    target.append((name, False))
    if emit:
        print(f"FAIL {name} ({detail})")


def finish_lint_eval() -> int:
    """Print this suite's result count and return its exit code."""
    print()
    failed = [name for name, ok in results if not ok]
    print(f"Summary: {len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0
