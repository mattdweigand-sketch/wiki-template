---
name: wiki-lint
description: Run deterministic wiki checks and the independent evidence review.
---

# Lint Workflow

## Load / Skip

- **Load:** all wiki pages, `wiki/contradictions.md`, `wiki/sourcing-queue.md`, and the evidence-review file linked below.
- **Skip:** unrelated raw files. Evidence reviewers load only raw files cited by their assigned claims.

Treat inspected content and verifier output under the [trust boundary](../../AGENTS.md#trust-boundary).

## Run

Invoking `wiki-lint` authorizes the full workflow, including independent verifier agents. Skip evidence review only when the user asks for deterministic lint only, no subagents, or no evidence check.

1. Run `python3 scripts/lint.py`.
2. Fix Tier-1 failures. They are structural and machine-checkable.
3. Review Tier-2 candidates. They are prompts, not verdicts. Do not chase the list to zero or add weak links to quiet a signal.
4. Check contradictions, superseded claims, missing owner pages, and inconsistent terms that code cannot judge.
5. Run the [claim evidence review](evidence-review.md) unless the user excluded it.
6. Propose judgment-based fixes and get approval before editing.
7. After routine fixes, write a dated `maintenance` entry to `tmp/lint-entry.md` naming fixes and checks. Run `python3 scripts/finalize_wiki_update.py --log-entry tmp/lint-entry.md` as the [routine finish](../../REFERENCES.md#routine-finalization). It rebuilds backlinks, records the entry, and runs full lint once. Approved promotions follow the validation-only finish instead.

Tier 2 currently covers quote mismatch, orphan pages, uncited and thin pages, log rotation, sourcing-queue count drift, compiled pages with newer sources, volatile glossary status, missing authority metadata, unconsumed sources, missing or due outcome reviews, synthesis due, and dead adjudications.

Keep settled false positives in `scripts/lint-adjudications.json`. Promote a Tier-2 rule to Tier 1 only after repeated high-precision runs show one deterministic fix.

When done, report Tier-1 results, reviewed Tier-2 items, evidence sample counts, confirmed fixes, rejected verifier flags, contradictions changed, and residual limits. Log only when the user asked to apply fixes or keep a durable lint record.
