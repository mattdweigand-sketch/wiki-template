---
name: wiki-ask
description: Default lightweight workflow for answering questions from the wiki.
---

# Wiki Ask

Answer from the smallest relevant part of the wiki. This is the default research route.

## Load / Skip

- **Load:** named owner pages when known; otherwise `wiki/primer.md` for entry points by question type, bounded `python3 scripts/wiki_lookup.py index --query "<topic>"` results to locate pages, then only the pages the question touches. When filing an analysis, also load the citation and provenance rules in `wiki/SCHEMA.md`.
- **Skip:** unrelated entity folders, raw sources, evidence-run tooling, and the rest of `wiki/SCHEMA.md`.

## Steps

1. Read a known owner page directly. When discovering pages, start with catalog lookup: use the primer to select the likely entity folder. For unknown slugs, extract a few distinctive keywords from the question, preserving exact IDs and names, and search the catalog with `--folder` when the route is clear. Select the smallest useful set of up to 8 pages. Load more pages only when a link, conflict, or missing fact requires them.
2. If catalog results are empty or the selected pages lack the evidence, use `python3 scripts/wiki_lookup.py content --query "<key terms>" --folder <entity-folder>`. If the results do not supply the evidence, try at most one alternate keyword query using terminology from the primer or retrieved pages. Preserve the question’s entities, constraints, and requested detail. If the folder scope is insufficient, broaden once by omitting `--folder`. These limits apply across the question, not afresh to each result; read at most one additional result page across these lookups rather than loading all results. This read-only command searches cataloged entity bodies internally and returns at most 12 page excerpts within the 12,000-character output cap. Matches require all terms on one line and retain catalog order. A broader topic match does not establish that the requested detail is supported. A match is not evidence verification; a miss is not proof of corpus absence. Describe the searched scope and any unresolved gap. Do not reconstruct the answer from `raw/`.
3. Open selected pages and read their authority, confidence, qualifications, and relevant evidence before answering. In chat, use clickable Markdown links to the supporting source page's safe HTTP(S) or existing local-path `authority_ref`; otherwise link the source page itself. Prose, missing paths, malformed references, and unsafe schemes fall back to that page. Use the active interface's local-file convention (absolute paths in Codex). Keep `[[page-name]]` for durable wiki content. Do not publish private evidence to make a public link, and do not substitute a broad compiled-page authority for the source supporting the claim. Separate sourced facts from inference and open questions.
4. Do not call the answer independently verified. Use `wiki-research` only when the user explicitly invokes it.
5. When invoked as `wiki-ask`, end with a compact `Wiki pages consulted:` line naming the actual repository-relative pages used.
6. Use Analysis Capture below only when the answer should become a durable wiki page.

## Analysis Capture

When filing, use the [run workspace](../run-workspace.md). Ordinary answers remain chat-only.

File the answer as a citable analysis only when all three hold. It synthesizes at least three wiki pages, runs over 300 words, and answers a durable question about the configured domain. Use `capture_boundary: analysis-capture` and follow the [complete approval procedure](../../REFERENCES.md#complete-capture-staging) through its validation-only finish. Load that section only when filing.

If the filing test fails, answer in chat only. Append to `wiki/log.md` only when an analysis was filed or the user asked for a durable query record.

Name an analysis for the question, not its presumed answer. A filed analysis normally runs 300-800 words and uses `## Summary`, `## Question`, `## Key findings`, topic sections as needed, `## Open questions and gaps`, and `## Related pages`.

```text
## [YYYY-MM-DD] analysis-capture | <question summary>
Pages consulted: ...
Output filed: yes/no — <filename if yes>
```
