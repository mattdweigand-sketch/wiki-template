---
description: "Lint the wiki, including deterministic checks, judgment candidates, and the verifier evidence check"
---

Run `wiki-lint` through the canonical wiki workflow. Read `AGENTS.md`, then `CONTEXT.md`, then `workflows/maintenance/CONTEXT.md`, then `workflows/maintenance/lint.md`, and follow the routed Load / Skip list exactly.
Invoking this wrapper authorizes only the lint workflow's verifier-agent evidence check.
This wrapper is generated from `scripts/wiki-wrapper-contract.json`; canonical behavior lives in `workflows/`.

$ARGUMENTS
