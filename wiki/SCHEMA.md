# Wiki Schema Reference

Use this file when authoring or auditing a wiki page.

Two data files own the allowed values.

- `scripts/entity-catalog.json` owns entity types, folders, purpose, review guidance, and default freshness.
- `scripts/schema-vocabularies.json` owns confidence, source type, authority, and related-link values.

Do not copy their complete lists into another document.

## Page format

Every page inside `wiki/<entity-folder>/` uses this frontmatter.

```yaml
---
title: <page title>
type: <type from scripts/entity-catalog.json>
created: YYYY-MM-DD
updated: YYYY-MM-DD
review_by: YYYY-MM-DD
sources: [source references]
source_type: <source type from scripts/schema-vocabularies.json>
tags: [relevant tags]
confidence: <confidence from scripts/schema-vocabularies.json>
agent_use_cases:
  - <question this page helps answer>
---
```

`review_by` is optional. It is expected for decisions and goals unless there is a clear reason to leave the page out of outcome review.

`source_type` is required only for pages in `wiki/sources/`.

`agent_use_cases` is required for non-source entity pages.

Root wiki files are infrastructure and may use lighter frontmatter.

## Source references

Each `sources` item may be one of these forms.

- A `raw/` path.
- A bare kebab-case slug for a page under `wiki/sources/`.
- A URL.
- Free text beginning with `experience`, `web`, `deliverable`, or `source` followed by a colon or space.

Lint checks raw paths and source-page slugs when it can.

## Authority

`sources` records what informed a page. Authority fields record where current truth lives.

```yaml
authority_kind: <value from scripts/schema-vocabularies.json>
authority_ref: <repo path, URL, or short mixed-source note>
authority_freshness: <value from scripts/schema-vocabularies.json>
verify_before_action: true
last_verified: YYYY-MM-DD
```

Authority fields are optional. If any authority field is present, `authority_kind` is required.

Use full repo paths in `authority_ref`. Do not use bare source slugs there.

Predictive authority requires `review_by`.

For changing facts, use one owner page. Other pages should link to it instead of copying live values.

## Body

After frontmatter, write these parts.

1. One-line summary.
2. A structured body.
3. `## Open questions / gaps` on non-source entity pages.
4. `## Related pages` when useful.

Use kebab-case filenames with no date prefix.

## Evidence rules

- Add `(source: [[source-page]])` after a specific fact.
- Prefix opinions and inference with `Inference:` or `Hypothesis:`.
- Use quotation marks only for exact source wording.
- Keep vague source language vague.
- Label a list assembled from scattered evidence as synthesis.
- Restate `confidence: low` or `confidence: contested` in the body.
- A contested page needs a `## Disagreement` section naming both sides.

## Related pages

Write ordinary `[[wikilinks]]`. When a typed relationship adds meaning, use a label from `scripts/schema-vocabularies.json`.

```markdown
## Related pages

- Depends on: [[workflow-automation]]
- Supports: [[q3-board-deck]]
- Related: [[pricing-packaging]]
```

Plain links remain valid.

```markdown
- [[page]]
```

Do not edit `## Referenced by`. Run `scripts/rebuild_referenced_by.py` after authored links change.

## Source summaries

Choose the narrowest source type in `scripts/schema-vocabularies.json`.

Summaries should state what the source can support, what needs care, the main claims, and open gaps. A source page is an evidence map, not proof that every source claim is true.

## Referenced by

_No inbound links yet._
