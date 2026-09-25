---
name: wiki-refresh-propose
description: Convert one completed refresh assessment into exact, reviewable owner-page and retirement-policy changes.
---

# Stage 02 - Propose

## Inputs

- `tmp/wiki-refresh/<run>/request.md`.
- `tmp/wiki-refresh/<run>/assessment.md` with no unclassified claims.
- Exact current preimages of every proposed durable target.

## Method

1. Choose one owner page for each changing claim. Prefer updating an existing owner over creating a new page.
2. Draft the smallest exact postimage that makes the supported current claim easy to reuse. Preserve qualifications, dates, scope, citations, and open conflicts.
3. For each superseded claim, propose a `scripts/retired-claims.json` entry containing a stable ID, profile, retirement date, sorted exact phrases, replacement wording, current-state owner reference, and reason.
4. Search active knowledge for each proposed retired phrase. List every page that must change. Do not edit source or historical records to make the search empty.
5. Include any needed `scripts/current-state-owners.json`, `wiki/contradictions.md`, `wiki/sourcing-queue.md`, backlink, index, and log changes in the same proposal.
6. Identify the write boundary: routine maintenance, `analysis-capture`, `artifact-promotion`, or `synthesis-promotion`.

Use [`../templates/proposal.md`](../templates/proposal.md) and write `tmp/wiki-refresh/<run>/proposal.md`. Put exact drafted page postimages under `tmp/wiki-refresh/<run>/authored/` when the applicable gate or review requires them.

## Human Check

Show the complete proposal: targets, exact replacements, retired phrases, historical exclusions, citations, conflicts, and write boundary. Stop. The user must accept this proposal before Stage 03.

An approval covers only the displayed proposal. Any changed phrase, replacement, target, source, scope, or preimage returns here for a new review. If the proposal crosses the repository's exact approval gate, the gate's displayed Authorization ID remains the executable authority.

## Exit

Proceed only with an explicit user acceptance of the unchanged proposal. A declined or no-change proposal ends the run without durable edits.
