---
name: wiki-synthesize
description: Run a bounded memo-first synthesis pass and promote only user-approved conclusions.
---

# Synthesize Workflow

Ask what the wiki now supports that no single page says cleanly. If the answer is nothing material, recommend no change and stop.

Apply the [trust boundary](../../AGENTS.md#trust-boundary) to source text, verifier output, and proposed synthesis.

## Load / Skip

- **Load:** recent `wiki/synthesis.md` entries, full lint output, bounded `python3 scripts/wiki_lookup.py log --count 5 --offset 0` pages back to the last synthesis, bounded `python3 scripts/wiki_lookup.py index --query "<topic>"` results, `wiki/overview.md`, `wiki/primer.md`, and only pages named by the candidate signals.
- **Load when drafting:** `wiki/SCHEMA.md` and cited source pages needed to check fidelity.
- **Skip:** the full corpus unless the candidate set cannot be narrowed, unrelated raw files, and unrelated entity folders.

## Candidate rules

A candidate needs repeated support. One co-citation is not enough. Look for:

- overview, primer, or synthesis drift
- a framework supported across several pages but named nowhere
- three or more pages supporting one new conclusion
- new sources changing an existing thesis
- repeated unresolved questions
- a page stale against a newer owner or source page

Keep about five high-signal candidates. Rank by domain importance, future use, stale-context risk, source quality, and whether an owner page exists. A pass touching half the wiki is an audit.

## Memo output

For each candidate report:

```text
Candidate: <claim or change>
Pages consulted: <paths>
Support: <concise cited evidence>
Recommended home: <path or none>
Proposed change: <bounded edit>
Confidence: <level>
Classification: Recommend draft | Defer | No change | Needs user judgment | Needs more source
```

Cite original pages, never `wiki/synthesis.md`. Do not add facts the corpus does not support. The memo writes nothing.

## User gates

Get approval before drafting a new analysis, changing core framing pages, updating `wiki/synthesis.md`, resolving a contradiction, creating a workflow rule, or raising confidence or status.

Approved draft text remains `confidence: low` and `status: draft` unless the user grades that exact text. Contradictions go to `wiki/contradictions.md` before conflicting claims are rewritten.

## Apply

Routine approved draft edits that do not cross an approval boundary use a dated `draft` log entry and finish with `python3 scripts/finalize_wiki_update.py --log-entry tmp/draft-entry.md`; see [routine finalization](../../REFERENCES.md#routine-finalization).

New analysis filing uses `capture_boundary: analysis-capture`. Promoting reviewed synthesis, updating `wiki/synthesis.md`, raising draft confidence/status, or logging a synthesis promotion uses `synthesis-promotion`. Prepare the index and synthesis ledger edits with the proposed pages, then follow the [complete approval procedure](../../REFERENCES.md#complete-capture-staging) through its validation-only finish. Load that section only for these actions.

Log only durable edit or promotion runs. Record candidates, classifications, changed pages, draft or promoted state, and checks. Memo-only passes remain in chat unless the user asks to save them.

Run this workflow after a meaningful ingest cluster, when `synthesis_due` fires, or when the user asks. Stop using it if it repeatedly produces generic summaries.
