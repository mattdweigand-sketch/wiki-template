---
name: wiki-review
description: Use this workflow when the user wants to grade dated predictions or decisions against outcomes. Surfaces pages whose review_by date has passed, records the realized outcome, and advances or clears review_by.
---

# Review Workflow - grade dated checkpoints against outcomes

A page opts into the outcome-review loop by adding `review_by: YYYY-MM-DD` to its frontmatter. This workflow checks what happened, records the outcome, and advances or clears the date. The script surfaces due pages; the user supplies the judgment.

## Load / Skip

- **Load:** `python3 scripts/review_due.py` output, the due pages selected for review, `wiki/SCHEMA.md`, `REFERENCES.md` if cross-links or confidence changes are needed, and only the cited sources needed to check the outcome.
- **Skip:** unrelated entity folders, unrelated raw sources, and unrelated workflow files.

## When to run

Run on a recurring cadence or whenever `scripts/review_due.py` reports pages due. `wiki-eval` also surfaces the count each run. Letting dated claims stand ungraded is the failure mode this loop exists to prevent.

## Steps

1. Run `python3 scripts/review_due.py` to list pages whose `review_by` has passed, most overdue first.
2. Pick only the due pages the user wants reviewed now.
3. For each due page, gather what actually happened from cited sources, newer ingests, and the user's judgment. Do not invent an outcome; if the result is not yet knowable, that is itself the finding and `review_by` moves forward.
4. If updating the page, add a dated `## Review log` entry: what was predicted or decided, what actually happened, and the resulting confidence change.
5. Adjust `confidence:` only when the realized outcome justifies it. A prediction that converted can move up; one that missed can move down or become `contested` with the reason logged in `wiki/contradictions.md`. This outcome-driven confidence change does not use `capture_gate.py --kind=synthesis`.
6. Set the next checkpoint: advance `review_by` to the next date the page should be re-graded, or remove it when the prediction or decision has fully resolved.
7. Run `python3 scripts/rebuild_referenced_by.py` and `python3 scripts/lint.py --tier1` after durable edits.
8. Log material review outcomes in `wiki/log.md`, naming the pages graded and any confidence changes.

Review is judgment work. The script only surfaces and validates dates; it does not decide whether an outcome succeeded, failed, or remains open.
