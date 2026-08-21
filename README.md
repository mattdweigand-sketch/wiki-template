<!-- wiki-setup:readme-identity:start -->
# <Organization> Wiki

A clonable, agent-readable wiki template for organization, project, or personal context, based on the [Karpathy LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
<!-- wiki-setup:readme-identity:end -->

Put source documents in `raw/`. Agents turn them into structured, cited, interlinked pages in `wiki/`. Future agents answer from the wiki instead of re-reading the same raw material every time.

---

## Why This Exists

Most AI workflows repeatedly retrieve and reassemble context. Prior organization and interpretation rarely carry forward.

This repo compiles stable, source-backed context so future work can reuse prior organization and interpretation. Compiled pages provide orientation. Current facts still come from their owner or source at runtime, and consequential, contradicted, or time-sensitive claims return to raw evidence.

---

<!-- wiki-setup:readme-getting-started:start -->
## Getting Started

The deterministic tooling requires Python 3.9 or newer and `ripgrep` (`rg`).

1. Clone the repo.
2. Point an agent at it. Claude Code can start at `CLAUDE.md`; other agents start at `AGENTS.md`.
3. Follow [`SETUP.md`](SETUP.md) to preview and approve the one-time initializer.
4. Add source files under `raw/`, then ask the agent to ingest them.
5. Ask questions in plain language.

The finalizer leaves reviewable Git changes, archives the answers and receipt, and removes the initializer. After those changes are committed, agents use `AGENTS.md`, `wiki/domain.md`, and `CONTEXT.md` to route each task.
<!-- wiki-setup:readme-getting-started:end -->

<!-- wiki-setup:readme-agent-setup-prompt:start -->
## Agent Setup Prompt

Copy this into your coding agent to download and configure a local wiki from this template:

```text
Download https://github.com/mattdweigand-sketch/wiki-template locally as a new wiki folder.

Ask me where to put it and what to name the folder. Then clone the repo, enter it, read AGENTS.md, and follow SETUP.md because wiki/domain.md starts as status: unconfigured.

Confirm that python3 is Python 3.9 or newer and that rg is available.

Review the initializer preview with me. Apply it only after I approve the displayed changes. Report the final changed files and validation results; do not create the commit.
```
<!-- wiki-setup:readme-agent-setup-prompt:end -->

The repo has seven common workflow shortcuts. Claude Code exposes them as slash commands. Codex exposes them as skills, invoked with `$wiki-*` or selected through `/skills`. Other agents use the same routes through `CONTEXT.md`.

| Workflow | Claude Code | Codex | Use it to |
|---|---|---|---|
| `wiki-ingest` | `/wiki-ingest` | `$wiki-ingest` | Turn a raw source into durable wiki pages. |
| `wiki-capture` | `/wiki-capture` | `$wiki-capture` | Record first-person context, usually a decision or lived experience. |
| `wiki-promote` | `/wiki-promote` | `$wiki-promote` | Route a useful artifact into the wiki, or decide not to save it. |
| `wiki-lint` | `/wiki-lint` | `$wiki-lint` | Run deterministic checks, judgment candidates, compiled-page recompile review candidates, and evidence review. |
| `wiki-eval` | `/wiki-eval` | `$wiki-eval` | Verify that the wiki tools and guardrails still work. |
| `wiki-synthesize` | `/wiki-synthesize` | `$wiki-synthesize` | Draft corpus distillations for review and approved promotion. |
| `wiki-export` | `/wiki-export` | `$wiki-export` | Build a local zip export of the wiki, including raw sources; optionally upload to an explicit `rclone` target. |

Research answers can stay in chat or become durable analyses when they are worth saving.

---

## How It Works

The wiki runs one loop: preserve the evidence, turn it into pages, build durable knowledge on those pages, connect them, then check the result.

1. **Preserve the evidence.** Original files, notes, transcripts, and exported source files live in `raw/`. Once added, they are treated as read-only so later conclusions can always be traced back to the source. This template assumes a private Git repository whose access is limited to the wiki's intended users. Git tracks raw files with the rest of the wiki, so review sensitive material before pushing them to any remote. <!-- wiki-setup:readme-private-repository:line -->
2. **Turn sources into wiki pages.** All three setup presets include the `source` type. While it remains active, each important source gets a page in `wiki/sources/`. Other pages cite those source pages instead of relying on loose files, memory, or uncaptured links. <!-- wiki-setup:readme-source-pages:line -->
3. **Build durable knowledge.** Wiki pages capture the configured domain using active types from a governed 24-type catalog. Pages use a shared schema, citations, and a `confidence` value of `high`, `medium`, `low`, or `contested`, so agents know how far to trust each claim. Writing and naming rules live in operating docs rather than a default entity folder.
4. **Connect related context.** Pages link to each other with `[[wiki-links]]`. Agents choose meaningful outgoing links; the repo can rebuild the incoming `## Referenced by` lists automatically.
5. **Check and protect the corpus.** A layer of automated checks and approval gates guards the result. The next section lists them.

---

## What Keeps It Reliable

The checks and guardrails that protect the corpus:

| Mechanism | Purpose |
|---|---|
| One-time initialization and CI | `SETUP.md` collects temporary answers, previews exact changes, and applies them once after approval. The initializer then deletes itself. GitHub Actions validates repository mechanics on pushes and pull requests. <!-- wiki-setup:readme-ci-row:line --> |
| Route-first workflows | Point agents from `AGENTS.md` through the `wiki/domain.md` status check, then to `SETUP.md` or `CONTEXT.md` as appropriate. <!-- wiki-setup:readme-route-row:line --> |
| Sourcing queue | `wiki/sourcing-queue.md` tracks evidence gaps so weak claims become future work instead of disappearing. |
| Contradiction tracking | Records conflicts in `wiki/contradictions.md` instead of overwriting inconvenient claims. |
| Three-tier lint | `scripts/lint.py` reports two deterministic tiers: Tier 1 fails on broken structure and malformed proof; Tier 2 ranks suspicious patterns for review, including compiled pages with newer source inputs, glossary status language, pages likely needing authority metadata, and optional current-state owner drift. Tier 3, genuine judgment, is left to the `wiki-lint` prose workflow, not the script. |
| Evidence review | Full `wiki-lint` creates an exact OS-random sample, immutable verifier batches, a hidden calibration plant, and validated verdict accounting so claims are tested against cited pages and raw evidence without trusting partial or stale runs. |
| Lint adjudications | `scripts/lint-adjudications.json` records reviewed false positives and accepted exceptions so the same candidates are not re-litigated every lint run. |
| Approval gate and ledger | `scripts/capture_gate.py` makes the agent ask before filing analyses, applying artifact promotions, or approving synthesis; `scripts/capture-runs.jsonl` records what was approved afterward. |
| Durable file updates | Approval-ledger writes use a stable sidecar lock and atomic replacement; backlink rebuilds and log rotations use recoverable multi-file transactions that fail closed when interrupted or conflicted. |
| Generated wrappers | `scripts/wiki-wrapper-contract.json` is the single manifest for both `.claude/commands/` and `.agents/skills/`; the renderer and parity checker prevent hand-edited drift. |
| Live evals | `wiki-eval` runs the suites registered in `scripts/wiki_eval.py`, including parsing, durable files, transactions, backlinks, lint and evidence checks, approval gates and ledgers, export and backup receipts, log rotation, review dates, discoverability, wrapper parity, entity-catalog and schema contracts, document reachability, and Tier-1 lint. |
| Optional backup receipt | An explicit `rclone` upload advances local backup freshness only after remote size and checksum verification. `scripts/backup_state.py` reports missing, stale, invalid, future-dated, or fresh state without making backup configuration a repository gate. |

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
|-- .agents/skills/            # Repo-local Codex skill wrappers
|-- .wiki-transactions/        # Gitignored multi-file recovery authority
|
|-- workflows/                 # Vendor-neutral workflow instructions
|   |-- ingest/                # raw source -> wiki pages
|   |-- research/              # question -> answer
|   `-- maintenance/           # audit, lint, eval, capture, promote, sourcing, synthesize, review, rotate, export
|-- scripts/                   # Deterministic gates, lint, evals, export, link helpers
|-- .github/workflows/         # CI for deterministic wiki checks
|
|-- archive/                   # Tracked setup provenance and rotated wiki logs
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

<!-- wiki-setup:readme-configuration:start -->
## Configuration

A fresh clone starts unconfigured. [`SETUP.md`](SETUP.md) collects the context owner, domain, starting preset, final supported entity types, raw buckets, example questions, and privacy acknowledgement in a temporary answers file. `scripts/finalize_wiki_setup.py preview` validates the answers and reports every change without writing. Its approved `apply` command configures the wiki, archives only the answers and receipt, removes the initializer, runs validation, and leaves ordinary Git changes for review.

The final active-type list is literal. All presets include `source`, `analysis`, and `decision` so the standard ingest, analysis-capture, and decision-capture routes have destinations. Remove one only when the configured wiki will not use that route.

The domain config, [`wiki/domain.md`](wiki/domain.md), records what this wiki is about and which entity types are active. The full schema, [`wiki/SCHEMA.md`](wiki/SCHEMA.md), defines the available page types and page rules.
<!-- wiki-setup:readme-configuration:end -->

## Credits

- Pattern by [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
