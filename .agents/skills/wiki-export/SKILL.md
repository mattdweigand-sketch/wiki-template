---
name: wiki-export
description: Run the wiki export workflow. Use when the user says $wiki-export, wiki-export, export the wiki, back up the wiki, or wants a zip backup of the corpus.
---

# Wiki Export

Run `wiki-export` through the canonical wiki workflow for this repo. Read `AGENTS.md`, then `CONTEXT.md`, then `workflows/maintenance/CONTEXT.md`, then `workflows/maintenance/export.md`, and follow the routed Load / Skip list exactly.
Command hint: `python3 scripts/export_wiki.py --date YYYY-MM-DD`.
This wrapper is generated from `scripts/wiki-wrapper-contract.json`; canonical behavior lives in `workflows/`.
