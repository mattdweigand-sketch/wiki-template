---
name: wiki-maintenance
description: Router for initial domain setup, wiki hygiene, tooling evals, artifact promotion, first-person capture, corpus synthesis, and export. Open the one task file you need.
---

# Maintenance Workspace

Initial domain setup, wiki hygiene, tooling evals, artifact promotion, capture, corpus synthesis, and export. Load this router, then open only the one task file the work calls for. Do not pull every task file into context. `wiki-setup` and `wiki-capture` are shortcuts for tasks in this workspace, not separate workflows.

Invoking `wiki-lint` through either agent wrapper authorizes the full lint workflow, including its verifier-agent evidence check, unless the user asks for deterministic-only lint, no subagents, or skipping the evidence check.

Wrapper-surface maintenance is tooling eval work. If the task concerns `.claude/commands/`, `.agents/skills/`, or `scripts/check_wrapper_parity.py`, open [`eval.md`](eval.md).

Artifact promotion uses the exact capture proposal flow in `AGENTS.md`. Preview every staged target, stop for approval of the displayed digest, and apply only that digest. Decision capture, experience capture, workflow updates, domain customization, and routine page updates skip this gate unless they are part of promotion or analysis capture. If the user directly says they made a decision or lived through something they want remembered, use `wiki-capture`; use `wiki-promote` only when evaluating a separate artifact.

Synthesis promotion uses the same flow with `capture_boundary: synthesis-promotion` before updating `wiki/synthesis.md`, flipping draft confidence/status, or logging a synthesis promotion.

## Load / Skip

| Task | Open | Also load | Skip |
|---|---|---|---|
| Configure a fresh clone's domain | [`setup.md`](setup.md) | `wiki/domain.md` only | entity pages, raw sources, unrelated workflows |
| Audit root documents or workflow routing for drift | [`audit-docs.md`](audit-docs.md) | named documents and only the live paths needed to verify them | wiki entity pages, raw sources, unrelated workflows |
| Lint the wiki | [`lint.md`](lint.md) | all wiki pages, `wiki/contradictions.md`, `wiki/sourcing-queue.md` | `raw/`, the other task files |
| Rotate `wiki/log.md` when `log_rotation_due` fires | [`rotate-log.md`](rotate-log.md) | `wiki/log.md`, `scripts/rotate_log.py`, `log_rotation_due` lint output | wiki entity pages, raw sources, backlink rebuilds |
| Run the wiki tooling evals | [`eval.md`](eval.md) | `scripts/wiki_eval.py`; failing suite output only if a run fails | wiki entity pages, raw sources, Tier-2/Tier-3 content review |
| Promote an artifact | [`artifact-promotion.md`](artifact-promotion.md) | `wiki/SCHEMA.md`, `REFERENCES.md` (cross-referencing rules), `wiki/index.md`, `scripts/capture_gate.py`, artifact being evaluated | unrelated entity folders, raw sources not cited by the artifact |
| Capture a decision or experience | [`capture.md`](capture.md) | `wiki/SCHEMA.md`, `wiki/index.md`, affected or related entity pages | raw sources, unrelated entity folders, other task files |
| Refresh the sourcing queue | [`refresh-sourcing-queue.md`](refresh-sourcing-queue.md) | `wiki/sourcing-queue.md`, last ~10 `wiki/log.md` entries | the full wiki, entity pages, raw sources |
| Synthesize the corpus | [`synthesize.md`](synthesize.md) | `wiki/synthesis.md` first, full `scripts/lint.py` output, `wiki/log.md` since the last synthesis entry, `wiki/index.md`, candidate pages only | `raw/`, entity folders the candidates do not touch |
| Review due pages | [`review.md`](review.md) | `python3 scripts/review_due.py` output and due pages only | unrelated entity folders, raw sources |
| Create a complete private backup | [`export.md`](export.md) | nothing else | all wiki pages, raw sources, other task files |

Each task file opens with its own Load / Skip list. Follow it instead of pulling the whole wiki into context.
