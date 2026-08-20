---
name: wiki-lint
description: Use this workflow when the user says "lint the wiki". Reads all pages and reports structural issues.
---

## Load / Skip

- **Load:** all wiki pages because lint is the one task that legitimately needs breadth. Also load `wiki/contradictions.md` and `wiki/sourcing-queue.md` if they exist; otherwise use the maintenance workflow files as the current operating record. During the evidence check in Step 3, verifier agents may also load only the raw files cited by sampled claims.
- **Skip:** unrelated `raw/` sources and the other workflow files.

## Steps

Lint is split by enforcement tier. Machine-checkable rules run as a deterministic script; only the rules that need genuine judgment are read by the agent.

Invoking `/lint`, `/wiki-lint`, or `wiki-lint` is an explicit request to run this full workflow, including the verifier-agent evidence check in Step 3. Do not ask for separate confirmation before using those verifier agents. If the user says "deterministic lint only", "no subagents", or "skip evidence check", skip Step 3 and say so in the final report.

1. Run the deterministic linter from the repo root:

   ```bash
   python3 scripts/lint.py
   ```

   It reports two tiers. **Tier 1** is machine-checkable and exits non-zero on any failure: filename and frontmatter-key validity, type/folder match, invalid `confidence` or `source_type`, malformed dates including `review_by`, dangling `[[links]]`, stale Markdown `.md` links, index coverage, duplicate link stems, empty required block lists, raw source references, raw bucket taxonomy drift against `scripts/raw-buckets.json`, tracked raw artifacts, repo folder-structure hygiene, raw/deliverables hygiene, stray tool-call artifacts, and `.DS_Store` files. These are not judgment calls, so fix them rather than debating them.

   **Tier 2** is ranked candidates and maintenance signals the script surfaces but cannot decide: near-duplicate pages, orphans, uncited pages, thin stubs, `confidence: low` pages with enough inbound links to upgrade, missing cross-references, quote/source mismatches that need review, goals or decisions missing `review_by` outcome checkpoints, due outcome reviews, legacy domain-configuration migration advisories, stale sourcing-queue entity counts, log rotation due, compiled pages with newer source inputs, source pages that no non-source entity page consumes, pages likely needing authority metadata, optional current-state owner drift, synthesis due after an ingest burst, and adjudication records that no longer suppress anything. Treat Tier 2 as a worklist to adjudicate, not as failures.

   Do not promote Tier-2 signals to Tier-1 because the underlying risk feels important. Promote only after reviewed maintenance cycles show high precision, false positives are structural enough to suppress or model as owned data, and each finding has a deterministic fix rather than a judgment debate. `recompile_candidates` and broad citation-support checks stay Tier-2 by default. Machine-checkable shape and reference failures can gate sooner: malformed proof/config, invalid adjudication entries, impossible authority refs, predictive authority without `review_by`, and source pages marked as current-state authority.

   Do not chase Tier 2 to zero. Add links only when the relationship is editorially meaningful. Leave weak candidates unresolved and record settled judgments in `scripts/lint-adjudications.json` so lint stops re-surfacing them.

   Current deterministic maintenance signals:

   - `sourcing_queue_count_drift`: `wiki/sourcing-queue.md` has machine-readable `<!-- lint:entity-count folder=... count=... -->` markers whose counts no longer match real entity pages. Malformed, duplicated, or negative markers are Tier-1 failures; drift is Tier 2 because the page may need editorial refresh.
   - `log_rotation_due`: `wiki/log.md` is over the configured live-log threshold. Run `workflows/maintenance/rotate-log.md`; the signal clears after archival.
   - `recompile_candidates`: a compiled page has authored links to source pages with newer `updated:` dates than the compiled page's own `updated:` or latest dated Status note. Review for no-change, a small update, or a recompile, then record durable no-change judgments under `reviewed_recompile_candidates`.
   - `unconsumed_sources`: a source page has no authored link from any non-source entity page. Source-to-source links, meta-page links, and generated `## Referenced by` echoes do not count as consumption because they do not integrate the source into the knowledge layer. Wire one editorially meaningful link from the right owner page, or record a durable standalone judgment under `reviewed_unconsumed_sources`. A page already adjudicated under `accepted_orphans` is suppressed automatically.
   - `glossary_volatile_status`: `wiki/glossary.md` has volatile status language inside a glossary entry. Rewrite to a dated fact or delegate live status to the owner page; adjudicate only durable definitional or rhetorical usage under `reviewed_glossary_volatile`.
   - `authority_missing`: a non-source page has a dated Status note or `review_by` checkpoint but lacks `authority_kind`. Backfill the smallest useful authority metadata from `wiki/SCHEMA.md`, or record a durable no-change judgment under `reviewed_authority_missing`.
   - `status_drift`, `owner_status_missing`, `owner_self_drift`, `owner_registry_empty`, and `authority_owner_mismatch`: when `scripts/current-state-owners.json` is explicitly enabled, review whether referring compiled pages or owner metadata lag a registered owner. Source pages are never the stale side. Suppress a durable no-change result only as a directional `[referring page, owner page]` pair under `reviewed_status_drift`. The disabled empty registry shipped by the template is quiet; malformed config and missing registered pages are Tier 1.
   - `review_by_missing` and `review_due`: goals and decisions should either enroll in the outcome-review loop with `review_by`, or be deliberately left out. Due reviews are collected by `scripts/review_due.py`.
   - `configuration_migration`: configured legacy domains without `configuration_version: 2` and `entity_preset` remain valid but should rerun `SETUP.md` when convenient. Populated legacy custom types require manual schema resolution.
   - `synthesis_due`: enough ingest activity has accumulated without a later synthesis pass that a human should consider running `/wiki-synthesize`.
   - `adjudication_dead`: an entry in `scripts/lint-adjudications.json` suppressed nothing in the current run. Prune it, or keep it deliberately when the historical judgment is still useful.

   Authority metadata separates provenance from current truth. `sources:` says what evidence informed a page; `authority_*` says what an agent should trust or re-check before acting on volatile claims. Source pages usually point at raw evidence with `authority_kind: raw-source`. Compiled pages can point at a source page, an owner page, a URL, a local resource, a mixed authority description, or `none` when no durable authority exists. Predictive authority requires `review_by`.

   Authority adoption is candidate-driven. Do not backfill low-risk stable pages for completeness, and do not use `authority_kind: none` just to quiet a review prompt. Add metadata where it changes future agent behavior: current-state owners, dated Status pages, `review_by` pages, predictive analyses, and pages whose facts an agent might act on.

   `glossary_volatile_status` exists because glossary definitions are a date-proxy blind spot: every ingest may bump the file-level `updated:`, so an individual entry can rot invisibly. Fenced format examples and the pre-heading preamble do not fire. Keep the vocabulary in `VOLATILE_STATUS_RE` while it remains small and eval-covered; move it to governed data only when that materially improves review or extension.

   Resolve a glossary candidate in one of two durable shapes:
   - **Dated fact:** "policy X was issued 2026-06-30" never rots; "the policy remains pending" does.
   - **Delegate:** drop the status claim and point at the page that owns it.

   Adjudicate under `reviewed_glossary_volatile` only for durable definitional or rhetorical usage. Never adjudicate a status claim that is merely true today: the suppression would outlive the truth and hide the exact rot this signal exists to catch.

2. Read the pages to assess the judgment-only checks the script deliberately does not attempt:
   - Contradictions between pages.
   - Stale claims superseded by newer sources.
   - Concepts mentioned but lacking their own page.
   - Terms used inconsistently where the right canonical term is a judgment call.
3. Run the **evidence check**: sampled verification that citations support the claims they are attached to. Tier 1 proves a `[[link]]` resolves and `quote_mismatch` surfaces possible non-verbatim quotes; this step checks overextension, conflation, mismatch, unsupported inference, and missing evidence. The linting agent orchestrates but does not judge its own claims.

   1. Choose a fresh, non-sensitive run ID and let the production interface draw the sample with operating-system randomness:

      ```bash
      python3 scripts/build_evidence_sample.py --run-id YYYYMMDD-HHMMSS --count 25
      ```

      The immutable manifest lives at `tmp/evidence-check/<run-id>/sample.json`. Its path-and-line identities, whole-file hashes, line hashes, and manifest hash bind this run to the exact sampled snapshot. Production sampling has no caller-provided seed; deterministic seed injection exists only inside the eval suite.

   2. Create exactly one hidden `plant.json` in that run directory. Select one claim from `sample.json`; copy its `claim_id` into `source_claim_id` and copy its `path`, `line_number`, and `cited_slugs` exactly. Set `schema_version` to `1`, `plant_id` to `plant-01`, `invalid_verdict` to `VERIFIED`, and `text` to a deliberately unsupported overstatement that differs from the sampled line. The plant stays only under this disposable run directory. Never write it to the corpus, reveal it in a verifier prompt, or log its text.

   3. Validate the sample and plant and atomically publish two or three exact batches plus prompts:

      ```bash
      python3 scripts/build_verifier_batches.py \
        --run-dir tmp/evidence-check/YYYYMMDD-HHMMSS --batches 3
      ```

      A partial batch/prompt install is not authoritative. If this command fails, use a fresh run ID rather than editing published batches.

   4. Give each file under `prompts/` to a separate verifier agent in a fresh context. Each agent tries to refute only its assigned item IDs against the cited page and, where present, the raw evidence behind it. Save its strict JSON response as `verdicts/<matching-batch-id>.json`. The only verdicts are `VERIFIED`, `OVEREXTENDED`, `CONFLATED`, `MISMATCH`, and `NOT-FOUND`; every item requires a decisive quote and canonical evidence paths. Do not merge, omit, duplicate, or renumber items.

   5. Validate exact sample-to-batch-to-verdict accounting and confirm that the source snapshot and generated prompts did not change:

      ```bash
      python3 scripts/verify_evidence_run.py \
        --run-dir tmp/evidence-check/YYYYMMDD-HHMMSS
      ```

      Trust metrics only when the result is `PASSED`. `STALE SNAPSHOT` has no valid precision metrics. A plant verdict of `VERIFIED`, missing or extra verdict, altered prompt, duplicate key, unsafe path, or schema mismatch makes the run fail. Re-sample under a fresh run ID after a failed plant.

   6. Adjudicate real flags with the user when needed. Confirmed findings get fixed by softening, relabeling provenance per `wiki/SCHEMA.md`, or correcting the citation. Rejected findings count as false positives; durable false positives go to `scripts/lint-adjudications.json` so they stop resurfacing. When fixing, aim for honest confidence rather than maximum hedging.
4. Propose fixes for Tier-2 candidates, evidence-check findings, and judgment checks, and ask which ones to apply. Tier-1 failures are not optional. Residual Tier-2 candidates are acceptable when reviewed and judged too weak, duplicated, or under-sourced to change.
5. After applying fixes, update the contradiction and sourcing-queue records if present.
6. Rebuild the auto-generated inbound-link sections:

   ```bash
   python3 scripts/rebuild_referenced_by.py
   ```

   The rebuild plans from one authored-page snapshot and applies one recoverable generation. Never delete `.wiki-transactions/` to clear a lint failure; inspect status and diagnose any preserved conflict or corruption.

7. Re-run `python3 scripts/lint.py` and confirm Tier 1 is clean before finishing.
8. Housekeeping: empty `tmp/` if it only contains lint scratch files. Contents of `tmp/` are disposable by rule; do not delete anything outside `tmp/`.
9. Append to `wiki/log.md`:

```text
## [YYYY-MM-DD] lint
Issues found: ...
Fixes applied: ...
Reviewed/no-change: ...
Evidence check: N sampled, M flagged, K fixed, R rejected, plant caught: yes/no
Contradictions opened/closed: ...
```

The evidence-check line grades the check itself: `K/M` is verifier precision. If false positives dominate across repeated runs, retune the verifier contract or consider narrowing the evidence-check step. A zero-flag streak alone is not a reason to retire evidence review; failed plants or persistently bad precision are the real signals.
