---
name: wiki-maintenance
description: Router for initial domain setup, optional repository and backup connection, wiki hygiene, tooling evals, artifact promotion, first-person capture, corpus synthesis, and export. Open the one task file you need.
---

# Maintenance Workspace

Initial domain setup, optional repository and backup connection, wiki hygiene, tooling evals, artifact promotion, capture, corpus synthesis, and export. Load this router, then open only the one task file the work calls for. Do not pull every task file into context. `wiki-setup` and `wiki-capture` are shortcuts for tasks in this workspace, not separate workflows.

Invoking `wiki-lint` through either agent wrapper authorizes the full lint workflow, including its verifier-agent evidence check, unless the user asks for deterministic-only lint, no subagents, or skipping the evidence check.

Wrapper-surface maintenance is tooling eval work. If the task concerns `.claude/commands/`, `.agents/skills/`, or `scripts/check_wrapper_parity.py`, open [`eval.md`](eval.md).

Follow the [approval boundaries](../../AGENTS.md#exact-approval-boundary) and the selected task's link to the [complete approval procedure](../../REFERENCES.md#complete-capture-staging). A directly reported decision or experience uses `wiki-capture`; evaluating a separate artifact uses `wiki-promote`.

## Load / Skip

| Task | Open | Also load | Skip |
|---|---|---|---|
| Configure a fresh clone's domain | [`setup.md`](setup.md) | `wiki/domain.md` only | entity pages, raw sources, unrelated workflows |
| Connect GitHub or a private backup destination | [`connect.md`](connect.md) | `export.md` and `scripts/export_wiki.py` help only for backup | entity pages, raw source contents, unrelated workflows |
| Audit root documents or workflow routing for drift | [`audit-docs.md`](audit-docs.md) | named documents and only the live paths needed to verify them | wiki entity pages, raw sources, unrelated workflows |
| Lint the wiki | [`lint.md`](lint.md) | all wiki pages, `wiki/contradictions.md`, `wiki/sourcing-queue.md` | `raw/`, the other task files |
| Rotate `wiki/log.md` when `log_rotation_due` fires | [`rotate-log.md`](rotate-log.md) | `wiki/log.md`, `scripts/rotate_log.py`, `log_rotation_due` lint output | wiki entity pages, raw sources, backlink rebuilds |
| Run the wiki tooling evals | [`eval.md`](eval.md) | `scripts/wiki_eval.py`; failing suite output only if a run fails | wiki entity pages, raw sources, Tier-2/Tier-3 content review |
| Change wiki tooling | [`eval.md`](eval.md) | the relevant [change-impact row](../../REFERENCES.md#tooling-change-impact), then its owner and affected callers | unrelated modules, wiki entity pages, raw sources |
| Promote an artifact | [`artifact-promotion.md`](artifact-promotion.md) | artifact, affected pages, bounded `wiki_lookup.py index` results, relevant [page schema](../../wiki/SCHEMA.md) and [cross-reference rules](../../REFERENCES.md#cross-referencing-rules); [approval procedure](../../REFERENCES.md#complete-capture-staging) only when applying | unrelated entity folders, uncited raw sources, implementation code except for diagnosis or tooling edits |
| Capture a decision or experience | [`capture.md`](capture.md) | `wiki/SCHEMA.md`, bounded `python3 scripts/wiki_lookup.py index --query "<topic>"` results, affected or related entity pages | raw sources, unrelated entity folders, other task files |
| Refresh the sourcing queue | [`refresh-sourcing-queue.md`](refresh-sourcing-queue.md) | `wiki/sourcing-queue.md`, `python3 scripts/wiki_lookup.py log --count 10` output | the full wiki, entity pages, raw sources |
| Synthesize the corpus | [`synthesize.md`](synthesize.md) | `wiki/synthesis.md` first, full `scripts/lint.py` output, bounded `wiki_lookup.py log` pages back to the last synthesis entry, bounded `python3 scripts/wiki_lookup.py index --query "<topic>"` results, candidate pages only | `raw/`, entity folders the candidates do not touch |
| Review due pages | [`review.md`](review.md) | `python3 scripts/review_due.py` output and due pages only | unrelated entity folders, raw sources |
| Create a complete private backup | [`export.md`](export.md) | nothing else | all wiki pages, raw sources, other task files |

Each task file opens with its own Load / Skip list. Follow it instead of pulling the whole wiki into context.
