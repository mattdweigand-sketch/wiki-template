---
title: Index
type: index
created: 2026-05-17
updated: 2026-06-26
---

# Wiki Index

Master catalog of every page in this wiki, grouped by entity type with one-line summaries and confidence ratings.

Use Markdown links to the page path, not bare wikilinks, so `scripts/lint.py --tier1` can verify index coverage. The link target should be the folder-qualified Markdown path, for example: `concepts/page-slug.md`.

Do not put example `.md` links in this file unless the target page exists; lint treats every Markdown link to an entity path in `index.md` as an actual catalog row.

## Core Files

| File | Summary |
|---|---|
| [domain.md](domain.md) | Setup status, configured context, preset, active entity types, raw taxonomy, and example queries |
| [overview.md](overview.md) | Big-picture narrative for the configured context or domain |
| [glossary.md](glossary.md) | Canonical definitions of terms used in this wiki |
| [primer.md](primer.md) | Entry points by question type for downstream agents |
| [SCHEMA.md](SCHEMA.md) | Entity types, frontmatter contract, source-type templates, and confidence values |
| [design-notes.md](design-notes.md) | Design rationale for the wiki structure and maintenance rules |
| [log.md](log.md) | Append-only record of wiki actions |
| [sourcing-queue.md](sourcing-queue.md) | Knowledge gaps and sources needed to resolve them |
| [contradictions.md](contradictions.md) | Open and resolved conflicts between sources |
| [synthesis.md](synthesis.md) | Reviewed synthesis output and synthesis run history |

No entries yet — pages appear here as ingest runs.

See [`primer.md`](primer.md) for routing by question type and [`domain.md`](domain.md) for the wiki's scope.
