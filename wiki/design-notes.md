---
title: Design Notes
type: maintenance
created: 2026-05-17
updated: 2026-08-19
---

# Design Notes

A running record of where this wiki diverges from the [Karpathy LLM-wiki pattern](https://karpathy.ai/zero-to-one/), and why. Useful when revisiting structural decisions later.

## 2026-08-20: One-Time Wiki Initialization

### The Template Becomes the Wiki

A fresh clone carries a disposable initializer. The user supplies basic answers
in `tmp/wiki-setup-answers.json`, previews every planned change, and explicitly
approves one apply command. Apply configures the live tree, archives only the
exact answers and a compact receipt, validates the result, and deletes the
initializer. It leaves ordinary working-tree changes and never commits.

This is intentionally one-way at the product level. A configured wiki has no
setup or reconfiguration command. Git can still restore uncommitted changes or
old commits, but that is repository recovery rather than a supported wiki mode.

Rejected alternatives included a permanent materializer, custom setup
transactions, a path-role registry, migration planners, and automatic commits.
They add a second lifecycle to a repository whose lasting job is only to be a
wiki.

## 2026-08-19: Governed Entity Catalog

### One Catalog Owns the Supported Ontology

Problem: folder/type pairs, authoring guidance, and review
expectations had become duplicated prose that could drift independently.

Chosen seam: `scripts/entity-catalog.json` defines the exact 24 supported
entity records, while `scripts/wiki_entity_catalog.py` is the only production
interface for loading and validating the catalog, looking up folder/type pairs,
and validating configured layouts. Lint, parity, and eval code call that
interface. Setup presets live only in the disposable initializer.

Rejected alternative: let each consumer read the JSON or keep its own lists.
That would make the data file visible without making its meaning authoritative.

Tradeoff: adding or changing an entity type now requires a coordinated catalog,
schema-table, and regression-test update. In return, malformed, duplicated, or
partially documented types fail deterministically.

### Configured Layouts Are Exact

An unconfigured template may hold all 24 empty placeholder folders. A
configured wiki contains exactly the folders mapped from its explicit active
types. The selected interview preset is not permanent configuration. The live
catalog has no presets, migration mode, or reconfiguration behavior.

### Freshness and Verification Stay Authoring Guidance

The catalog describes a default freshness posture and verification expectation
for every type. Goals and decisions receive a Tier-2 signal when `review_by` is
missing. Lint does not infer or insert authority metadata, does not assume every
health, investment, or property claim is current, and does not invent an
"active goal" status model. Authors decide when a page owns live facts and
record authority explicitly.

Rejected alternative: derive authority metadata from the folder. That appears
convenient but converts a prose default into an unsupported factual claim.

### Documentation Graph and Duplicated Tables Are Executable Contracts

`scripts/document-reachability.json` declares operational graph roots,
directories, exclusions, and intentional standalone documents. The checker
follows Markdown links only and treats unreachable workflow documents as
defects. Seven detached legacy guides were removed after their still-useful
research guidance was consolidated into the live route.

The schema parity checker validates every field in the 24-row catalog table and
all three copies of the related-page label vocabulary. Seeded negative fixtures
prove that a missing route, a drifted catalog field, or drift at any label site
fails. The tradeoff is that deliberate duplicated guidance carries explicit
maintenance cost; the parity markers make that cost visible and enforceable.

### Refactor Provenance

The upstream template baseline for this refactor is commit
`65bfdf3d7c11061f1ca038b49b56043e3df9d7ad`. The supporting user-provided
Personal Wiki archive had SHA-256
`3cdbb2b21ff747ef94763af91ce96b60ecb0bfbe475e6fb0944f5c50105c0176`.
Its aggregate evidence was 271 sources, 63 concepts, 24 analyses, 13 people,
11 decisions, 11 properties, 5 learnings, 4 goals, 3 health pages,
3 investments, 2 projects, and 2 skills. Page names and personal content were
not transferred. Because archive identity is not Git identity, the commit above
is called the upstream baseline rather than a claim about an extracted tree's
local `.git` state.

## Starter Decisions

### Raw Artifacts Stay Immutable

Raw source artifacts live in `raw/` and are treated as read-only after placement. The wiki layer interprets sources; it does not rewrite them.

### Source Pages Are the Citation Surface

Entity pages cite `wiki/sources/` pages rather than loose raw files wherever possible. This gives future agents a compact, inspectable source summary before they decide whether to open raw evidence.

### Confidence and Contradictions Are First-Class

Pages carry `confidence:` in frontmatter, and contested claims are recorded in [[contradictions]] before they are overwritten. The goal is traceable uncertainty, not forced consensus.

### Sourcing Gaps Stay Visible

Known missing evidence belongs in [[sourcing-queue]] so weak claims become future work instead of disappearing from the operating context.

### Backlinks Are Generated

Agents author `## Related pages`; `scripts/rebuild_referenced_by.py` owns `## Referenced by`. Generated backlinks are a convenience layer, not source material.

### Volatile State Has One Owner

Moving values such as statuses, dates, targets, prices, rates, and stage labels should live on one owner page. Other pages link the owner with stable pointer language instead of copying values that will drift.

### No Specific App Is Required

The wiki uses plain Markdown, scripts, and vendor-neutral workflows. Claude Code, Codex, Cursor, ChatGPT, or a raw API harness can all operate it by following `AGENTS.md`, `CONTEXT.md`, and `workflows/`.
