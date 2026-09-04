---
title: Primer for Downstream Agents
type: primer
created: 2026-05-17
updated: 2026-09-03
---

# Primer

Routing into the wiki by question type. When an agent gets a question, this page maps the question shape to the right entry points.

## How the Wiki Is Organized

| Layer | What it holds |
|---|---|
| Core files | Domain declaration, schema, index, glossary, log, sourcing queue, contradictions, and synthesis |
| Entity folders | One folder per governed knowledge type in [`SCHEMA.md`](SCHEMA.md); unused folders may stay empty |
| Raw sources | Immutable source artifacts under `raw/`, organized by the registered raw buckets |

## Question Routing

| Question type | Start with |
|---|---|
| "What is <entity>?" | `wiki/<entity-type>/<slug>.md` directly, or [`index.md`](index.md) if the slug is unknown |
| "How does X compare to Y?" | Both entity pages; then check [`analyses/`](analyses/) for an existing comparison |
| "What's our position on X?" | [`decisions/`](decisions/), then [`index.md`](index.md) for a related active goal, project, or initiative type |
| "Who is involved?" | [`people/`](people/), then [`index.md`](index.md) for any active team, customer, persona, or partner type |
| "What does <term> mean here?" | [`glossary.md`](glossary.md) |

Add domain-specific routing rows below as the wiki grows.

## Agent Instructions

If you are a downstream agent reading this wiki:

1. Read [`domain.md`](domain.md) first for the wiki's subject, scope, and example questions.
2. Use `python3 scripts/wiki_lookup.py index --query "<topic>"` for bounded matches from [`index.md`](index.md); paginate with `--offset`. With no query it returns section locations.
3. Use [`glossary.md`](glossary.md) to resolve ambiguous terms before assuming meaning.
4. Use `[[double-bracket]]` links inside authored page bodies and `## Related pages`.
5. If a page's `confidence` is `low` or `contested`, check [`contradictions.md`](contradictions.md) and cited sources before relying on it.
6. Do not edit existing files in `raw/`. During ingest, newly provided sources may be placed once under the correct `raw/` subfolder, then treated as immutable.
7. Do not create durable derived conclusions unless the user explicitly requested a write route such as ingest, capture, promotion, synthesis, or workflow maintenance, or approves the destination.
