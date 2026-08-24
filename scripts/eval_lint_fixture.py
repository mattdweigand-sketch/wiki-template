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
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _file_transactions import run_transaction
from _wiki_parse import META_PAGES, get_entity_pages

REPO_ROOT = Path(__file__).resolve().parents[1]
LINT = REPO_ROOT / "scripts" / "lint.py"
FIXTURE = REPO_ROOT / "scripts" / "fixtures" / "wiki-lint"

results = []


def copy_fixture(root):
    """Materialize the fixture mini-wiki (wiki/ + scripts/) under `root`."""
    shutil.copytree(FIXTURE / "wiki", root / "wiki")
    shutil.copytree(FIXTURE / "scripts", root / "scripts")


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
    base = {"accepted_orphans": [], "reviewed_quotes": [],
            "reviewed_recompile_candidates": [],
            "reviewed_authority_missing": [], "reviewed_glossary_volatile": [],
            "reviewed_unconsumed_sources": []}
    base.update(kwargs)
    (root / "scripts" / "lint-adjudications.json").write_text(json.dumps(base))


def write_raw_buckets(root, value):
    (root / "scripts" / "raw-buckets.json").write_text(json.dumps(value))


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
