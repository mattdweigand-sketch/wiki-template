# <Organization> Wiki

A clonable, agent-readable wiki template for company, project, or personal context, based on the [Karpathy LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Put source documents in `raw/`. Agents turn them into structured, cited, interlinked pages in `wiki/`. Future agents answer from the wiki instead of re-reading the same raw material every time.

---

## Why This Exists

Most AI workflows repeatedly retrieve and reassemble context. Prior organization and interpretation rarely carry forward.

This repo compiles stable, source-backed meaning so future work starts from an organized map instead of cold. Compiled pages are the orientation and reuse layer; current facts still come from their owner or source at runtime, and consequential, contradicted, or stale-sensitive claims return to raw evidence. Compounding means reusing prior organization and interpretation, not eliminating verification.

---

## Getting Started

The deterministic tooling requires Python 3.9 or newer and `ripgrep` (`rg`).

1. Clone the repo.
2. Point an agent at it. Claude Code can start at `CLAUDE.md`; other agents start at `AGENTS.md`.
3. Run [`SETUP.md`](SETUP.md) to configure `wiki/domain.md`.
4. Add source files under `raw/`, then ask the agent to ingest them.
5. Ask questions in plain language.

After setup, agents use `AGENTS.md`, `wiki/domain.md`, and `CONTEXT.md` to route each task into the right workflow.

## Agent Setup Prompt

Copy this into your coding agent to download and configure a local wiki from this template:

```text
Download https://github.com/mattdweigand-sketch/wiki-template locally as a new wiki folder.

Ask me where to put it and what to name the folder. Then clone the repo, enter it, read AGENTS.md, and follow SETUP.md because wiki/domain.md starts as status: unconfigured.

Confirm that python3 is Python 3.9 or newer and that rg is available.

After setup, run the repo checks:
- python3 scripts/wiki_eval.py
- python3 scripts/lint.py --tier1

Report changed files, check results, and any remaining setup choices.
```

The repo has seven common workflow shortcuts. Claude Code and Codex expose them as slash commands; other agents use the same routes through `CONTEXT.md`.

| Command | Use it to |
|---|---|
| `/wiki-ingest` | Turn a raw source into durable wiki pages. |
| `/wiki-capture` | Record first-person context, usually a decision or lived experience. |
| `/wiki-promote` | Route a useful artifact into the wiki, or decide not to save it. |
| `/wiki-lint` | Run deterministic checks, judgment candidates, compiled-page recompile review candidates, and evidence review. |
| `/wiki-eval` | Verify that the wiki tools and guardrails still work. |
| `/wiki-synthesize` | Draft corpus distillations for review and approved promotion. |
| `/wiki-export` | Build a local zip export of the wiki, including raw sources; optionally upload to an explicit `rclone` target. |

Research answers can stay in chat or become durable analyses when they are worth saving.

---

## How It Works

The wiki runs one loop: preserve the evidence, turn it into pages, build durable knowledge on those pages, connect them, then check the result.

1. **Preserve the evidence.** Original files, notes, transcripts, and exported source files live in `raw/`. Once added, they are treated as read-only so later conclusions can always be traced back to the source.
2. **Turn sources into wiki pages.** Each important source gets a page in `wiki/sources/`. Other pages cite those source pages instead of relying on loose files, memory, or uncaptured links.
3. **Build durable knowledge.** Wiki pages capture the configured domain using a governed 24-type catalog and organization, personal, or hybrid setup preset. Pages use a shared schema, citations, and a `confidence` value of `high`, `medium`, `low`, or `contested`, so agents know how far to trust each claim. Writing and naming rules live in operating docs rather than a default entity folder.
4. **Connect related context.** Pages link to each other with `[[wiki-links]]`. Agents choose meaningful outgoing links; the repo can rebuild the incoming `## Referenced by` lists automatically.
5. **Check and protect the corpus.** A layer of automated checks and approval gates guards the result. The next section lists them.

---

## What Keeps It Reliable

The checks and guardrails that protect the corpus:

| Mechanism | Purpose |
|---|---|
| Setup and CI checks | `SETUP.md` configures a clone through a read-only setup plan; GitHub Actions validates repository mechanics on pushes and pull requests. Fresh clones remain intentionally unconfigured. |
| Route-first workflows | Point agents from `AGENTS.md` to `CONTEXT.md` to the right workflow, so they read the instructions that match the task. |
| Sourcing queue | `wiki/sourcing-queue.md` tracks evidence gaps so weak claims become future work instead of disappearing. |
| Contradiction tracking | Records conflicts in `wiki/contradictions.md` instead of overwriting inconvenient claims. |
| Three-tier lint | `scripts/lint.py` reports two deterministic tiers: Tier 1 fails on broken structure and malformed proof; Tier 2 ranks suspicious patterns for review, including compiled pages with newer source inputs, glossary status language, and pages likely needing authority metadata. Tier 3, genuine judgment, is left to the `/wiki-lint` prose workflow, not the script. |
| Evidence review | Full `/wiki-lint` adds sampled citation checks so claims are tested against their cited source pages and raw evidence. |
| Lint adjudications | `scripts/lint-adjudications.json` records reviewed false positives and accepted exceptions so the same candidates are not re-litigated every lint run. |
| Approval gate and ledger | `scripts/capture_gate.py` makes the agent ask before filing analyses, applying artifact promotions, or approving synthesis; `scripts/capture-runs.jsonl` records what was approved afterward. |
| Durable file updates | Approval-ledger writes use a stable sidecar lock and atomic replacement; backlink rebuilds and log rotations use recoverable multi-file transactions that fail closed when interrupted or conflicted. |
| Generated wrappers | `scripts/wiki-wrapper-contract.json` is the single manifest for both `.claude/commands/` and `.codex/skills/`; the renderer and parity checker prevent hand-edited drift. |
| Live evals | `/wiki-eval` runs `scripts/wiki_eval.py` to test shared parsing, durable files, recoverable transactions, backlinks, lint fixtures, stale-text sweep proof, the unified approval gate, ledger validation, export, log rotation, review due checks, discoverability, generated wrapper parity, schema-doc parity, and Tier-1 lint over the live corpus. |

Detailed workflow ownership lives in [`REFERENCES.md`](REFERENCES.md); task instructions live under [`workflows/`](workflows/).

---

## Repo Structure

```text
<wiki-root>/
|-- AGENTS.md                  # Canonical operating map for agents
|-- CONTEXT.md                 # Task router
|-- SETUP.md                   # First-session configuration workflow
|-- REFERENCES.md              # Maintainer reference: operating model, layer model, boundaries
|-- CLAUDE.md                  # Thin Claude Code wrapper
|
|-- .claude/commands/          # Claude Code slash-command wrappers
|-- .codex/skills/             # Repo-local Codex skill wrappers
|-- .wiki-transactions/        # Gitignored multi-file recovery authority
|
|-- workflows/                 # Vendor-neutral workflow instructions
|   |-- ingest/                # raw source -> wiki pages
|   |-- research/              # question -> answer
|   `-- maintenance/           # lint, eval, capture, promote, sourcing, synthesize, export
|-- scripts/                   # Deterministic gates, lint, evals, export, link helpers
|-- .github/workflows/         # CI for deterministic wiki checks
|
|-- archive/                   # Tracked rotated wiki logs
|-- raw/                       # Immutable source artifacts
|-- deliverables/              # Gitignored one-off outputs built from wiki content
|-- tmp/                       # Gitignored scratch space
`-- wiki/                      # Maintained knowledge layer
    |-- domain.md              # Context-owner configuration
    |-- SCHEMA.md              # Entity types and page templates
    |-- index.md               # Master catalog
    |-- overview.md            # Big-picture synthesis
    |-- primer.md              # Agent entry points by question type
    |-- glossary.md            # Canonical terminology
    |-- design-notes.md        # Rationale for structural choices
    |-- log.md                 # Chronological activity log
    |-- sourcing-queue.md      # Knowledge gaps
    |-- contradictions.md      # Open and resolved contradictions
    |-- synthesis.md           # Synthesis ledger and run history
    `-- <entity folders>/      # sources, products, people, decisions, analyses, etc.
```

---

## Configuration

A fresh clone starts unconfigured. The setup guide, [`SETUP.md`](SETUP.md), interviews the user for the context owner, domain, organization/personal/hybrid preset, final supported entity-type selection, `raw/` taxonomy, and example questions. `scripts/plan_wiki_setup.py` validates the selection and previews folder changes without writing.

The domain config, [`wiki/domain.md`](wiki/domain.md), records what this wiki is about and which entity types are active. The full schema, [`wiki/SCHEMA.md`](wiki/SCHEMA.md), defines the available page types and page rules.

## Credits

- Pattern by [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
