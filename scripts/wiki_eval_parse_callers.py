#!/usr/bin/env python3
"""Behavior regression eval for Markdown parser callers."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from eval_lib import Results

results = Results()
check = results.record
CRLF_RAW = (
    "---\r\n"
    "title: edge sample\r\n"
    "type: concept\r\n"
    "tags: [agent, money]\r\n"
    "review_by: 2020-01-01\r\n"
    "---\r\n"
    "Body links [[real-page]] and [[sources/aliased|shown text]].\r\n"
    "A folder pointer [[concepts/]] and an in-code link `[[in-code]]`.\r\n"
    "A fenced one (language tag + an unbalanced stray backtick inside):\r\n"
    "```python\r\n"
    "a stray ` backtick then\r\n"
    "[[fenced-example]]\r\n"
    "```\r\n"
)

# One CRLF page through the callers must produce consistent behavior.

with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "wiki"
    (root / "concepts").mkdir(parents=True)
    (root / "sources").mkdir(parents=True)
    # Page under test: written with CRLF bytes on disk.
    page = root / "concepts" / "edge.md"
    page.write_bytes(CRLF_RAW.encode("utf-8"))
    # A real target so the link resolves and an inbound edge can form.
    (root / "sources" / "real-page.md").write_bytes(
        ("---\ntitle: real\ntype: source\ncreated: 2026-01-01\n"
         "updated: 2026-01-01\nsources: []\ntags: [agent]\n"
         "confidence: medium\nsource_type: other\n---\nbody\n").encode("utf-8")
    )

    # review_due: review_by is read from the CRLF page and surfaces as overdue.
    rd = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "review_due.py"),
                         "--root", str(root), "--today", "2026-06-21"],
                        text=True, capture_output=True)
    check("caller-review-due-exits-clean", rd.returncode == 0,
          detail=f"exit={rd.returncode}; stderr={rd.stderr!r}")
    check("caller-review-due-reads-crlf-review-by",
          "concepts/edge.md" in rd.stdout and "1 page(s)" in rd.stdout,
          detail=rd.stdout.replace("\n", " | "))

    # rebuild_referenced_by: the authored [[real-page]] body link from the CRLF
    # page produces an inbound edge on real-page.md, proving the LF-normalized
    # CRLF page is scanned with the shared LINK_RE grammar.
    rebuild = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "rebuild_referenced_by.py")],
        cwd=td, text=True, capture_output=True,
    )
    check("caller-rebuild-exits-clean", rebuild.returncode == 0,
          detail=f"exit={rebuild.returncode}; stderr={rebuild.stderr!r}")
    real_text = (root / "sources" / "real-page.md").read_text(encoding="utf-8")
    check("caller-rebuild-links-crlf-page",
          "## Referenced by" in real_text and "[[edge]]" in real_text,
          detail=real_text)
    # Nothing links to edge.md, so it gets the no-inbound marker. This pins that
    # the [[real-page]]/[[aliased]] links it emits are treated as outbound only.
    edge_text = page.read_text(encoding="utf-8")
    check("caller-rebuild-edge-has-no-inbound",
          "_No inbound links yet._" in edge_text,
          detail=edge_text)

sys.exit(results.finish())
