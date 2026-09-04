# Capture — decision or experience

Use this workflow when the user says "capture decision [topic]" or "capture experience [topic]", or describes a decision they made or something they lived through and want recorded. Both routes are first-class; capture early and liberally.

## Load / Skip

- **Load:** `wiki/SCHEMA.md` (frontmatter), bounded `python3 scripts/wiki_lookup.py index --query "<topic>"` results to check whether an existing page already owns the topic, and the specific entity pages the capture affects or connects to.
- **Skip:** raw sources and unrelated entity folders.

## Capture Preflight

Neither capture route requires `scripts/capture_gate.py` approval unless it is being applied as part of artifact promotion or analysis capture (the boundary statement lives in `AGENTS.md`). This workflow owns the quality of the record: which page owns it, what is worth preserving, and how it links.

## Steps

1. Search the bounded catalog and the relevant entity folder (`wiki/decisions/` for decisions; the best-fit folder for experiences) for an existing page that already owns the topic. Update that page when it exists; create a new page only when no current page fits. Use frontmatter from `wiki/SCHEMA.md`.
2. Capture, by route:
   - **Decision:** the decision made; the reasoning; alternatives rejected and why; the date; when to revisit (consider a `review_by` date, which enrolls it in the outcome-review loop); entities affected.
   - **Experience:** what happened; what was learned; what would be done differently; when it occurred; what it connects to.
3. Cross-link from affected or related entity pages back to this page.
4. Add or update the `wiki/index.md` row for the page.
5. Write a scratch entry to `tmp/capture-entry.md`, then run `python3 scripts/finalize_wiki_update.py --log-entry tmp/capture-entry.md`. The [routine finish](../../REFERENCES.md#routine-finalization) rebuilds backlinks, records the entry, and runs full lint once. Review relevant Tier-2 candidates.

```text
## [YYYY-MM-DD] decision | <summary>
Page created/updated: <path>
Affects/Connects to: ...
Verification: finalize_wiki_update.py --log-entry tmp/capture-entry.md
```

Use `experience` as the entry type for an experience. Retry the same entry if finalization fails; do not append a second log entry afterwards.
