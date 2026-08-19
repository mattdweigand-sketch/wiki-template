---
name: wiki-artifact-promotion
description: Use this workflow when a useful output, draft, chat answer, script, prompt, or working artifact should be promoted into durable wiki memory.
---

# Artifact Promotion Workflow

Artifact promotion is a router before it is a write. It turns useful work into the right durable layer of the wiki, or decides not to save it. It is not a new entity type. It handles artifacts that start outside the wiki or inside a temporary answer and may deserve to become source, concept, analysis, decision, initiative, workflow, schema material, an update to an existing page, or nothing at all.

This workflow remains the prose policy for promotion. The executable gate is `scripts/capture_gate.py`, which standardizes the approval preflight for artifact promotion and analysis capture. Use code for the checkable approval boundary; use this workflow for judgment about the right home, page quality, links, and logging.

Promotion has two modes:

- **Audit only** - evaluate the artifact and recommend one primary route. Do not edit files. Use when the user asks whether or how something should be promoted.
- **Apply** - make the chosen wiki update, rebuild backlinks, run Tier-1 lint, and log the promotion. Use when the user explicitly asks to promote, apply, save, file, or update the wiki after the audit.

Collaborative drafting is chat-only by default. Requests like "work with me," "let's discuss," "let's define," "refine this," "talk track," "make this sharper," or "help me think through" are not promotion intent, even when the topic already has a wiki page, the repo is the current working directory, or the result might be reusable. Continue the conversation in chat and do not edit files first.

Promotion is user-routed. Run an audit when the user asks whether, how, or where to preserve an artifact. Apply the promotion only when they explicitly ask to promote, apply, save, file, or update it. Ordinary ingest, question answering, and routine maintenance work do not end with an automatic promotion audit.

Before applying any promotion or filing any analysis capture, run `python3 scripts/capture_gate.py` with the proposed artifact, phase, primary home, touched pages, and analysis criteria or promotion triggers. Ordinary ingest, decision capture, experience capture, workflow updates, setup updates, and routine page updates do not require this approval gate unless they are part of an artifact-promotion or analysis-capture route. If it prints `APPROVAL REQUIRED`, show the full block and do not edit files until the user approves the displayed durable action, primary destination, and allowed file scope. Re-run with `--approved` only after that approval, then run `python3 scripts/validate_capture_runs.py`.

The executable preflight contract is:

```bash
python3 scripts/capture_gate.py \
  --artifact "<what is being evaluated>" \
  --phase drafting|accepted|source|decision|experience|workflow \
  --primary-home "<path or none>" \
  --pages-touched "<comma-separated paths>" \
  [--source-path "<raw path or URL>"] \
  [--path "tmp/<draft>.md"] \
  [--synthesized-pages <count>] \
  [--word-count <count>] \
  [--domain-context yes|no] \
  [--trigger reusable_distinction|ranking_or_framework|open_question_resolution|future_agent_behavior|existing_page_update]
```

The script prints the derived mode: `chat-only`, `analysis-capture`, `promotion-audit`, or `non-approval (phase <phase>)`. An apply route, meaning filing an analysis or promoting an artifact, uses `--phase accepted`: that phase derives `analysis-capture` or `promotion-audit` and triggers the approval gate, while `--phase drafting` and the other phases derive non-approval routes that exit 0 without requiring approval, so never use them for an apply. It can also print `CAPTURE GATE: BLOCKED` and exit non-zero when required inputs are missing; fix the invocation and re-run. For `analysis-capture`, stage the draft in `tmp/` and pass `--path`; the gate measures `word_count` from that file instead of trusting a declared count. The gate also refuses free routes that target `wiki/analyses/`, and rejects placeholder (`<...>`) or out-of-root destinations for approval-required routes, so an approval always names a concrete in-scope home. The script's `promotion-audit` mode means "promotion apply preflight" when a trigger and durable-write intent are present; audit-only prose recommendations do not run the gate and do not edit files. Approval is required only for the derived `analysis-capture` and `promotion-audit` routes unless re-run with `--approved` after the user approves the displayed durable action, primary destination, and allowed file scope. Approved reruns append or confirm an idempotent structured record in `scripts/capture-runs.jsonl`; validate it with `python3 scripts/validate_capture_runs.py`.

Collaborative drafting is chat-only by default. Requests like "work with me," "let's discuss," "let's define," "refine this," "make this sharper," or "help me think through" are not promotion intent, even when the topic already has a wiki page, the repo is the current working directory, or the result might be reusable. If the draft becomes clearly durable, ask whether to save it; do not edit files first.

## Load / Skip

- **Load:** the artifact to evaluate, `wiki/SCHEMA.md`, `wiki/index.md`, and only the pages the artifact directly touches.
- **Load when changing workflow behavior:** `AGENTS.md`, root `CONTEXT.md`, `REFERENCES.md`, and the relevant `workflows/` file.
- **Skip:** unrelated entity folders, raw sources not cited by the artifact, and broad lint unless a contradiction or broken link appears.

## Promotion Ladder

| Layer | Put it here | Use when | Example |
|---|---|---|---|
| Discard | no file | Useful only in the moment | A one-off explanation |
| Raw source | `raw/` | User provides a source artifact to preserve | Transcript, email, PDF, note |
| Source page | `wiki/sources/` | The artifact is evidence from an external or internal source | Summary of a transcript |
| Concept | `wiki/concepts/` | The artifact names a reusable idea or model | Artifact promotion |
| Analysis | `wiki/analyses/` | The artifact synthesizes multiple pages or answers a durable question | Competitive comparison |
| Decision | `wiki/decisions/` | The artifact records a choice and rationale | Adopt typed relationship labels |
| Domain entity update | `wiki/<active-folder>/` | The artifact changes or justifies an entity in the configured active catalog | Goal update, project brief, partner record, system note |
| Operating style rule | `AGENTS.md`, `REFERENCES.md`, or `workflows/` | The artifact governs writing or naming style for future agents | Naming pattern |
| Operating rule | `AGENTS.md`, `CONTEXT.md`, `REFERENCES.md`, or `workflows/` | The artifact should change how future agents behave | New maintenance workflow |
| Script | `scripts/` | The artifact is deterministic and repeatable | Link rebuild, lint check |

## Promotion Tests

Promote an artifact only when at least one is true:

1. It will likely be reused by a future agent.
2. It captures a decision, rule, or distinction that would otherwise be re-litigated.
3. It synthesizes 3 or more pages into a useful answer.
4. It changes how the wiki should be maintained.
5. It preserves source-grounded facts that should not be lost.
6. It defines deterministic behavior that can be tested.

Do not promote when all are true:

1. It is only a conversational clarification.
2. It has no durable source, decision, operating, or test value.
3. It duplicates an existing page without a meaningful update.
4. It would create a new category just to hold one artifact.

## Calibration Examples

### Good

- Update an existing owner page when the artifact sharpens a concept already represented in the wiki.
- Promote a chat insight into an operating rule only when future agents should behave differently.
- When changing an operating rule, record why, one rejected alternative, and the accepted tradeoff in the log or a decision page.

### Bad

- Create a new page for a useful phrase that fits cleanly inside an existing concept, initiative, decision, workflow, or analysis page.
- Treat `/wiki-promote` as permission to save everything.
- Add a new folder or entity type to hold one artifact.

## Routing Spec

Use this decision order:

1. **Is the user still drafting?** If yes, stay in chat. Do not audit or edit.
2. **Is it a source?** If yes, use ingest, not this workflow.
3. **Does it meet research analysis-capture criteria?** It must synthesize 3+ wiki pages, run over 300 measured words in a staged draft, and answer a durable domain-context question. If yes, route to `wiki/analyses/<slug>.md` through the research workflow's analysis filing step.
4. **Is it already covered by an existing page?** If yes, update that page instead of creating a duplicate.
5. **Is it a durable answer or synthesis that does not meet analysis capture?** If yes, audit before deciding whether to update an existing analysis or keep it chat-only.
6. **Is it a reusable model?** If yes, create or update `wiki/concepts/<slug>.md`.
7. **Is it a decision?** If yes, create or update `wiki/decisions/<slug>.md`.
8. **Does it change or justify a domain entity?** If yes, update or create the relevant page under a folder listed in `wiki/domain.md` `entity_types_active`.
9. **Is it an operating instruction for future agents?** If yes, update `AGENTS.md`, root `CONTEXT.md`, `REFERENCES.md`, or the relevant `workflows/` file.
10. **Is it deterministic repeatable logic?** If yes, propose or add a script under `scripts/`.
11. **If none apply, discard it and log only if the user asked for a durable check.**

## Route Outcomes

Use these route labels in audit output and log entries:

| Route | Use when | Workflow to follow |
|---|---|---|
| `discard` | The artifact has no durable source, decision, operating, or reuse value | Stop after audit |
| `ingest` | The artifact is a source that should be preserved before synthesis | `workflows/ingest/CONTEXT.md` |
| `analysis-capture` | The artifact is a substantial synthesis meeting the analysis criteria | `workflows/research/CONTEXT.md` analysis filing step |
| `update-existing-page` | A current wiki page already owns the idea or facts | This workflow plus the target page's schema |
| `create-page` | No current page owns the durable concept, analysis, or similar artifact | This workflow plus `wiki/SCHEMA.md` |
| `capture` | The artifact records a choice, rationale, observation, or lived context | `workflows/maintenance/capture.md` |
| `workflow-update` | The artifact changes how future agents should behave | Update `AGENTS.md`, `CONTEXT.md`, `REFERENCES.md`, or `workflows/` |
| `script` | The artifact is deterministic repeatable logic | Add or update `scripts/` with tests when appropriate |

If `/wiki-promote` routes into another workflow, keep the route decision in the promotion audit and then follow that workflow's Load / Skip list. Do not keep both workflows fully loaded after routing; switch to the selected workflow.

## Audit-Only Output

When the user asks whether, how, or where to promote an artifact, answer with a promotion audit before editing:

```text
Artifact: <what is being evaluated>
Route: discard | ingest | analysis-capture | update-existing-page | create-page | capture | workflow-update | script
Recommendation: <one sentence action>
Primary home: <path or "none">
Reason: <which promotion test it passes or fails>
Pages touched if applied: <short list>
Do not promote because: <only if discarded>
```

If the best route is to update an existing page, name the exact section or kind of change. If the artifact is already covered with no meaningful new distinction, recommend discard or no-op instead of creating a duplicate. Stop after the audit unless the user has already asked to apply the promotion.

## Page Requirements

When creating a wiki page:

1. Use `wiki/SCHEMA.md` frontmatter.
2. Add `agent_use_cases` unless the page type is exempt.
3. Include a one-line summary.
4. Cite source pages with `(source: [[page]])` when stating specific facts.
5. Use `## Related pages` with typed relationship labels when clear.
6. Update `wiki/index.md`.
7. Run `python3 scripts/rebuild_referenced_by.py`. The rebuild applies one recoverable generation; preserve and diagnose any reported transaction conflict instead of deleting `.wiki-transactions/`.

When updating operating docs:

1. Keep the canonical rule in `AGENTS.md`, root `CONTEXT.md`, `REFERENCES.md`, or `workflows/`.
2. Avoid putting canonical behavior only in tool-specific wrappers.
3. Keep the rule short enough for future agents to follow.
4. Update route tables if the new workflow must be discoverable.
5. For new or changed operating rules, record the reason, one rejected alternative, and the accepted tradeoff in `wiki/log.md` or a decision page. Do this going forward; do not backfill old rules unless the user asks.
6. If the new rule is stable and objectively checkable from files, arguments, structured data, or command output, prefer moving it into lint, gate validation, pre-commit, or eval coverage. Keep prose as the explanation, not the enforcement. Do not encode taste or one-off preferences as hard checks.
7. If the change comes from repeated workflow friction, simplify before warning. Prefer deleting duplication, narrowing the rule, moving detail into the routed workflow, or replacing vague wording with a concrete boundary. Add a warning only when the risk is high-blast-radius and cannot be enforced mechanically.

## Workflow Steps

1. Identify the artifact and candidate promotion path in one sentence.
2. Search `wiki/index.md` and relevant folders for existing pages.
3. Choose one primary home from the promotion ladder.
4. If the user asked for audit only, return the audit output and stop.
5. Run `python3 scripts/capture_gate.py --phase accepted` for the proposed apply route (`accepted` derives the approval-requiring `analysis-capture` and `promotion-audit` routes; other phases derive non-approval routes and must not be used for an apply). If it requires approval, show the exact output and stop. Continue only after approval, re-run with `--approved`, and run `python3 scripts/validate_capture_runs.py`.
6. Update the existing page or create the new page, workflow file, or script.
7. Add or update meaningful `[[wikilinks]]`.
8. Update `wiki/index.md` for new or materially changed wiki pages.
9. Run:

   ```bash
   python3 scripts/rebuild_referenced_by.py
   python3 scripts/lint.py --tier1
   ```

   The rebuild plans from one authored-page snapshot and applies one recoverable generation. If it reports a conflict or corrupt transaction, preserve the recovery authority and diagnose the named transaction before continuing.

10. Append to `wiki/log.md`:

   ```text
   ## [YYYY-MM-DD] promotion | <artifact summary>
   Artifact: <chat answer/source/draft/script/etc.>
   Promoted to: <path or discarded>
   Reason: <reuse value>
   Pages updated: ...
   Verification: ...
   ```

## Acceptance Checklist

- [ ] A future agent can find the promoted artifact from `wiki/index.md`, root `CONTEXT.md`, or `workflows/maintenance/CONTEXT.md`.
- [ ] The artifact has one primary home.
- [ ] Related pages link to it where the relationship is meaningful.
- [ ] No raw file was modified.
- [ ] The change avoids a new entity type unless the user approved one.
- [ ] `python3 scripts/lint.py --tier1` passes.
