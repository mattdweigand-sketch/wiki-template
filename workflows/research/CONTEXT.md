---
name: wiki-question-answering
description: Default workflow for answering questions from the wiki.
---

# Research Workspace

Consumes the wiki to answer a question and files the answer back as a citable analysis when it is substantial.

Analysis capture is a prose workflow with an executable approval gate. `scripts/capture_gate.py` decides whether a durable write is approved; this workflow decides whether the analysis is useful, cited, and worth filing.

## Load / Skip

- **Load:** `wiki/index.md` to locate pages, `wiki/primer.md` for entry points by question type, then only the specific pages the question touches. When filing an analysis through Analysis Capture, also load `wiki/SCHEMA.md`'s citation/provenance rules.
- **Skip:** the rest of `wiki/SCHEMA.md`, raw sources, and entity folders unrelated to the question.

## Calibration Examples

### Good

- Answer from the smallest set of relevant pages, cite them with `[[page]]`, and separate source-backed facts from inference.
- File an analysis only when the answer synthesizes 3+ pages, is substantial, and creates durable value for the configured domain.
- Keep a one-off clarification chat-only unless the user asks to preserve it.

### Bad

- Read broad folders because the question feels important.
- File a polished answer as an analysis when it is really a one-off clarification.
- Update a durable page just because the answer could be reusable, without the user asking to preserve or apply it.

## Steps

1. Read `wiki/index.md` and `wiki/primer.md` if unsure where to start.
2. Read only the relevant pages.
   Start with the 3-8 pages most likely to answer the question. If that set is
   insufficient, name the corpus gap instead of expanding into an unbounded
   scan or silently re-deriving the answer from `raw/`.
3. Synthesize a clear answer with citations to wiki pages using `[[page-name]]`.
4. Follow the Analysis Capture section below when the answer should be filed as a citable analysis.
5. Append to `wiki/log.md` only when an analysis was filed or the user explicitly asked for a durable query record:

## Analysis Capture

File the answer as a citable analysis when **all three** hold: it synthesized 3+ wiki pages, it runs over 300 words, and it answers a durable question about this wiki's configured domain. Before filing, stage the draft in `tmp/<slug>.md`, then run the gate:

```bash
python3 scripts/capture_gate.py --artifact "<answer summary>" --phase accepted \
  --synthesized-pages <count> --domain-context yes \
  --primary-home "wiki/analyses/<slug>.md" --pages-touched "<full edit scope>" \
  --path "tmp/<draft>.md"
```

On `APPROVAL REQUIRED`, follow `AGENTS.md`: ask first, re-run with `--approved` after the user approves, then run `python3 scripts/validate_capture_runs.py`. Save to `wiki/analyses/<slug>.md`, add or update the `wiki/index.md` row, run `python3 scripts/rebuild_referenced_by.py`, and run `python3 scripts/lint.py --tier1`. The rebuild applies one recoverable generation; preserve `.wiki-transactions/` and diagnose any named conflict or corruption instead of deleting recovery state. Notify in one line: `Filed as analyses/<slug>.md.` If any criterion fails, answer in chat only and do not write `wiki/log.md`.

Name an analysis for the question, not its presumed answer. A filed analysis
normally runs 300-800 words and uses this body shape: `## Summary`,
`## Question`, `## Key findings`, topic sections as needed,
`## Open questions and gaps`, and `## Related pages`. Cite source-backed
claims, mark inference explicitly, and make uncertainty visible. A brief may
compress that shape to at most 400 words. If the material needs substantially
more space, prefer multiple focused analyses or durable entity-page updates.

```text
## [YYYY-MM-DD] query | <question summary>
Pages consulted: ...
Output filed: yes/no — <filename if yes>
```
