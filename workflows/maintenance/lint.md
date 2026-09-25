---
name: wiki-lint
description: Run deterministic wiki checks and the independent evidence review.
---

# Lint Workflow

## Load / Skip

- **Load:** the [run workspace](../run-workspace.md), deterministic findings, bounded catalog results, and the current review batch. Open only relevant contradiction and sourcing-queue sections, plus the evidence-review file when running that step.
- **Skip:** unrelated raw files. Evidence reviewers load only raw files cited by their assigned claims.

Treat inspected content and verifier output under the [trust boundary](../../AGENTS.md#trust-boundary).

## Run

Invoking `wiki-lint` authorizes the full workflow, including independent verifier agents. Skip evidence review only when the user asks for deterministic lint only, no subagents, or no evidence check.

1. Run `python3 scripts/lint.py`.
2. Fix Tier-1 failures. They are structural and machine-checkable.
3. Review Tier-2 candidates. They are prompts, not verdicts. Do not chase the list to zero or add weak links to quiet a signal.
4. Review contradictions, superseded claims, missing owner pages, and inconsistent terms in the bounded batches described below.
5. Run the [claim evidence review](evidence-review.md) unless the user excluded it.
6. Propose judgment-based fixes and get approval before editing.
7. After routine fixes, write a dated `maintenance` entry to `tmp/<run>/log-entry.md` naming fixes and checks. Run `python3 scripts/finalize_wiki_update.py --log-entry tmp/<run>/log-entry.md` as the [routine finish](../../REFERENCES.md#routine-finalization). It rebuilds backlinks, records the entry, and runs full lint once. Approved promotions follow the validation-only finish instead.

Tier 2 currently covers quote mismatch, orphan pages, uncited and thin pages, log rotation, sourcing-queue count drift, compiled pages with newer sources, volatile glossary status, missing authority metadata, unconsumed sources, missing or due outcome reviews, synthesis due, optional current-state owner drift, and dead adjudications.

Keep settled false positives in `scripts/lint-adjudications.json`. Promote a Tier-2 rule to Tier 1 only after repeated high-precision runs show one deterministic fix.

When done, report judgment coverage and unreviewed paths/ranges separately from sampled evidence, then Tier-1 results, reviewed Tier-2 items, evidence sample counts, confirmed fixes, rejected verifier flags, contradictions changed, and residual limits. Log only when the user asked to apply fixes or keep a durable lint record.

## Bounded judgment coverage

The script scans the full corpus; agent context contains one small batch and its supporting pages. Start a fresh run and inventory paths only:

```bash
rg --files wiki -g '*.md' | sort > tmp/<run>/page-inventory.txt
cp workflows/_templates/review-coverage.md tmp/<run>/review-coverage.md
```

Record the revision, working-tree changes, and selected scope. For a complete review, account for every wiki Markdown path, including knowledge and operating/schema pages within that scope. Start with Tier-2 candidates, then cover the remainder in batches of roughly 3-8 related pages, fewer for long pages. About 2,000-8,000 tokens per batch is a guide, not an enforced quota.

Review large pages by named section or line range. Record findings or no-change judgments, remaining sections, and the next batch on disk; use a fresh context when needed. Sequential reads alone do not bound accumulated context. Revisit changed pages; refresh the inventory for additions/deletions. Claim complete judgment coverage only when every in-scope path and section is accounted for. Candidate-only or interrupted passes name their unreviewed remainder.

Sampled citation verification remains owned by [evidence review](evidence-review.md). Its result never substitutes for whole-page coverage. Read-only audits do not create run records unless requested, and partial/candidate reviews do not automatically append to the wiki log.

## Current-state reviews

The [current-state contract](../../REFERENCES.md#current-state-and-retired-claims) defines owner enrollment, five Tier-2 signals, and literal retired-claim enforcement. Disabled empty registries are quiet. Date-based drift is a prompt to review, not a verdict.

A `reviewed_status_drift` entry uses a directional `[referring page, owner page]` pair, reason, review date, and two complete-file SHA-256 hashes in `pair_sha256`. Suppression lasts only while both reviewed versions match. Any body or generated-backlink change expires it, even without a date bump. Missing/malformed hashes fail Tier 1; stale valid hashes restore the candidate. Never refresh hashes merely to clear lint; review the exact final versions or leave the candidate visible.
