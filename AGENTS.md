# <Organization> Wiki

A clonable, agent-readable wiki template for an organization's durable context layer. Grounded in sources. Structured for downstream agents. Designed to compound instead of re-deriving context from raw documents.

`AGENTS.md` is canonical and agent-agnostic. Codex, Cursor, Claude, ChatGPT, or a raw API harness should drive this wiki the same way: read `AGENTS.md`, check `wiki/domain.md` for setup status, route through `CONTEXT.md`, then follow the vendor-neutral prose in `workflows/`. Claude Code reaches the same guidance through the thin `CLAUDE.md` wrapper and tracked `.claude/commands/`. Codex reaches the same guidance through tracked repo-local `.codex/skills/` wrappers. Nothing about core operation depends on `.claude/` or `.codex/`.

Start by reading `wiki/domain.md` only far enough to check `status:`. If `status: unconfigured`, route to `SETUP.md` before doing wiki work. If `status: configured`, continue through `CONTEXT.md`.

---

## Directory Structure

- `AGENTS.md` - canonical operating map (this file). `CLAUDE.md` is a thin wrapper that imports it.
- `CONTEXT.md` - task router; read after this file to find the right workflow.
- `SETUP.md` - first-session configuration workflow for a fresh clone.
- `REFERENCES.md` - stable operating model, cross-reference rules, key files, and load-layer guidance.
- `.github/workflows/` - GitHub Actions CI for deterministic wiki checks.
- `workflows/` - vendor-neutral prose workflows grouped into three workspaces, each with a `CONTEXT.md` entry point: `ingest/` (raw -> pages), `research/` (question -> answer), and `maintenance/` (hygiene, audits, tooling, capture, synthesis, review, and export). Single-task workspaces hold their workflow in `CONTEXT.md`; `maintenance/CONTEXT.md` is the task router for maintenance jobs.
- `.claude/commands/` - tracked Claude Code slash-command wrappers for the default wrapped workflows: `wiki-ingest`, `wiki-capture`, `wiki-lint`, `wiki-eval`, `wiki-promote`, `wiki-synthesize`, and `wiki-export`. Both wrapper surfaces are deterministic renders of `scripts/wiki-wrapper-contract.json`; canonical behavior lives in `workflows/` and is routed through `CONTEXT.md`.
- `.codex/skills/` - tracked repo-local Codex skill wrappers for the same seven wiki shortcuts. Current Codex discovers this directory while working in the repo. Generate both surfaces with `python3 scripts/render_wiki_wrappers.py --render`; `python3 scripts/check_wrapper_parity.py` verifies exact rendered parity.
- `scripts/` - vendor-neutral deterministic tooling, self-contained. CLI files are thin entry points over concept-owned modules: `capture_gate.py` composes `capture_approval_policy.py` and `capture_approval_records.py`; `lint.py` composes the `wiki_lint_*` contract, parsing, repository, page-check, adjudication, and signal layers; `_file_transactions.py` is the stable execution facade over `_transaction_contract.py`. Approved ledger writes use a stable sidecar lock and atomic full-file replacement; `capture-runs.jsonl` is the single structured approval ledger written only by approved capture-gate reruns; `validate_capture_runs.py` checks that ledger's schema and approval scope; `wiki-wrapper-contract.json` and `render_wiki_wrappers.py` own the generated wrapper surfaces; `raw-buckets.json` is the tracked raw taxonomy source; `hooks/pre-commit` blocks committed raw artifacts except `raw/.gitkeep` and `raw/README.md`; `export_wiki.py` builds and verifies complete corpus export zips; `rebuild_referenced_by.py` regenerates `## Referenced by` inbound-link sections; `rotate_log.py` archives oversized `wiki/log.md` ranges under `archive/wiki-log/`; `stale_text_sweep.py` emits read-only stale-text sweep proof for ingest logs; `lint.py --tier1` is the deterministic validation gate; `wiki_eval.py` runs the live guard suites; `check_discoverability.py` enforces typed, distinctive production functions and explicitly exported class constructors; `check_wrapper_parity.py` verifies wrapper manifests and exact renders; `check_schema_doc_parity.py` verifies duplicated schema vocabulary docs match `wiki_lint_contract.py` constants.
- `.wiki-transactions/` - gitignored recovery authority for multi-file backlink rebuilds and log rotations. It is not scratch: never empty or delete it to clear lint, a commit, or an export. Inspect with `python3 scripts/wiki_transactions.py status`, recover an interrupted clean transaction with `python3 scripts/wiki_transactions.py recover`, and diagnose preserved conflicts or corruption by transaction ID. Tier 1, pre-commit, and export fail closed while the authority is nonclean.
- `scripts/fixtures/` - eval mini-wikis for live tooling: `wiki-rebuild` guards link-graph invariants and `wiki-lint` proves lint checks can fire.
- `scripts/lint-adjudications.json` - settled Tier-2 lint judgments with reasons and dates, so lint stops re-surfacing what has been adjudicated.
- `tmp/` - gitignored scratch space. Everything in it is disposable at all times.
- `deliverables/` - optional gitignored one-off outputs built from wiki content. Contents are not wiki content. Keep outputs inside clearly labeled kebab-case subfolders; do not leave loose files directly under `deliverables/`.
- `raw/` - source artifacts. Existing files are immutable, and new user-provided sources may be placed once during ingest before becoming immutable.
- `wiki/` - knowledge layer: `domain.md`, `index.md`, `overview.md`, `glossary.md`, `primer.md`, `log.md`, `SCHEMA.md`, `sourcing-queue.md`, `contradictions.md`, `design-notes.md`, `synthesis.md`, and entity folders.
- `wiki/<entity-type>/` - one folder per active entity type.

<!-- parity:enum key=entity-folders -->
**Default entity folders:** sources, products, features, personas, customers, competitors, concepts, initiatives, decisions, metrics, people, analyses

Create new entity types only during setup or after an explicit schema decision.

---

## Routing

Routing lives in `CONTEXT.md`, the source of truth for which workflow handles which task. Read it after this file, find the task, and open the workflow file it points to. Each workflow opens with its own Load / Skip list.

Routine command surface only: `/wiki-ingest`, `/wiki-capture`, `/wiki-lint`, `/wiki-eval`, `/wiki-promote`, `/wiki-synthesize`, and `/wiki-export`. These commands are shortcuts; canonical behavior stays in `CONTEXT.md`, `workflows/`, `scripts/`, and `wiki/SCHEMA.md`. Claude Code reads `.claude/commands/` in the repo. Codex reads tracked repo-local skills under `.codex/skills/`; duplicate global `wiki-*` skills are local runtime noise, not source of truth.

## Capture Approval Gate

Run `python3 scripts/capture_gate.py` before exactly three approval boundaries: filing a research answer as `wiki/analyses/`, applying an artifact promotion, and promoting reviewed synthesis output with `--kind=synthesis`. Every other route skips the gate, including ordinary source ingest, routine page updates, decision capture, experience capture, workflow updates, and setup updates, unless the work is part of one of those approval boundaries.

If the script prints `APPROVAL REQUIRED`, show the full block and stop until the user approves the displayed durable action, primary destination, and allowed file scope. Plain-language approval such as "approve" or "yes" is enough when it clearly approves the displayed action, destination, and file scope. Re-run with `--approved` only after that approval.

The script owns the checkable approval boundary and verifies the parts prose should not hand-wave: analysis capture must point `--path` at a real draft so the gate can count its words, a free route may not target `wiki/analyses/`, and approval-required routes reject placeholder (`<...>`) or out-of-root destinations. The prose workflows own judgment about what to write, how to cite it, where to link it, and how to log it.

The approved rerun writes or confirms the idempotent structured approval record in `scripts/capture-runs.jsonl`. The non-approved gate call is display-only: it must not update `wiki/analyses/`, promoted pages, `scripts/capture-runs.jsonl`, or `wiki/log.md`.

## Synthesis Approval Gate

Run `python3 scripts/capture_gate.py --kind=synthesis` before promoting synthesis output: updating `wiki/synthesis.md`, flipping draft confidence/status because the user reviewed a synthesis draft, or logging a synthesis promotion. The gate must display the draft being approved, primary destination, and full editable file scope. If it prints `APPROVAL REQUIRED`, show the approval request and stop. Re-run with `--approved` only after the user clearly approves the displayed synthesis draft and file scope.

The approved rerun writes or confirms the idempotent structured approval record in `scripts/capture-runs.jsonl`. The non-approved gate call is display-only: it must not update `wiki/synthesis.md`, `scripts/capture-runs.jsonl`, draft confidence/status, or `wiki/log.md`.

## Session Start

1. Read this file.
2. Read `wiki/domain.md` only far enough to check `status:`.
3. If `status: unconfigured`, open `SETUP.md` and follow it.
4. If `status: configured`, read `CONTEXT.md` to route the task.
5. Open the routed workspace `CONTEXT.md`, then the task file it names when applicable.
6. Follow that workflow's Load / Skip list.
7. Load `REFERENCES.md`, `wiki/index.md`, `wiki/log.md`, and other wiki files only when the routed workflow asks for them.
8. If no task was provided, ask what to do after reading this file, `wiki/domain.md`, and `CONTEXT.md`.

---

## Naming Conventions

All filenames are kebab-case, lowercase, no extension prefix, no date prefix. Chronology lives in `wiki/log.md`.

Repo structure is linted. `scripts/lint.py --tier1` fails on unknown repo-root entries, unknown `wiki/` root entries, unknown top-level `raw/` buckets after setup, loose top-level `raw/` or `deliverables/` files, non-kebab-case `deliverables/` subfolders, and Finder `.DS_Store` metadata outside `.git`. Fix those as structural violations; do not work around them.

| Entity | Pattern | Example |
|---|---|---|
| Source page | kebab-case from source title | `q3-board-deck.md` |
| Person/team page | kebab-case role, team, or name | `enterprise-sales.md` |
| Decision page | kebab-case from decision topic | `pricing-packaging.md` |
| Product / feature / persona / customer / competitor / concept / initiative / metric / analysis | kebab-case from canonical term | `workflow-automation.md` |
| Workspace entry | `workflows/<workspace>/CONTEXT.md` | `workflows/ingest/CONTEXT.md` |
| Maintenance task file | kebab-case verb or noun | `workflows/maintenance/artifact-promotion.md` |

Predictable names let any agent find, organize, and reference files without reading the whole repo.

---

## Cross-Referencing

Use `[[filename-without-extension]]` for all internal links. Two link sections have different ownership:

- `## Related pages` - curated outbound links written by hand. Pick meaningful links. When the relationship is clear, prefix the link with a typed relationship label:
  - `Supports: [[page]]` - this page strengthens, evidences, or confirms the linked page
  - `Contradicts: [[page]]` - this page conflicts with or materially challenges the linked page
  - `Depends on: [[page]]` - this page requires the linked page to be understood or true
  - `Derived from: [[page]]` - this page was created from, generalized from, or synthesized out of the linked page
  - `Part of: [[page]]` - this page is a component of the linked larger system, project, or framework
  - `Related: [[page]]` - meaningful connection, but no stronger typed relationship fits
- `## Referenced by` - auto-generated inbound links. Never hand-edit this section. It is rebuilt from one immutable authored-page snapshot by `scripts/rebuild_referenced_by.py`, which applies all changed pages as one recoverable transaction.

The script is an optional convenience: if it is never run, `## Related pages` still works and the wiki stays operable. It just means inbound links will not auto-refresh.

## Terminology

New terms go in `wiki/glossary.md`. Conflicts get flagged explicitly. Always use the canonical glossary term once it exists.

## Hard Rules

- Do not edit existing files in `raw/`.
- Flag contradictions before updating; never silently overwrite contested claims.
- Prefer updating existing pages over creating new ones.
- Write for AI agents first: structured, dense, cited.
- Keep tool-specific wrappers thin; canonical behavior belongs in `AGENTS.md`, `CONTEXT.md`, `REFERENCES.md`, `workflows/`, `scripts/`, and `wiki/SCHEMA.md`.
