---
name: wiki-ask
description: Default lightweight workflow for answering questions from the wiki.
---

# Wiki Ask

Answer from the smallest relevant part of the wiki. This is the default research route.

## Load / Skip

- **Load:** bounded `python3 scripts/wiki_lookup.py index --query "<topic>"` results to locate pages, `wiki/primer.md` for entry points by question type, then only the pages the question touches. When filing an analysis, also load the citation and provenance rules in `wiki/SCHEMA.md`.
- **Skip:** unrelated entity folders, raw sources, evidence-run tooling, and the rest of `wiki/SCHEMA.md`.

## Steps

1. Start with the 3-8 pages most likely to answer the question.
2. If those pages are not enough, name the corpus gap. Do not expand into an unbounded scan or silently reconstruct the answer from `raw/`.
3. Answer clearly with `[[page-name]]` citations. Separate sourced facts from inference and open questions.
4. Do not call the answer independently verified. Use `wiki-research` only when the user explicitly invokes it.
5. Use Analysis Capture below only when the answer should become a durable wiki page.

## Analysis Capture

File the answer as a citable analysis only when all three hold. It synthesizes at least three wiki pages, runs over 300 words, and answers a durable question about the configured domain. Use `capture_boundary: analysis-capture` and follow the [complete approval procedure](../../REFERENCES.md#complete-capture-staging) through its validation-only finish. Load that section only when filing.

If the filing test fails, answer in chat only. Append to `wiki/log.md` only when an analysis was filed or the user asked for a durable query record.

Name an analysis for the question, not its presumed answer. A filed analysis normally runs 300-800 words and uses `## Summary`, `## Question`, `## Key findings`, topic sections as needed, `## Open questions and gaps`, and `## Related pages`.

```text
## [YYYY-MM-DD] analysis-capture | <question summary>
Pages consulted: ...
Output filed: yes/no — <filename if yes>
```
