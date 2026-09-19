---
name: wiki-maintenance
description: Router for initial domain setup, optional repository and backup connection, wiki hygiene, tooling evals, artifact promotion, first-person capture, corpus synthesis, and export. Open the one task file you need.
---

# Maintenance Workspace

Initial domain setup, optional repository and backup connection, wiki hygiene, tooling evals, artifact promotion, capture, corpus synthesis, and export. Load this router, then open only the one task file the work calls for. Do not pull every task file into context. `wiki-setup` and `wiki-capture` are shortcuts for tasks in this workspace, not separate workflows.

Invoking `wiki-lint` through either agent wrapper authorizes the full lint workflow, including its verifier-agent evidence check, unless the user asks for deterministic-only lint, no subagents, or skipping the evidence check.

Wrapper-surface maintenance is tooling eval work. If the task concerns `.claude/commands/`, `.agents/skills/`, or `scripts/check_wrapper_parity.py`, open [`eval.md`](eval.md).

Follow the [approval boundaries](../../AGENTS.md#exact-approval-boundary) and the selected task's link to the [complete approval procedure](../../REFERENCES.md#complete-capture-staging). A directly reported decision or experience uses `wiki-capture`; evaluating a separate artifact uses `wiki-promote`.

## Tasks

| Task | Open |
|---|---|
| Configure a fresh clone's domain | [`setup.md`](setup.md) |
| Connect GitHub or a private backup destination | [`connect.md`](connect.md) |
| Audit root documents or workflow routing for drift | [`audit-docs.md`](audit-docs.md) |
| Lint the wiki | [`lint.md`](lint.md) |
| Rotate `wiki/log.md` when `log_rotation_due` fires | [`rotate-log.md`](rotate-log.md) |
| Run the wiki tooling evals | [`eval.md`](eval.md) |
| Change wiki tooling | [`eval.md`](eval.md) |
| Promote an artifact | [`artifact-promotion.md`](artifact-promotion.md) |
| Capture a decision or experience | [`capture.md`](capture.md) |
| Refresh the sourcing queue | [`refresh-sourcing-queue.md`](refresh-sourcing-queue.md) |
| Synthesize the corpus | [`synthesize.md`](synthesize.md) |
| Review due pages | [`review.md`](review.md) |
| Create a complete private backup | [`export.md`](export.md) |

Each task file owns its inputs, Load / Skip list, steps, and finish. Open that file before loading task inputs.
