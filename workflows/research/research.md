---
name: wiki-research
description: Manual high-rigor wiki research with claim-level independent verification.
---

# Wiki Research

Use this workflow only when the user explicitly invokes `wiki-research`, `$wiki-research`, or `/wiki-research`. It is not the default for important or complex questions.

## Load / Skip

- **Load:** `wiki/index.md`, `wiki/primer.md`, the pages needed to answer the question, their cited source pages, and only the raw files required to verify those claims. Load the evidence-check section of `workflows/maintenance/lint.md` and the citation and provenance rules in `wiki/SCHEMA.md`.
- **Skip:** unrelated entity folders, unrelated raw files, and maintenance workflows other than the evidence-check instructions.

## Steps

1. Define the question and the exact page set to research. Start narrow and expand only when a named gap requires it.
2. Read the selected pages and their source closure. Record contradictions, unsupported claims, and missing evidence before drafting.
3. Build a targeted evidence sample containing every cited claim on the selected pages.

   ```bash
   python3 scripts/build_evidence_sample.py \
     --run-id YYYYMMDD-HHMMSS \
     --path wiki/<entity-folder>/<page>.md \
     --path wiki/<entity-folder>/<other-page>.md
   ```

4. Complete the independent evidence check exactly as defined in `workflows/maintenance/lint.md`. Create the hidden plant, publish verifier batches, collect one-to-one verdicts from fresh reviewers, and run `python3 scripts/verify_evidence_run.py`. Do not draft a verified answer from a stale, incomplete, or structurally invalid run.
5. Draft the answer after the run passes. Bind each returned statement to one or more verified claim IDs. Place the wiki page and source citations beside the statement.
6. Give the draft and its named claims to a fresh reviewer. The reviewer checks each statement for support, scope, conflation, citation fit, and any flagged source claim.
7. Return only statements the reviewer marks `VERIFIED`. Remove or label gaps, contradictions, and flagged claims. Do not present them as verified findings.
8. If the user asks to file the result, use the Analysis Capture rules in `ask.md`.

`wiki-research` adds review cost on purpose. It is for cases where the user wants each returned statement bound to checked claims, not for ordinary corpus questions.
