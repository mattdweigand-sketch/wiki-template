---
name: wiki-ingest
description: Route a supplied source into the canonical ingest recipe and conditional transcript checks.
---

# Ingest Workspace

Use this route when the user asks to ingest a supplied source or turn a raw artifact into wiki pages. Read the [ingest recipe](ingest.md) before handling the source; it owns execution and finalization.

## Load / Skip

- **Load:** [ingest.md](ingest.md), then only its named inputs and directly affected pages.
- **Load for transcripts:** [transcript evidence](transcript-evidence.md).
- **Skip:** unrelated wiki pages, sources, and workflows.

## Output and review

The recipe preserves immutable, local-only evidence under `raw/`, records its exact identity in `scripts/raw-artifacts.json`, creates its source page, and updates affected knowledge and catalog entries.

An explicit ingest request authorizes routine durable edits. If the work crosses analysis capture or artifact promotion, use that boundary's workflow and the [complete approval procedure](../../REFERENCES.md#complete-capture-staging).

Completion requires the recipe's provenance checks, backlink rebuild, log entry, final lint, matching passed finalization result, and touched-page Tier-2 review. Run state lives under `tmp/<run>/`.
