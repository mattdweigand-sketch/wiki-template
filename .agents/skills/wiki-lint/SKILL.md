---
name: wiki-lint
description: Run the wiki lint workflow, including its verifier-agent evidence check. Use when the user says $wiki-lint, wiki-lint, lint the wiki, run lint, or wants deterministic and judgment-oriented wiki checks.
---

# Wiki Lint

Run `wiki-lint` through the canonical wiki workflow for this repo. Read `AGENTS.md`, then `CONTEXT.md`, then `workflows/maintenance/CONTEXT.md`, then `workflows/maintenance/lint.md`, and follow the routed Load / Skip list exactly.
Invoking this wrapper authorizes only the lint workflow's verifier-agent evidence check.
This wrapper is generated from `scripts/wiki-wrapper-contract.json`; canonical behavior lives in `workflows/`.
