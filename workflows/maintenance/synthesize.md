---
name: wiki-synthesize
description: Use this workflow to run a bounded synthesis pass over the corpus: detect what the wiki now implies across pages, surface it as a reviewable memo with no file edits, and promote only what the user approves. Recommending "no change" is a valid outcome.
---

# Synthesize Workflow

Digestion, not ingestion. Ingest brings material in and wires each source into the pages it touches; lint finds defects; this workflow finds what the corpus now implies across several pages and surfaces it for the user to grade. It writes nothing before the user approves a draft or edit scope.

Apply the canonical [trust boundary](../../AGENTS.md#trust-boundary) to source content, verifier output, and proposed synthesis text.

## Core Principle

A synthesis pass is only valuable when it can answer one question:

**What does the wiki now know that no single page says cleanly yet?**

If the honest answer is "nothing material," the pass stops and recommends no change. That is a successful run.

Division of labor:

1. **Primary target: the wiki's self-model.** `wiki/overview.md` and `wiki/primer.md` are cross-corpus judgments no single ingest has the scope to write. They must be drafted and graded, never auto-promoted.
2. **Secondary: genuinely emergent frameworks and cluster distillations.** Three or more pages that now support one conclusion with no page naming it.
3. **Backstop only: per-page "Open questions / gaps" sections.** Ingest writes and updates these in-band, and lint checks that they are present. The synthesize pass flags one only when ingest plainly missed it.

## Memo-Then-Draft-Then-Grade Contract

Every page in `wiki/` may be consumed by future agents with no human present at read time. Synthesized content carries its epistemic state in-band: `confidence: low` where frontmatter applies, and `status: draft` on meta pages that carry a status field. User review is the grade. Only exact proposal approval with `capture_boundary: synthesis-promotion` flips those markers or records a synthesis promotion.

This workflow is memo-first:

1. The pass proposes candidates in chat with an evidence packet and classification.
2. The user approves which candidates are worth drafting or editing.
3. Approved edits land at draft/low unless the user explicitly graded the exact content.
4. Promotion, ledger updates, and confidence/status flips still stop at the exact proposal gate in `AGENTS.md`.

## Load / Skip

- **Load:** `wiki/synthesis.md` (read Current state and the last few run entries first), recent synthesis records in `scripts/capture-runs.jsonl` when checking whether a prior synthesis scope was already approved, full `python3 scripts/lint.py` output, `wiki/log.md` entries since the last `synthesis` entry, `wiki/index.md`, `wiki/overview.md`, and only the candidate pages the detected signals point to. At drafting time, also load `wiki/SCHEMA.md` and `REFERENCES.md`.
- **Optional:** wiki source pages cited by candidate pages when source-page fidelity matters. Open raw files only when a source-page claim itself needs checking; synthesis normally distills wiki pages, not raw artifacts.
- **Skip:** the full wiki unless the candidate set genuinely cannot be narrowed, unrelated `raw/` sources, and entity folders the candidates do not touch.

## Candidate Signals

A page or cluster becomes a candidate when one of these is true:

- `wiki/overview.md`, `wiki/primer.md`, or `wiki/synthesis.md` no longer reflects the current corpus.
- A reusable framework has emerged from several sources with no page naming it.
- Three or more pages now support the same conclusion.
- Recent ingests modify or challenge an existing thesis.
- Multiple pages repeat the same unresolved question.
- A page is stale relative to a newer owner page it depends on.

One co-citation is not a cluster; a signal must recur before it is a candidate.

## Pass Size And Ranking

Keep a pass small: aim for about five high-signal items. If more surface, rank by:

1. Importance to the configured domain.
2. Usefulness to future agents.
3. Risk of stale or misleading context if left alone.
4. Number and quality of supporting pages.
5. Whether a durable home already exists.

A pass that would touch half the wiki is an audit, not a synthesis loop iteration.

## Allowed Outputs

A memo-first pass may produce:

- A chat-only synthesis memo.
- A proposed update list.
- A recommendation to draft a low-confidence page update.
- A recommendation to update `wiki/synthesis.md`.
- A recommendation to update `wiki/overview.md` or `wiki/primer.md`.
- A recommendation to do nothing.

It may not, without user approval, promote conclusions, flip confidence, update ledgers, rewrite durable pages, or resolve contradictions.

## Evidence Packet

Present one packet per candidate in chat before any edit:

```text
Candidate:
Pages consulted:
Claim now supported:
Why this matters:
Recommended home:
Proposed change:
Confidence:
Classification:
Approval needed:
```

Ground every claim in cited pages and include concise evidence snippets or citations for the support. Synthesis combines what the corpus says; it never adds a fact the corpus does not contain. Cite original pages, never `wiki/synthesis.md`: the ledger is for orientation and drift tracking only, and treating it as a source lets summaries silently replace the pages they summarize.

## Done Condition

The memo-first pass is done when every candidate is classified as one of:

- **Recommend draft** - worth drafting if the user approves the edit scope.
- **Defer** - real but not now; note why in the memo.
- **No change** - examined and rejected, with the reason.
- **Needs user judgment** - a fork only the user can call.
- **Needs more source material** - the corpus does not yet support it.

After the user approves a candidate, its classification becomes **Draft this** and the durable-edit flow below begins.

## Human Gates

The user must approve before:

- Creating a new `wiki/analyses/` page.
- Drafting or changing `wiki/overview.md`, `wiki/primer.md`, or other core framing pages.
- Updating `wiki/synthesis.md`.
- Flipping draft/low content to approved confidence.
- Resolving a contradiction.
- Turning a synthesis into a durable workflow rule.

Never silently overwrite verified content. Additions to an existing page go in clearly bounded sections; anything that conflicts with what a page already says is flagged in `wiki/contradictions.md` first. When refreshing overview, primer, index, or the synthesis digest, do not copy volatile current-state values from owner pages; name the thread and link the owner page.

## Durable-Edit Flow After Approval

1. If the user approves drafting a new `wiki/analyses/` page, stage every exact postimage and an `analysis-capture` proposal under `tmp/`, then follow `AGENTS.md`.

   ```bash
   python3 scripts/capture_gate.py --proposal tmp/<proposal>.json --json
   ```

   Show the complete preview and stop for its exact digest. Other synthesis draft edits that neither file a new analysis nor cross the synthesis-promotion boundary in Step 2 are routine page updates and skip the gate.

2. For synthesis promotion, ledger updates, durable core-page drafts, or confidence/status flips, compose every exact postimage before preview. New synthesized content lands at `confidence: low` (restated in the body) and `status: draft` on meta pages unless the user explicitly graded that exact text. Include any new `wiki/index.md` row, the `wiki/synthesis.md` digest and run-ledger update, and the `wiki/log.md` entry described below. Then stage a `synthesis-promotion` proposal and all of those postimages:

   ```bash
   python3 scripts/capture_gate.py --proposal tmp/<proposal>.json --json
   # After approval of the displayed authorization_digest:
   python3 scripts/capture_gate.py --proposal tmp/<proposal>.json \
     --approve-digest <authorization_digest> --json
   ```

   The proposal's primary destination must be one of its exact targets, and the editable scope must equal the target set. Apply installs those targets and the combined ledger record in one transaction. Do not manually change approved targets afterward.

3. Run:

   ```bash
   python3 scripts/validate_capture_runs.py
   python3 scripts/rebuild_referenced_by.py
   python3 scripts/lint.py --tier1
   ```

   Backlink changes are system-generated maintenance. They use guarded atomic page writes and converge when rerun after interruption.

   All three must pass.

## Log Entry Shape

For a memo-only pass with no durable edits, report in chat and do not log unless the user asks for a durable record.

For an approved draft/edit pass:

```text
## [YYYY-MM-DD] synthesis | <short batch description>
Candidates considered: <count, with the signals that produced them>
Classifications: <Draft this / Defer / No change / Needs user judgment / Needs more source>
Pages touched: <pages, or none>
Held at draft/low pending review: <pages>
Promoted after review: pending | <pages>
Verification: rebuild_referenced_by.py and lint.py --tier1 passed
```

For an approved promotion, append the promotion result:

```text
## [YYYY-MM-DD] synthesis promotion | <short batch description>
Promoted after review: <pages>
Ledger updated: wiki/synthesis.md
Gate: capture_gate.py exact synthesis-promotion proposal applied; validate_capture_runs.py passed
Verification: rebuild_referenced_by.py and lint.py --tier1 passed
```

## Success Criteria And Kill Switch

A pass is worth running only if it produces at least one of:

- A clearer current-state summary.
- A reusable framework future agents can cite.
- A stale-page correction.
- A reduced need to re-read many pages.
- A sharper next question for the user.
- A surfaced contradiction or unresolved fork.

Judge quality, not frequency. An empty pass that correctly recommends no change is a success. A pass that mostly produces generic summaries is not. If generic summaries become the pattern, stop using this workflow and let ingest plus lint carry the load.

## Recursive Maintenance Checks

### Synthesis -> Prune

During candidate review, ask whether the strongest action is to merge, shorten, or remove ambiguity rather than add a new page or section. Use this only for the pages already in the candidate set. A prune recommendation can be `No change`, a merge into an existing owner page, or a bounded wording cleanup. If it wants to touch a broad slice of the corpus, stop and treat it as an audit, not a synthesis loop.

### Contradiction -> Resolution

If a synthesis candidate depends on conflicting claims, do not smooth over the conflict. Either recommend a bounded owner-page resolution when the newer source clearly supersedes the old claim, or flag the unresolved conflict in `wiki/contradictions.md` before any durable rewrite. Treat nuance as scope clarification, not contradiction.

## Cadence

Run when lint's `synthesis_due` Tier-2 signal fires, after a cluster of related ingests, or whenever the user asks. It stays a manual loop: the pass must always stop for the user's grade, so only the trigger is automated. Pair with `refresh-sourcing-queue`, which tracks what the wiki is missing from outside; this workflow tracks what the wiki already contains but has not yet said out loud.
