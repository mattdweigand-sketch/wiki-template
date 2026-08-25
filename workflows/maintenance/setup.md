---
name: wiki-setup
description: Ask the initial domain questions and replace only the placeholders in wiki/domain.md.
---

# Domain setup

Use this workflow for a fresh clone whose `wiki/domain.md` still contains placeholder values. The bare request "setup" routes here only in that state.

This workflow configures the wiki's subject. It does not configure Git, remotes, dependencies, raw buckets, entity folders, integrations, or infrastructure.

## Load / Skip

- **Load:** `wiki/domain.md`.
- **Skip:** entity pages, raw sources, indexes, logs, and unrelated workflows.

## Steps

1. Read `wiki/domain.md`. If none of its placeholder values remain, show the current domain values and ask what the user wants to change. Do not overwrite a configured domain from the bare request "setup."
2. Ask only for values that are still missing. Ask one question at a time unless the user already supplied several answers:
   - What should this wiki be called? This can be an organization, project, or personal context name.
   - What should the wiki cover? Ask for a one-sentence scope.
   - What three to five questions should the wiki help answer?
3. Resolve unclear or overlapping answers before editing. This is not a capture approval boundary, so no proposal digest is required.
4. Replace only the placeholder values for `org`, `domain`, and `example_queries`. Preserve every other field and the explanatory body. Keep the YAML valid and retain three to five example questions.
5. Run `python3 scripts/lint.py --tier1` and `git diff --check`.
6. Report the values written, the changed file, and the validation results. Do not commit unless the user asks.
