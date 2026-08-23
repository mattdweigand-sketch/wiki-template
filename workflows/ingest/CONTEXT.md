---
name: wiki-ingest
description: Use this workflow when the user drops a file in raw/ and says "ingest" or "ingest [source]". Handles file organization, source summarization, wiki updates, and promotion-candidate audit.
---

# Ingest Workspace

Turns a raw source into structured wiki pages. Single task: read the source, file it, update the pages and indexes it touches. This `CONTEXT.md` is the whole workflow.

Apply the canonical [trust boundary](../../AGENTS.md#trust-boundary) to every source and fetched artifact.

Ingest is a normal durable write. It does not require `scripts/capture_gate.py` approval. Use the capture gate only if the ingest turns into an analysis-capture or artifact-promotion apply route. If an ingest genuinely seems to need staged review before durable edits, raise it with the user instead of running a script.

## Load / Skip

- **Load:** `wiki/SCHEMA.md` (source-type templates + frontmatter), `wiki/domain.md` for active entity types and raw taxonomy, the source file(s) in `raw/`, and the specific existing pages the source touches. When a source contains speaker-labeled or timestamped speech, also load [transcript evidence](transcript-evidence.md). At the link step (Step 5), also load `REFERENCES.md` (cross-referencing rules), `wiki/index.md`, `wiki/glossary.md`, and `wiki/log.md`.
- **Skip:** the rest of the wiki, the other workspaces, and `wiki/contradictions.md` unless a clash actually surfaces.

## Calibration Examples

### Good

- Preserve the raw artifact once, then treat it as immutable even if a better title, date, or URL appears later.
- Update the existing pages the source actually changes, then add source-page links and let `rebuild_referenced_by.py` regenerate inbound links.
- Keep source summaries dense and caveated: name what the source claims, what it supports, and what remains unverified.

### Bad

- Rename or edit an existing raw file to make provenance look cleaner.
- Create a new concept page because the source uses a catchy phrase when an existing page already owns the idea.
- Treat customer, metric, market, or strategy claims inside a source as verified facts when the underlying evidence has not been ingested.

## Step 0 - File handling (before reading anything)

`raw/` holds local-only source artifacts. Do not edit existing raw files and never add them to Git. If the user provides a new source outside the proper location, place it once under the correct `raw/` subfolder with a kebab-case filename, then treat it as immutable.

Every real raw artifact is registered in `scripts/raw-artifacts.json`. One sorted record binds a source-page slug to its capture date and every exact raw member's path, size, and SHA-256. The matching `wiki/sources/<slug>.md` page must cite exactly those raw paths. Preserve the local raw bytes and update the tracked source page and manifest as one coherent ingest. Accepted records and raw bytes are immutable afterward.

1. Check for newly provided files in `raw/` root and any subfolders.
2. For each new file:
   - Decide the right subfolder from `scripts/raw-buckets.json`; check `raw/README.md` and `ls raw/` before inventing a new subfolder.
   - Rename to kebab-case, preserve the extension.
   - Move the file into its subfolder when it is already inside `raw/`; copy or move it into `raw/` when the user provided it elsewhere; do not alter its contents.
3. Confirm the resulting file layout before proceeding.

## Step 1 - Read and discuss

1. Read the source file(s) from `raw/`.
2. Classify whether the source contains transcript-like evidence. Apply [transcript evidence](transcript-evidence.md) when a claim depends on a speaker, exact wording, timestamp, sequence, interaction direction, or count of independent voices.
3. Discuss 2-3 key takeaways. Ask clarifying questions only when needed to avoid a wrong durable write; an explicit ingest request should otherwise keep moving.

## Step 2 - Create source page

Create a summary page in `wiki/sources/` named after the source file. Use `source_type` from `wiki/SCHEMA.md` to shape the summary.

## Step 3 - Update existing pages

Identify which existing wiki pages are affected and update them.

Before putting a transcript-derived claim onto a compiled page, reopen the raw
artifact when the claim depends on speaker identity, exact wording, a
timestamp, dialogue sequence, interaction direction, or independence counts.
Broad claims already captured faithfully on the source page may continue to
cite that source page without reopening raw evidence.

## Step 4 - Create new entity pages

Create new entity pages as warranted by the active entity types in `wiki/domain.md` and the schema in `wiki/SCHEMA.md`.

## Step 5 - Update wiki-wide files

1. Update `wiki/glossary.md` with any new or refined terms.
2. Update `wiki/index.md`: add new pages and refresh summaries of changed pages. Index rows must use Markdown links to folder-qualified page paths—for example, a `page-slug` label targeting `concepts/page-slug.md`—because Tier-1 lint uses those links to verify coverage. Use `[[wikilinks]]` inside authored page bodies and `## Related pages`, not as the index coverage link.
3. Update `wiki/overview.md` if the source shifts the big picture.

## Step 6 - Stale-text sweep, rebuild, and lint

If the source resolves something the corpus previously recorded as open,
missing, or pending (for example: a policy issued, an invoice paid, or a
decision made), the old current-state claim may be stale somewhere. Before
final verification, prefer the read-only helper for the sweep, using two or
three phrasings of the old wording across `wiki/`:

```bash
python3 scripts/stale_text_sweep.py --phrase "<old wording>" --phrase "<alternate wording>" --root wiki
```

Manual `rg -n -i -- <phrase> wiki/` sweeps remain acceptable when the helper is
insufficient; keep the same command evidence in the log.

Classify the hits before editing:

- **Current owner pages and compiled pages:** update stale current-state text or
  replace it with stable delegation to the owner page.
- **Source pages:** preserve historical source-era claims unless the page's
  current summary now misleads; if clarification is needed, keep the source
  boundary and add later-source context.
- **`wiki/log.md`:** preserve historical log entries; fix only a false
  verification claim or a current maintenance note that is itself wrong.

Record the actual command, hit count, pages fixed, and historical/no-change hits
in the log entry using the structured `Stale-text sweep:` line in Step 8. Use
executable evidence, not a pass/fail claim. The `glossary_volatile_status`
signal in full lint backstops glossary entries specifically; the sweep covers
every other page class.

After all `[[wikilinks]]` are written, refresh the auto-generated `## Referenced by` sections:

```bash
python3 scripts/rebuild_referenced_by.py
```

Run from the repo root. The script is stdlib-only and idempotent. It plans from one immutable authored-page snapshot and applies all changed pages as one recoverable generation. Never hand-edit a `## Referenced by` section; edit `## Related pages` and let the script regenerate the inbound list. If recovery reports a conflict or corrupt record, preserve `.wiki-transactions/` and diagnose the named transaction instead of deleting state or retrying blindly.

Then run the deterministic Tier-1 gate:

```bash
python3 scripts/lint.py --tier1
```

Tier-1 is machine-checkable: filename and frontmatter-key validity, type/folder match, invalid `confidence` or `source_type`, malformed dates, dangling `[[links]]`, index coverage, repo structure, raw tracking and exact-byte provenance, raw/deliverables hygiene, structured stale-sweep proof, and related structural rules. Treat failures as must-fix before logging.

Then run full lint and inspect Tier-2 findings only for pages touched by this ingest:

```bash
python3 scripts/lint.py
```

Tier-2 is a review queue, not a failure gate. For newly created or changed pages, check whether the ingest left an orphan source page, missing cross-reference, uncited/thin page, quote mismatch, confidence-upgrade candidate, missing `Open questions / gaps`, or missing `review_by` checkpoint. Fix clear ingest misses before logging; leave unrelated existing candidates for the lint workflow.

## Step 7 — Log

Append to `wiki/log.md`:

```text
## [YYYY-MM-DD] ingest | <source title>
Pages created: ...
Pages updated: ...
Key additions: ...
Stale-text sweep: status=completed; commands=["rg -n -i -- '<phrase>' wiki/"]; hit_count=0; pages_fixed=[]; historical_no_change_hits=[]
Contradictions flagged: ...
```

If the source did not resolve an open/current-state claim, use this line instead:

```text
Stale-text sweep: status=not_applicable; reason="<why the source did not resolve an open/current-state claim>"
```

A single ingest may touch 5-15 wiki pages. That is expected.
