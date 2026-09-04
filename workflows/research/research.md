---
name: wiki-research
description: Manual high-rigor wiki research with claim-level independent verification.
---

# Wiki Research

Use this workflow only when the user explicitly invokes `wiki-research`, `$wiki-research`, or `/wiki-research`. It is not the default for important or complex questions.

## Load / Skip

- **Load:** bounded `python3 scripts/wiki_lookup.py index --query "<topic>"` results, `wiki/primer.md`, the pages needed to answer the question, their cited source pages, only the raw files required to verify those claims, `workflows/maintenance/evidence-review.md`, and the citation and provenance rules in `wiki/SCHEMA.md`.
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

4. Complete the independent evidence check exactly as defined in `workflows/maintenance/evidence-review.md`. Create the hidden plant, publish verifier batches, collect one-to-one verdicts from fresh reviewers, and run `python3 scripts/verify_evidence_run.py`. Do not draft a verified answer from a stale, incomplete, or structurally invalid run.
5. Select only verified real claims in `response-draft.json` under the run directory. Its exact fields are `schema_version: 1`, `run_id`, `manifest_sha256`, and a nonempty `statements` list. Each statement contains only `claim_id`; no replacement wording. IDs must be known and unique. Non-VERIFIED findings remain labeled gaps or contradictions outside the verified response.

   ```bash
   python3 scripts/evidence_response.py create --run-dir tmp/evidence-check/<run-id>
   python3 scripts/evidence_response.py render --run-dir tmp/evidence-check/<run-id>
   ```

   Creation is write-once. Rendering uses the captured text and source-page links, with supported authority links when available. It refuses draft, review, packet, or snapshot drift. Use a fresh run when review inputs change.
6. Give the rendered packet and its named claims to a fresh reviewer. The reviewer checks each statement for support, scope, conflation, citation fit, and any flagged source claim.
7. Return the rendered packet only if the fresh reviewer marks every selected statement `VERIFIED`. Otherwise start a fresh run with a narrower selection. Report gaps and contradictions separately without presenting them as verified findings. Do not rewrite the rendered claims.
8. If the user asks to file the result, use the Analysis Capture rules in `ask.md`.

`wiki-research` adds review cost on purpose. It is for cases where the user wants each returned statement bound to checked claims, not for ordinary corpus questions.
