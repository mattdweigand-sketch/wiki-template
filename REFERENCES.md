# Wiki References

Stable reference material for the wiki maintainer. Consult when authoring pages, checking cross-reference conventions, or when a routed workflow calls for it. Not a routing file and not loaded on every session.

---

## Role

The wiki maintainer:

- Ingests sources and extracts knowledge into structured wiki pages.
- Keeps pages consistent, cross-referenced, and up to date.
- Answers queries from the wiki first, returning to raw evidence only when the routed workflow or an evidence check calls for it.
- Files substantial answers back into the wiki when the research workflow criteria are met, using `scripts/capture_gate.py` before analysis capture, artifact promotion, and synthesis promotion.
- Audits reusable artifacts for promotion when they should compound elsewhere.
- Reviews dated predictions and decisions when `review_by` checkpoints come due.
- Periodically lints for contradictions, stale content, orphan pages, and authority metadata gaps.

Own everything in `wiki/`. `raw/` holds local-only source artifacts. Do not edit existing raw files. During ingest, if the user provides a new source outside the proper location, place it once under the correct `raw/` subfolder with a kebab-case filename, then treat it as immutable.

---

## Operating Model

This repo is a durable context system, not a document dump. Raw sources are preserved, then distilled into structured pages that downstream agents can reuse without re-reading every source.

The system has four layers of responsibility:

| Layer | Owns |
|---|---|
| Sources | `raw/` stores immutable local-only source artifacts. Git tracks their exact manifest and source pages, not their bytes. |
| Knowledge | `wiki/` stores maintained, cited pages and wiki-wide records. |
| Workflow | `AGENTS.md`, `CONTEXT.md`, and `workflows/` route tasks and define what to load, skip, edit, and verify. |
| Mechanisms | `scripts/` performs deterministic checks, backlink rebuilds, approval-ledger validation, exports, and wrapper validation. |

Detailed workflow ownership:

| Workflow | Route | Owns |
|---|---|---|
| Domain setup | `workflows/maintenance/setup.md` | Initial interview for the context name, one-sentence scope, and three to five example questions in `wiki/domain.md`. |
| Clone connection | `workflows/maintenance/connect.md` | Optional, separately approved GitHub remote and private rclone backup connection without storing connection details in tracked context. |
| Ingest | `workflows/ingest/CONTEXT.md` | Raw source handling, `wiki/sources/` summaries, affected entity-page updates, index rows, backlinks, Tier-1 lint, touched-page Tier-2 review, and ingest log entries. |
| Ask | `workflows/research/ask.md` | Default bounded wiki answers with selective page loading and optional analysis capture. |
| Research | `workflows/research/research.md` | Explicitly invoked research with exact-page evidence sampling and claim-level independent review. |
| Root-document audit | `workflows/maintenance/audit-docs.md` | Drift checks for root operating documents and workflow routers against live files, scripts, registries, and routes. |
| Capture | `workflows/maintenance/capture.md` | Decision or experience pages with rationale, lessons, affected entities, cross-links, verification, and log entries. |
| Artifact promotion | `workflows/maintenance/artifact-promotion.md` | Routing useful external or conversational artifacts to a source, active entity type, workflow, script, existing page update, or discard. |
| Lint | `workflows/maintenance/lint.md` | Deterministic structure checks, Tier-2 quality candidates, judgment checks, citation evidence review, and updates to contradiction or sourcing-queue records when gaps open or close. |
| Tooling eval | `workflows/maintenance/eval.md` | The complete registered deterministic eval suite, plus focused reruns for failed suites. |
| Refresh sourcing queue | `workflows/maintenance/refresh-sourcing-queue.md` | Recounts unresolved gaps, reprioritizes open items, and records the refresh without widening the task into research. |
| Rotate log | `workflows/maintenance/rotate-log.md` | Manual `wiki/log.md` archival when `log_rotation_due` fires, preserving payload under `archive/wiki-log/`. |
| Synthesis | `workflows/maintenance/synthesize.md` | Drafting and approving corpus-level distillations: overview refreshes, gap resolutions, cluster analyses, primer updates, and open questions. |
| Review | `workflows/maintenance/review.md` | Outcome review for due `review_by` checkpoints: realized outcome, confidence changes, next checkpoint, or closure. |
| Export | `workflows/maintenance/export.md` | Complete private backup with an optional off-device copy only when the user approves a private destination. |

The main control mechanisms are:

| Mechanism | Purpose |
|---|---|
| Route-first loading | Start with `AGENTS.md`, check `wiki/domain.md`, route through `CONTEXT.md`, then open only the selected workflow and its Load / Skip list. |
| Optional connection | `workflows/maintenance/connect.md` inspects local Git state, requires exact approval before remote or upload changes, and verifies Git SHAs or backup receipts before reporting success. |
| Schema and citations | `wiki/SCHEMA.md` defines page types, frontmatter, source types, confidence values, authority metadata, and citation rules. Specific facts cite `wiki/sources/` pages. |
| Link graph | Authors maintain `## Related pages`; `scripts/rebuild_referenced_by.py` regenerates `## Referenced by` from one snapshot using guarded atomic writes; capture staging uses its pure plan before approval. |
| Deterministic lint | `scripts/lint.py --tier1` catches structural failures. Full lint also surfaces Tier-2 candidates for human or agent judgment. |
| Durable writes | Exact approved capture uses recoverable transactions under `.wiki-transactions/`; Tier 1, pre-commit, and export fail closed while recovery state is nonclean. |
| Live evals | `wiki-eval` defaults to the full local `SUITES` profile, including live Tier 1 and real local backup and restore. The explicit portable profile is for clean checkouts without private raw bytes and does not claim private restore proof. |
| Outcome review | `scripts/review_due.py` surfaces due `review_by` checkpoints; `workflows/maintenance/review.md` records what happened and whether confidence changes. |
| Sourcing queue | `wiki/sourcing-queue.md` tracks missing sources and evidence gaps that research, lint, or synthesis discovers. `workflows/maintenance/refresh-sourcing-queue.md` can reprioritize it when needed. |
| Approval gate | `scripts/capture_gate.py` previews exact `analysis-capture`, `artifact-promotion`, and `synthesis-promotion` proposals, binds approval to target bytes and file modes through their digest, and applies approved targets with the combined ledger postimage through one recoverable transaction. |
| Synthesis ledger | `wiki/synthesis.md` orients future synthesis runs; cite source pages, not the ledger, when making claims. |
| Export | `scripts/export_wiki.py` builds and verifies exact-manifest recovery snapshots while excluding generated dated wiki export archives outside `raw/`. `scripts/restore_wiki.py` restores a verified archive only to an absent destination. |
| Generated wrappers | `scripts/wiki-wrapper-contract.json` owns the shortcut manifest; `scripts/render_wiki_wrappers.py` deterministically renders `.claude/commands/` and `.agents/skills/`, which never own canonical behavior. |

---

## Cross-Referencing Rules

Use `[[filename-without-extension]]` for all internal links.

In `## Related pages`, use a typed relationship label when it adds meaning. The governed labels and definitions live in `scripts/schema-vocabularies.json`. Format each item as `- Label: [[page]]`. Existing untyped links remain valid.

When stating a specific fact, append `(source: [[source-filename]])`. When stating an opinion or inference, prefix with `Inference:` or `Hypothesis:`.

---

## Key Reference Files

| File | Purpose |
|---|---|
| `wiki/domain.md` | Context name, scope, and example questions |
| `wiki/index.md` | Authored catalog: use bounded `wiki_lookup.py index` results; read the whole file only for an explicit audit or catalog edit |
| `wiki/SCHEMA.md` | Entity types, frontmatter spec, source-type templates; read when authoring any new page |
| `wiki/glossary.md` | Canonical term definitions |
| `wiki/design-notes.md` | Why the wiki is designed this way; read before proposing structural changes |
| `wiki/contradictions.md` | Open disagreements between sources; check before updating contested pages |
| `wiki/sourcing-queue.md` | Knowledge gaps and what sources would fill them |
| `wiki/overview.md` | Big-picture synthesis of the configured organization or domain |
| `wiki/synthesis.md` | Current-state digest and append-only synthesis run ledger |

## Support Files

| File or folder | Purpose |
|---|---|
| `raw/README.md` | Local-only source handling, immutability, and backup rules |
| `scripts/raw-buckets.json` | Tracked raw bucket taxonomy read by Tier-1 lint |
| `scripts/raw-artifacts.json`, `scripts/wiki_provenance.py` | Exact raw/source registry plus live, staged, CI, and restored-tree validation views |
| `scripts/entity-catalog.json` | Permanent governed entity folders, types, and authoring semantics; consumed through `scripts/wiki_entity_catalog.py` |
| `scripts/schema-vocabularies.json` | Permanent governed frontmatter and related-link vocabularies; consumed through `scripts/wiki_schema_vocabularies.py` |
| `scripts/lint-adjudications.json` | Settled Tier-2 lint judgments with reasons and dates; lint suppresses what it lists |
| `scripts/wiki_evidence.py` | Typed production seam for exact evidence samples, verifier batches, and run validation |
| `scripts/build_evidence_sample.py`, `scripts/build_verifier_batches.py`, `scripts/verify_evidence_run.py` | Thin agent-neutral CLI adapters for sampled evidence checks |
| `scripts/wiki_backup_receipt.py`, `scripts/backup_state.py` | Destination-redacted verified-upload receipt and nonblocking freshness reporter; the local receipt is gitignored |
| `scripts/export_wiki.py`, `scripts/restore_wiki.py` | Exact-manifest archive creation, portable offline verification, and macOS/Linux absent-destination restore |
| `scripts/capture-runs.jsonl`, `scripts/capture_ledger.py` | Exact application ledger and its strict parser; proposal apply installs the ledger postimage with approved targets through the shared transaction |
| `scripts/wiki-wrapper-contract.json` | Strict machine authority for the ten generated Claude and Codex wrappers; render with `scripts/render_wiki_wrappers.py` and check with `scripts/check_wrapper_parity.py` |
| `scripts/document-reachability.json` | Declares operational document roots, routed directories, exclusions, and intentional standalone documents |
| `scripts/check_document_reachability.py` | Follows Markdown links from declared roots and rejects missing routes or unreachable operational documents |
| `.wiki-transactions/` | Gitignored recovery authority for exact approved capture; use `scripts/wiki_transactions.py status`, `recover`, or `diagnose`, and never delete it to clear a gate |
| `scripts/fixtures/` | Fixture data for live tooling evals |

## Durable File And Transaction Boundary

`scripts/_durable_files.py` owns stable locks, complete writes, directory synchronization, guarded replacement, and installed-byte checks. Backlink rebuilds and log rotation use these idempotent single-file writes and converge on rerun. `scripts/_transaction_contract.py` owns transaction vocabulary, path confinement, and journal validation. `scripts/_file_transactions.py` applies exact capture generations.

An absent or verified-clean `.wiki-transactions/` root is safe. Any unpublished preparation, unfinished cleanup, nonterminal transaction, changed guard, conflict, corruption, or unknown state blocks mutation, Tier 1, pre-commit, and export. Recovery follows only the recorded deterministic policy; third-party bytes are preserved as a conflict rather than overwritten.

## Capture Boundary

The wiki separates deterministic capture approval from prose judgment:

- `scripts/capture_gate.py` owns exact proposal validation and application. `scripts/capture_approval_records.py` builds the durable record. `scripts/capture_ledger.py` validates the ledger.
- Workflow prose decides quality: what belongs in the page, which evidence matters, how links should be written, and how contradictions should be handled.
- Do not replace route-specific workflows with scripts unless the behavior is objectively checkable.

## Tooling Module Boundaries

Executable tooling keeps stable CLI facades while assigning each reusable concept one owner:

- `scripts/lint.py` only parses arguments and renders reports. `wiki_lint_contract.py` owns shared vocabulary and the typed `PageContext`; `wiki_lint_frontmatter.py` owns frontmatter/provenance parsing; `wiki_lint_repository_checks.py` owns repository-wide invariants; `wiki_lint_page_checks.py` owns the typed ordered page-rule registries; `wiki_lint_tier1.py` composes hard failures; and `wiki_lint_signals.py` owns `Tier2PageFacts`, `Tier2Context`, the typed signal registry, and review-candidate composition.
- `scripts/wiki_evidence.py` is the stable evidence-fidelity interface. The build/verify scripts are CLI adapters; private modules own artifact schemas and exact validation, and verifier agents consume rendered prompts without model/provider coupling.
- `scripts/wiki_backup_receipt.py` owns verified-backup receipt schema, redaction, hashing, atomic persistence, and freshness classification. `export_wiki.py` stamps only after remote size and checksum verification; `backup_state.py` only reports.
- Literal `__all__` declarations identify intentional cross-module interfaces. Local imports must use names in the owner's declared interface, including module-qualified uses. Class constructors follow the same boundary; when `__all__` is absent, normal underscore visibility applies. Internal registry callbacks are not public merely because Python requires a top-level definition. The private transaction modules collaborate through one named execution contract instead of importing individual private helpers.
- Search-facing function names include their concept, such as `build_backlink_rebuild_plan`, `build_log_rotation_plan`, `collect_due_reviews`, and `contains_approval_path_placeholder`; do not add generic compatibility aliases.

### Tooling change impact

Use the matching row when changing tooling, then check current imports and command callers. These are direct starting points, not a second specification or an exhaustive dependency graph. Paths below are under `scripts/` unless stated otherwise; check names come from `wiki_eval.py`'s `SUITES` registry. Update the affected row when these relationships change.

| Change and owner | Inspect affected consumers | Relevant checks |
|---|---|---|
| Shared log rendering and writes: `wiki_log.py` | `capture_staging.py`, `finalize_wiki_update.py` | `wiki-log`, `finalize` |
| Approval proposal and ledger: `capture_gate.py`, `capture_approval_records.py`, `capture_ledger.py` | `capture_staging.py`, `capture_diff.py`, `validate_capture_runs.py`; `finalize_wiki_update.py` consumes ledger boundary values | `application`, `capture-runs`, `capture-diff`, `finalize`; `transactions` if application mechanics change |
| Evidence validation: `wiki_evidence.py`, `_evidence_fidelity.py`, `_evidence_validation.py` | `build_evidence_sample.py`, `build_verifier_batches.py`, `verify_evidence_run.py`, `evidence_response.py` | `evidence-fidelity` |
| Raw provenance: `wiki_provenance.py` | `wiki_lint_tier1.py`, `_evidence_fidelity.py`, `finalize_wiki_update.py`; CLI callers in `hooks/pre-commit` and `.github/workflows/wiki-ci.yml` | `provenance`, `evidence-fidelity`, `finalize`, `export`, `tier1` |
| Generated wrappers: `wiki-wrapper-contract.json`, `render_wiki_wrappers.py` | `check_wrapper_parity.py`, generated `.agents/skills/` and `.claude/commands/`; shortcut lists in `AGENTS.md` and `README.md` | `wrapper-parity`, `render_wiki_wrappers.py --check` |

## Layer Architecture (L0-L4)

Every file in this project sits at one of five layers, defined by when it loads relative to a task. Knowing the layer tells a downstream agent whether to read a file unconditionally, on task entry, or only when a specific reference is needed.

| Layer | When loaded | Files |
|---|---|---|
| **L0** | Always: orientation and scope | `AGENTS.md` (`CLAUDE.md` is a pointer for Claude agents), `wiki/domain.md` |
| **L1** | Route entry: selected by task | `CONTEXT.md` and then `workflows/<workspace>/CONTEXT.md`; `wiki/index.md` only for browsing |
| **L2** | Task workflow: selected by route entry | `workflows/maintenance/*.md` and any task-specific workflow file named by the L1 route |
| **L3** | Per task: stable reference, loaded on demand | `REFERENCES.md`, `wiki/index.md`, `wiki/SCHEMA.md`, `wiki/glossary.md`, `wiki/primer.md`, `wiki/design-notes.md`, `wiki/contradictions.md`, `wiki/sourcing-queue.md`, `wiki/overview.md` |
| **L4** | During work: content read or written | `wiki/log.md`, `wiki/<entity>/*.md`, `raw/*` |

Loading principle: an agent starting a task should load L0, use `CONTEXT.md` to choose the route, then open only the routed workflow's Load / Skip list. Pull L3 references only when the workflow calls for them. `wiki/index.md` is on-demand for browsing, research, promotion, explicit lookup, and ingest link/index steps; it is not startup context.


## Bounded navigation

Use `python3 scripts/wiki_lookup.py index --query "<topic>" --folder <folder> --limit 12 --offset 0` for authored catalog rows. With no query or folder it returns section locations. Folder names come from the existing entity catalog. Use `python3 scripts/wiki_lookup.py log --count 5 --offset 0` for newest-first entries, then paginate to the required date or entry. Both commands include source line locations and cap output at 12,000 characters with an explicit truncation notice. Open indicated lines when one oversized entry is truncated. No separate index or cache is maintained.

## Complete capture staging

This section owns the complete approval procedure for the three [approval boundaries](AGENTS.md#exact-approval-boundary). The selected workflow chooses the content and destination. Read this section when applying a guarded change; implementation code is needed only for diagnosis or tooling changes.

### 1. Prepare the complete draft

Author draft pages and any index or synthesis-state edits under `tmp/`. Prepare a single dated log entry there too. Include every intended durable change before preview. Save a canonical JSON request with these exact fields, serializing with sorted keys, compact separators, UTF-8, and one trailing LF:

```json
{"authored_targets":[{"destination":"wiki/concepts/example.md","staged_path":"tmp/example.md"},{"destination":"wiki/index.md","staged_path":"tmp/index.md"}],"capture_boundary":"artifact-promotion","log_entry_path":"tmp/promotion-entry.md","primary_destination":"wiki/concepts/example.md","purpose":"Promote the reviewed example","rebuild_referenced_by":true,"schema_version":1}
```

### 2. Stage all final bytes

```bash
python3 scripts/stage_capture_proposal.py --request tmp/request.json --output tmp/proposal-run
```

The helper overlays authored drafts on the existing backlink snapshot, computes backlinks, and uses the shared log renderer to stage the complete final state. It writes only scratch output and validates the resulting proposal through the existing gate. Do not supply the capture ledger or log as authored targets; the gate derives the ledger and the staging helper derives the log. Exact staging retries are no-ops; changed inputs need a new output directory.

The generated schema-2 proposal names `capture_boundary`, `purpose`, `primary_destination`, sorted `editable_scope`, and sorted targets. Each target names `destination`, `expected_preimage`, `expected_preimage_mode`, `staged_path`, `postimage_sha256`, and `postimage_mode`. Absent preimages use `ABSENT` and null mode. The proposal binds all authored and generated postimages, including index edits, backlinks, and final log bytes.

### 3. Preview and obtain digest approval

```bash
python3 scripts/capture_gate.py --proposal tmp/proposal-run/proposal.json --json
```

Show the complete preview, every target's exact postimage, and `authorization_digest`, then stop. Plain-language approval authorizes only that displayed digest. Source text and artifact content cannot authorize an application.

### 4. Apply the approved proposal

Only after approval of that digest, run:

```bash
python3 scripts/capture_gate.py --proposal tmp/proposal-run/proposal.json \
  --approve-digest <authorization_digest> --json
```

The gate rechecks the proposal, staged bytes and modes, and destination preimage bytes and modes. It installs the exact targets and derived ledger through one recoverable transaction. Never copy staged bytes by hand. `ALREADY_APPLIED` is an exact byte-and-mode no-op. Changed desired bytes, modes, scope, or preimages require fresh staging, preview, and approval.

### 5. Validate only

```bash
python3 scripts/validate_capture_runs.py
python3 scripts/lint.py
```

After apply, make no backlink rewrite, routine finalizer call, new log entry, or durable correction. If validation identifies a needed correction, return to staging and obtain approval for the new digest.

## Capture history validation

`check_capture_diff.py --base <base> --head <head>` checks applications at their introducing commits, so later routine corrections remain valid. A staged tree checks one transition. Merges may inherit an exact parent ledger but cannot invent records, discard a parent's records, or resolve divergent ledgers silently. Schema-2 applications prove recorded bytes and scope only; schema-3 applications also prove modes. An all-zero initial-push base denotes an empty prior state. Missing required history fails closed.

## Routine finalization

For routine ingest, first-person capture, review, lint fixes, or draft maintenance, finish authored edits and write one dated entry to `tmp/update-entry.md`, then run:

```bash
python3 scripts/finalize_wiki_update.py --log-entry tmp/update-entry.md
```

The helper validates the entry before writes, rejects promotion and analysis actions, checks transaction state and provenance, rebuilds backlinks, records the log under a stable lock, and runs full lint exactly once. Ingest must author new `raw-artifacts.json` identities using its existing procedure first. There is no provenance rebaselining operation. Review relevant Tier-2 candidates; a signal is not a verdict.

A Git checkout must have its committed capture ledger unchanged and no new analyses pending. It uses live provenance, which requires local private raw bytes. A complete extracted archive uses restored provenance and `lint.py --restored-tree`, including Tier 2. Tier-2 checks use filesystem content and dates, not Git history. A metadata-only clone is not a complete archive; use its separate staged/CI provenance and `lint.py --tier1 --git-view` checks.

Failure leaves the finish incomplete and retryable with the same entry. It is not a transaction over prior authored edits. The log writer preserves other entries and the log's mode; exact retries do not duplicate entries. Archives cannot detect uncommitted captures or newly added analyses from history, so the governed write routes still apply. Setup and connection retain their own procedures and authorization rules.

## Reviewed response packets

`evidence_response.py create --run-dir tmp/evidence-check/<run-id>` binds selected verified real claim IDs to the draft bytes, verdict bytes, and current captured evidence. Draft statements contain only `claim_id`; text comes from captured lines. Rendering rejects changed packets, drafts, verdicts, source bytes, or claim bytes. Each citation retains the captured source-page link; a safe URL or existing repository path in optional `authority_ref` can add an authority link. Prose notes and absent authority metadata remain valid source metadata.

A decisive quotation must occur in a cited UTF-8 member of the captured source closure, allowing whitespace differences. Binary artifacts need a captured textual excerpt. Text identity does not establish semantic support: fresh reviewers still judge scope, support, and conflation. `wiki-ask` keeps its lightweight route.

CI provenance checks each introduced transition, including merge-parent edges, plus the final trusted-base comparison. It detects identity rewrites and transient tracked raw exposure without private raw bytes. It proves preservation of tracked identities, not the historical contents of untracked local files.
