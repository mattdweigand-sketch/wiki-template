---
name: wiki-refresh-assess
description: Build a bounded claim-level assessment for one refresh profile without editing durable wiki files.
---

# Stage 01 - Assess

## Inputs

- `../CONTEXT.md` and one selected profile.
- `tmp/wiki-refresh/<run>/request.md`.
- The current-state owner, its cited sources, newer sources that directly affect the claims, and relevant open contradictions.

## Method

1. Write the claims being checked before expanding the source set. Keep each claim atomic enough to change independently.
2. Find the existing current-state owner. Prefer one existing page. If none can own the surface cleanly, record `owner missing`; do not create one in this stage.
3. Compare each claim with the selected profile's evidence hierarchy. Dates, scope, edition, region, plan, and source authority are part of the claim.
4. Classify each claim as `current`, `superseded`, `new`, `unsupported`, or `conflicting`.
5. For `superseded`, record the exact phrases that could leak and the supported replacement. Do not add a phrase merely because it is unfashionable; retirement requires a reviewed factual or messaging change.
6. Record the next action separately as `no change`, `propose`, `needs source`, or `unresolved contradiction`. If the corpus cannot establish current reality, keep the claim `unsupported` or `conflicting` and route missing evidence to ingest or explicit research. Do not use confident copy to hide an evidence gap.

Use [`../templates/assessment.md`](../templates/assessment.md) and write `tmp/wiki-refresh/<run>/assessment.md`.

## Human Check

Present a short assessment summary. The user can correct the scope or source hierarchy before proposal drafting. Assessment does not authorize durable edits.

## Exit

Proceed only when every in-scope claim has a classification and evidence. Otherwise stop with `needs source` or `unresolved contradiction`.
