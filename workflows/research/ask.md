---
name: wiki-ask
description: Default lightweight workflow for answering questions from the wiki.
---

# Wiki Ask

Answer from the smallest relevant part of the wiki. This is the default research route.

## Load / Skip

- **Load:** `wiki/index.md` to locate pages, `wiki/primer.md` for entry points by question type, then only the pages the question touches. When filing an analysis, also load the citation and provenance rules in `wiki/SCHEMA.md`.
- **Skip:** unrelated entity folders, raw sources, evidence-run tooling, and the rest of `wiki/SCHEMA.md`.

## Steps

1. Start with the 3-8 pages most likely to answer the question.
2. If those pages are not enough, name the corpus gap. Do not expand into an unbounded scan or silently reconstruct the answer from `raw/`.
3. Answer clearly with `[[page-name]]` citations. Separate sourced facts from inference and open questions.
4. Do not call the answer independently verified. Use `wiki-research` only when the user explicitly invokes it.
5. Use Analysis Capture below only when the answer should become a durable wiki page.

## Analysis Capture

File the answer as a citable analysis only when all three hold. It synthesizes at least three wiki pages, runs over 300 words, and answers a durable question about the configured domain. Before filing, stage every exact postimage and an `analysis-capture` proposal under `tmp/`, then follow the exact preview and apply flow in `AGENTS.md`.

```bash
python3 scripts/capture_gate.py --proposal tmp/<proposal>.json --json
# After approval of the displayed authorization_digest
python3 scripts/capture_gate.py --proposal tmp/<proposal>.json \
  --approve-digest <authorization_digest> --json
```

Show the full preview and stop for approval. Do not copy staged files by hand. After apply, run `python3 scripts/validate_capture_runs.py`, `python3 scripts/rebuild_referenced_by.py`, and `python3 scripts/lint.py --tier1`.

If the filing test fails, answer in chat only. Append to `wiki/log.md` only when an analysis was filed or the user asked for a durable query record.

Name an analysis for the question, not its presumed answer. A filed analysis normally runs 300-800 words and uses `## Summary`, `## Question`, `## Key findings`, topic sections as needed, `## Open questions and gaps`, and `## Related pages`.

```text
## [YYYY-MM-DD] query | <question summary>
Pages consulted: ...
Output filed: yes/no — <filename if yes>
```
