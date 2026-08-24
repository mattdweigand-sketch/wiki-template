# Wiki

A clonable, agent-readable wiki template for organization, project, or personal context, based on the [Karpathy LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

Put source documents in `raw/`. Agents turn them into structured, cited, interlinked pages in `wiki/`. Future agents answer from the wiki instead of re-reading the same raw material every time.

---

## Why This Exists

Most AI workflows repeatedly retrieve and reassemble context. Prior organization and interpretation rarely carry forward.

This repo compiles stable, source-backed context so future work can reuse prior organization and interpretation. Compiled pages provide orientation. Current facts still come from their owner or source at runtime, and consequential, contradicted, or time-sensitive claims return to raw evidence.

---

## Getting Started

The deterministic tooling requires Python 3.9 or newer and `ripgrep` (`rg`). Backup verification works anywhere those requirements are met. Atomic restore requires macOS or Linux because it uses the operating system's no-replace directory rename.

1. Clone the repo.
2. Point an agent at it. Claude Code can start at `CLAUDE.md`; other agents start at `AGENTS.md`.
3. Replace the placeholders in [`wiki/domain.md`](wiki/domain.md) with the context name, scope, and example questions.
4. Add source files under a bucket registered in [`scripts/raw-buckets.json`](scripts/raw-buckets.json), then ask the agent to ingest them.
5. Ask questions in plain language.

The clone is operational before customization. All supported entity folders and workflows are present, so changing the subject does not require a setup command or structural migration.

## Agent Clone Prompt

Copy this into your coding agent to download a local wiki from this template:

```text
Download https://github.com/mattdweigand-sketch/wiki-template locally as a new wiki folder.

Ask me where to put it and what to name the folder. Then clone the repo, enter it, and read AGENTS.md.

Confirm that python3 is Python 3.9 or newer and that rg is available.

Update only the placeholders in wiki/domain.md with my name, scope, and example questions. Report the changed file and validation results; do not create the commit.
```

The repo has nine workflow shortcuts. Claude Code exposes them as slash commands. Codex exposes them as skills, invoked with `$wiki-*` or selected through `/skills`. Other agents use the same routes through `CONTEXT.md`.

| Workflow | Claude Code | Codex | Use it to |
|---|---|---|---|
| `wiki-ask` | `/wiki-ask` | `$wiki-ask` | Answer ordinary wiki questions from the smallest relevant page set. This is the default. |
| `wiki-research` | `/wiki-research` | `$wiki-research` | Run manually invoked research with claim-level independent review. |
| `wiki-ingest` | `/wiki-ingest` | `$wiki-ingest` | Turn a raw source into durable wiki pages. |
| `wiki-capture` | `/wiki-capture` | `$wiki-capture` | Record first-person context, usually a decision or lived experience. |
| `wiki-promote` | `/wiki-promote` | `$wiki-promote` | Route a useful artifact into the wiki, or decide not to save it. |
| `wiki-lint` | `/wiki-lint` | `$wiki-lint` | Run deterministic checks, judgment candidates, compiled-page recompile review candidates, and evidence review. |
| `wiki-eval` | `/wiki-eval` | `$wiki-eval` | Verify that the wiki tools and guardrails still work. |
| `wiki-synthesize` | `/wiki-synthesize` | `$wiki-synthesize` | Draft corpus distillations for review and approved promotion. |
| `wiki-export` | `/wiki-export` | `$wiki-export` | Build a complete private backup and optionally copy it to an approved private off-device destination. |

Ask answers stay lightweight. Research answers add independent claim review only when `wiki-research` is named. Either can become a durable analysis when worth saving.

---

## How It Works

The wiki runs one loop: preserve the evidence, turn it into pages, build durable knowledge on those pages, connect them, then check the result.

1. **Preserve the evidence.** Original files, notes, transcripts, and exported source files live in `raw/`. Once added, they are read-only. Raw bytes stay local and Git ignores them. Git tracks their exact paths, sizes, hashes, and matching source pages.
2. **Turn sources into wiki pages.** Each important source gets a page in `wiki/sources/`. Other pages cite those source pages instead of relying on loose files, memory, or uncaptured links.
3. **Build durable knowledge.** Wiki pages capture the domain using a governed 24-type catalog. Pages use a shared schema, citations, and a `confidence` value of `high`, `medium`, `low`, or `contested`, so agents know how far to trust each claim. Unused entity folders simply stay empty.
4. **Connect related context.** Pages link to each other with `[[wiki-links]]`. Agents choose meaningful outgoing links; the repo can rebuild the incoming `## Referenced by` lists automatically.
5. **Check and protect the corpus.** A layer of automated checks and approval gates guards the result. The next section lists them.

---

## What Keeps It Reliable

The main checks that protect the corpus:

| Mechanism | Purpose |
|---|---|
| Ready clone and CI | Every supported entity folder and neutral raw bucket ships with the clone. GitHub Actions checks pushes and pull requests. |
| Route-first workflows | Point agents from `AGENTS.md` through `wiki/domain.md`, then to `CONTEXT.md`. |
| Evidence and conflicts | Sources, citations, the sourcing queue, contradiction tracking, and sampled evidence review keep claims tied to evidence. |
| Lint and evals | Tier 1 blocks broken structure. Tier 2 surfaces focused review candidates. `wiki-eval` checks the tools and recovery paths. |
| Exact approval | Analysis capture, artifact promotion, and synthesis promotion bind approval to exact target bytes and apply through one recoverable transaction. |
| Generated wrappers | `scripts/wiki-wrapper-contract.json` owns both agent shortcut surfaces. Render and parity checks block drift. |
| Complete private backup | `wiki-export` includes raw sources, local state, deliverables, scratch files, and Git history. Version 3 binds file and directory modes before absent-destination restore. |

Detailed workflow ownership lives in [`REFERENCES.md`](REFERENCES.md); task instructions live under [`workflows/`](workflows/).

---

## Repo Structure

```text
<wiki-root>/
|-- AGENTS.md                  # Canonical operating map for agents
|-- CONTEXT.md                 # Task router
|-- REFERENCES.md              # Maintainer reference: operating model, layer model, boundaries
|-- CLAUDE.md                  # Thin Claude Code wrapper
|
|-- .claude/commands/          # Claude Code slash-command wrappers
|-- .agents/skills/            # Repo-local Codex skill wrappers
|-- .wiki-transactions/        # Gitignored capture recovery authority
|
|-- workflows/                 # Vendor-neutral workflow instructions
|   |-- ingest/                # raw source -> wiki pages
|   |-- research/              # question -> answer
|   `-- maintenance/           # audit, lint, eval, capture, promote, sourcing, synthesize, review, rotate, export
|-- scripts/                   # Deterministic gates, lint, evals, export, link helpers
|-- .github/workflows/         # CI for deterministic wiki checks
|
|-- archive/                   # Tracked rotated wiki logs
|-- raw/                       # Local-only immutable source artifacts
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

## Customization

A fresh clone is ready to use. Edit [`wiki/domain.md`](wiki/domain.md) to name the context, describe its scope, and list the questions it should answer. All 24 governed entity folders stay available; unused folders may remain empty.

If the raw taxonomy does not fit, update [`scripts/raw-buckets.json`](scripts/raw-buckets.json) and the tracked bucket placeholders together. No executable setup or reconfiguration workflow is required.

The full schema, [`wiki/SCHEMA.md`](wiki/SCHEMA.md), defines the available page types and page rules.

## Credits

- Pattern by [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
