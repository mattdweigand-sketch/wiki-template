---
name: wiki-refresh
description: Review one volatile messaging surface against current evidence, retire superseded claims, and update its current-state owner without rewriting source history.
---

# Wiki Refresh

Use this pipeline when product truth or approved messaging has changed and older wording must not leak into active wiki answers. It is generic across the wiki, but every run selects one bounded profile. The initial profiles are deliberately narrow.

## Load / Skip

- **Load:** the selected profile below, `scripts/current-state-owners.json`, `scripts/retired-claims.json`, the named current-state owner if one exists, `wiki/contradictions.md`, and only the cited source and dependent pages needed for the selected claims.
- **Load when applying:** `wiki/SCHEMA.md`, `REFERENCES.md`, the applicable approval-gate workflow when a proposed change crosses a guarded boundary, and the exact target preimages.
- **Skip:** unrelated entity folders, unrelated raw sources, other refresh profiles, and old source pages merely because they contain retired wording.

Tracking ships disabled with no owners or retired claims. Enroll only reviewed non-source entity pages with `authority_freshness: current-state`; the [registry contract](../../../REFERENCES.md#current-state-and-retired-claims) owns validation details. Personal and noncommercial wikis use only relevant profiles.

## Profiles

| Profile | Open | Volatile surface |
|---|---|---|
| `talk-track` | [`profiles/talk-track.md`](profiles/talk-track.md) | Organization or project narrative, value proposition, and approved vocabulary |
| `pricing-and-entitlements` | [`profiles/pricing-and-entitlements.md`](profiles/pricing-and-entitlements.md) | Pricing, credits, plan boundaries, and entitlements |
| `product-availability` | [`profiles/product-availability.md`](profiles/product-availability.md) | Availability, rollout state, regions, platforms, and prerequisites |
| `security-and-retention` | [`profiles/security-and-retention.md`](profiles/security-and-retention.md) | Security, privacy, training, retention, and compliance claims |

If the request names a surface, select the matching profile. If it does not, identify the affected surface before opening a profile. Do not combine profiles merely because one source touches several; split the work into independently reviewable runs.

## Run Workspace

Use `tmp/wiki-refresh/<YYYYMMDD-HHMMSS>-<profile>/`. It is disposable working state, not wiki content.

```text
tmp/wiki-refresh/<run>/
|-- request.md
|-- assessment.md
|-- proposal.md
|-- authored/          # exact draft postimages when approved work needs them
`-- verification.md
```

Initialize this directory from the shared [run starter](../../run-workspace.md), including `status.md` and `verification.md`. Copy the user request and selected profile into `request.md`. Record acceptance in the run status and proposal before Stage 03. Each later stage consumes the preceding artifact. Record actual user acceptance; a progress note alone cannot authorize an apply.

## Pipeline

1. [`01-assess/CONTEXT.md`](01-assess/CONTEXT.md) compares bounded claims with the strongest current evidence and writes `assessment.md`.
2. [`02-propose/CONTEXT.md`](02-propose/CONTEXT.md) turns accepted assessment findings into exact page and retirement-policy changes in `proposal.md`, shows the proposal, and stops for review.
3. [`03-apply/CONTEXT.md`](03-apply/CONTEXT.md) applies only the reviewed proposal through the boundary it actually crosses, then verifies the final tree.

Never jump from a source directly to durable wording. A run can end after assessment with `no change`, `needs source`, or `unresolved contradiction`. No-change ends without edits. Needs-source and unresolved-contradiction outcomes record incomplete work and must not be reported as applied refreshes.

## Authority Model

- Current messaging belongs on an enrolled current-state owner page, not on a source page or in the refresh workflow.
- `scripts/retired-claims.json` owns reviewed phrases that are no longer allowed in active knowledge. Tier-1 lint rejects those phrases in compiled entity and active meta pages.
- Historical evidence remains intact. Retired phrases are allowed under `raw/`, `wiki/sources/`, `wiki/log.md`, `wiki/contradictions.md`, and `wiki/sourcing-queue.md`.
- A retired-claim entry must point to an existing page enrolled in `scripts/current-state-owners.json`. The replacement must exist before the ban is durable.
- The model judges evidence quality, claim equivalence, and proposed wording. Configuration owns profiles and retired phrases. Code owns schema validation and literal enforcement.

## Review Boundary

Every run is memo-first and human-reviewed. Showing `proposal.md` does not authorize edits. Apply only after the user accepts that proposal.

Routine owner-page corrections, retirement-registry updates, contradiction entries, and log entries remain routine maintenance writes. If the proposal creates a new analysis, applies an artifact promotion, or promotes reviewed synthesis, use the exact approval gate for that boundary. In particular, bootstrapping a new talk-track analysis uses `analysis-capture`; do not weaken the gate to make the first refresh easier.

## Done

A run is complete when the selected claims have classifications, the user-reviewed changes are applied or explicitly declined, retired wording is absent from active knowledge, the replacement owner is current and cited, contradictions remain visible, and the selected finalization path passes. No-change and declined runs make no content writes; report those outcomes separately.
