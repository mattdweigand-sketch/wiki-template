# Wiki References

Stable reference material for the wiki maintainer. Consult when authoring pages, checking cross-reference conventions, or when a routed workflow calls for it. Not a routing file and not loaded on every session.

---

## Role

The wiki maintainer:

- Ingests sources and extracts knowledge into structured wiki pages.
- Keeps pages consistent, cross-referenced, and up to date.
- Answers queries by reading the wiki, not by re-deriving from raw sources.
- Files substantial answers back into the wiki when the research workflow criteria are met, using `scripts/capture_gate.py` before analysis capture, artifact promotion, and synthesis promotion.
- Audits reusable artifacts for promotion when they should compound elsewhere.
- Reviews dated predictions and decisions when `review_by` checkpoints come due.
- Periodically lints for contradictions, stale content, orphan pages, and authority metadata gaps.

Own everything in `wiki/`. `raw/` holds source artifacts: do not edit existing raw files. During ingest, if the user provides a new source outside the proper location, place it once under the correct `raw/` subfolder with a kebab-case filename, then treat it as immutable.

---

## Operating Model

This repo is a durable context system, not a document dump. Raw sources are preserved, then distilled into structured pages that downstream agents can reuse without re-reading every source.

The system has four layers of responsibility:

| Layer | Owns |
|---|---|
| Sources | `raw/` stores source artifacts. Existing raw files are immutable. |
| Knowledge | `wiki/` stores maintained, cited pages and wiki-wide records. |
| Workflow | `AGENTS.md`, `CONTEXT.md`, and `workflows/` route tasks and define what to load, skip, edit, and verify. |
| Mechanisms | `scripts/` performs deterministic checks, backlink rebuilds, approval-ledger validation, exports, and wrapper validation. |

Detailed workflow ownership:

| Workflow | Route | Owns |
|---|---|---|
| Setup | `SETUP.md` | First-session configuration: context owner, domain, preset, supported active entity types, raw taxonomy, privacy warning, and example questions. |
| Ingest | `workflows/ingest/CONTEXT.md` | Raw source handling, `wiki/sources/` summaries, affected entity-page updates, index rows, backlinks, Tier-1 lint, touched-page Tier-2 review, and ingest log entries. |
| Research | `workflows/research/CONTEXT.md` | Wiki-grounded answers, selective page loading, optional analysis capture, and promotion-candidate audits. |
| Capture | `workflows/maintenance/capture.md` | Decision or experience pages with rationale, lessons, affected entities, cross-links, verification, and log entries. |
| Artifact promotion | `workflows/maintenance/artifact-promotion.md` | Routing useful external or conversational artifacts to a source, active entity type, workflow, script, existing page update, or discard. |
| Lint | `workflows/maintenance/lint.md` | Deterministic structure checks, Tier-2 quality candidates, judgment checks, citation evidence review, and updates to contradiction or sourcing-queue records when gaps open or close. |
| Rotate log | `workflows/maintenance/rotate-log.md` | Manual `wiki/log.md` archival when `log_rotation_due` fires, preserving payload under `archive/wiki-log/`. |
| Synthesis | `workflows/maintenance/synthesize.md` | Drafting and approving corpus-level distillations: overview refreshes, gap resolutions, cluster analyses, primer updates, and open questions. |
| Review | `workflows/maintenance/review.md` | Outcome review for due `review_by` checkpoints: realized outcome, confidence changes, next checkpoint, or closure. |
| Export | `workflows/maintenance/export.md` | Local corpus backup, including gitignored raw sources, with an optional upload only when the user supplies an explicit destination. |

The main control mechanisms are:

| Mechanism | Purpose |
|---|---|
| Route-first loading | Start with `AGENTS.md`, check `wiki/domain.md`, route through `CONTEXT.md`, then open only the selected workflow and its Load / Skip list. |
| Schema and citations | `wiki/SCHEMA.md` defines page types, frontmatter, source types, confidence values, authority metadata, and citation rules. Specific facts cite `wiki/sources/` pages. |
| Link graph | Authors maintain `## Related pages`; `scripts/rebuild_referenced_by.py` regenerates `## Referenced by` from one snapshot and applies the generation as a recoverable transaction. |
| Deterministic lint | `scripts/lint.py --tier1` catches structural failures and malformed proof. Full lint also surfaces Tier-2 candidates for human or agent judgment. |
| Durable writes | Stable-lock atomic ledger replacement and `.wiki-transactions/` protect interrupted, concurrent, and multi-file updates; Tier 1, pre-commit, and export fail closed while recovery state is nonclean. |
| Live evals | `/wiki-eval` runs `scripts/wiki_eval.py`, the fixture-backed checks for durable files, transactions, lint, backlinks, gates, ledgers, export, stale-text sweep proof, log rotation, review due, discoverability, generated wrapper parity, schema-doc parity, entity-catalog behavior, and operational-document reachability. |
| Outcome review | `scripts/review_due.py` surfaces due `review_by` checkpoints; `workflows/maintenance/review.md` records what happened and whether confidence changes. |
| Sourcing queue | `wiki/sourcing-queue.md` tracks missing sources and evidence gaps that research, lint, or synthesis discovers. `workflows/maintenance/refresh-sourcing-queue.md` can reprioritize it when needed. |
| Approval gate | `scripts/capture_gate.py` guards analysis capture, artifact-promotion apply routes, and reviewed synthesis promotion (`--kind=synthesis`), then records approved boundaries in `scripts/capture-runs.jsonl`. |
| Synthesis ledger | `wiki/synthesis.md` orients future synthesis runs; cite source pages, not the ledger, when making claims. |
| Export | `scripts/export_wiki.py` builds a local backup that includes gitignored `raw/` sources. |
| Generated wrappers | `scripts/wiki-wrapper-contract.json` owns the shortcut manifest; `scripts/render_wiki_wrappers.py` deterministically renders `.claude/commands/` and `.codex/skills/`, which never own canonical behavior. |

---

## Cross-Referencing Rules

Use `[[filename-without-extension]]` for all internal links.

In `## Related pages`, use typed relationship labels when the relationship is clear:

<!-- parity:enum key=related-labels -->
| Label | Meaning |
|---|---|
| `Supports` | This page strengthens, evidences, or confirms the linked page |
| `Contradicts` | This page conflicts with or materially challenges the linked page |
| `Depends on` | This page requires the linked page to be understood or true |
| `Derived from` | This page was created from, generalized from, or synthesized out of the linked page |
| `Part of` | This page is a component of the linked larger system, project, or framework |
| `Related` | Meaningful connection, but no stronger typed relationship fits |

Format each item as `- Label: [[page]]`. The canonical label set is enforced by `RELATED_LABELS` in `scripts/wiki_lint_contract.py`; `AGENTS.md` and `wiki/SCHEMA.md` document the same six labels. Do not invent new labels casually. To add one, update `RELATED_LABELS` and this table together; the `schema-docs` eval suite enforces the duplicated vocabulary. Existing untyped related links remain valid, but new or touched pages should prefer labels where they add signal.

When stating a specific fact, append `(source: [[source-filename]])`. When stating an opinion or inference, prefix with `Inference:` or `Hypothesis:`.

---

## Key Reference Files

| File | Purpose |
|---|---|
| `wiki/domain.md` | Organization name, scope, active entity types, raw taxonomy, setup status |
| `wiki/index.md` | Master catalog: read for browsing, research, promotion, explicit lookup, and ingest link/index steps; not startup context |
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
| `raw/README.md` | Source-artifact handling note for the ignored `raw/` corpus |
| `scripts/raw-buckets.json` | Tracked raw bucket taxonomy read by Tier-1 lint |
| `scripts/entity-catalog.json` | Governed entity folders, types, preset membership, and authoring semantics; consumed through `scripts/wiki_entity_catalog.py` |
| `scripts/plan_wiki_setup.py` | Read-only JSON plan for preset selection, safe folder changes, blocked removals, and migration advisories |
| `scripts/lint-adjudications.json` | Settled Tier-2 lint judgments with reasons and dates; lint suppresses what it lists |
| `scripts/current-state-owners.json` | Optional, strict registry of current-state owner pages; ships disabled and empty |
| `scripts/wiki_current_state.py` | Typed owner-registry loader, validator, and current-state drift evaluator used by lint |
| `scripts/wiki_evidence.py` | Typed production seam for exact evidence samples, verifier batches, and run validation |
| `scripts/build_evidence_sample.py`, `scripts/build_verifier_batches.py`, `scripts/verify_evidence_run.py` | Thin agent-neutral CLI adapters for the sampled evidence workflow |
| `scripts/wiki_backup_receipt.py`, `scripts/backup_state.py` | Destination-redacted verified-upload receipt and nonblocking freshness reporter; the local receipt is gitignored |
| `scripts/capture-runs.jsonl` | Append-only logical approval ledger installed through stable-lock atomic full-file replacement, never in-place append |
| `scripts/wiki-wrapper-contract.json` | Strict machine authority for the seven generated Claude and Codex wrappers; render with `scripts/render_wiki_wrappers.py` and check with `scripts/check_wrapper_parity.py` |
| `scripts/check_schema_doc_parity.py` | Verifies the full schema catalog table against `scripts/entity-catalog.json` and duplicated vocabularies against `scripts/wiki_lint_contract.py` constants |
| `scripts/document-reachability.json` | Declares operational document roots, routed directories, exclusions, and intentional standalone documents |
| `scripts/check_document_reachability.py` | Follows Markdown links from declared roots and rejects missing routes or unreachable operational documents |
| `scripts/check_discoverability.py` | Scope-aware AST check for typed, distinctive production interfaces; eval and fixture findings remain advisory |
| `.wiki-transactions/` | Gitignored, non-disposable recovery authority for log rotation and backlink rebuild; use `scripts/wiki_transactions.py status`, `recover`, or `diagnose`, and never delete it to clear a gate |
| `scripts/fixtures/` | Fixture data for live tooling evals |

## Durable File And Transaction Boundary

`scripts/_durable_files.py` owns stable advisory locks, complete writes, file and directory synchronization, same-directory replacement, and installed-byte verification. `scripts/_transaction_contract.py` owns transaction vocabulary, path confinement, and journal validation; `scripts/_file_transactions.py` remains the stable execution and recovery facade used by log rotation and backlink rebuilds. Existing byte-identical rotation archives are read-only transaction guards rather than rewritten targets.

An absent or verified-clean `.wiki-transactions/` root is safe. Any unpublished preparation, unfinished cleanup, nonterminal transaction, changed guard, conflict, corruption, or unknown state blocks mutation, Tier 1, pre-commit, and export. Recovery follows only the recorded deterministic policy; third-party bytes are preserved as a conflict rather than overwritten.

## Capture Boundary

The wiki separates deterministic capture approval from prose judgment:

- `scripts/capture_approval_policy.py` owns route classification and destination confinement; `scripts/capture_approval_records.py` owns exact durable record construction; `scripts/capture_gate.py` composes them into the stable CLI and output contract.
- Workflow prose decides quality: what belongs in the page, which evidence matters, how links should be written, and how contradictions should be handled.
- Do not replace route-specific workflows with scripts unless the behavior is objectively checkable.

## Tooling Module Boundaries

Executable tooling keeps stable CLI facades while assigning each reusable concept one owner:

- `scripts/lint.py` only parses arguments and renders reports. `wiki_lint_contract.py` owns shared vocabulary and the typed `PageContext`; `wiki_lint_frontmatter.py` owns frontmatter/provenance parsing; `wiki_lint_repository_checks.py` owns repository-wide invariants; `wiki_lint_page_checks.py` owns the typed ordered page-rule registries; `wiki_lint_tier1.py` composes hard failures; and `wiki_lint_signals.py` owns `Tier2PageFacts`, `Tier2Context`, the typed signal registry, and review-candidate composition.
- `scripts/wiki_current_state.py` is the sole production owner for current-state registry parsing and drift semantics. Tier 1 validates opt-in configuration; `wiki_lint_signals.py` adapts its already-parsed corpus context into nonblocking findings.
- `scripts/wiki_evidence.py` is the stable evidence-fidelity interface. The build/verify scripts are CLI adapters; private modules own artifact schemas and exact validation, and verifier agents consume rendered prompts without model/provider coupling.
- `scripts/wiki_backup_receipt.py` owns verified-backup receipt schema, redaction, hashing, atomic persistence, and freshness classification. `export_wiki.py` stamps only after remote size and checksum verification; `backup_state.py` only reports.
- Literal `__all__` declarations identify intentional cross-module interfaces. Local imports must use names in the owner's declared interface, including module-qualified uses. Class constructors follow the same boundary; when `__all__` is absent, normal underscore visibility applies. Internal registry callbacks are not public merely because Python requires a top-level definition. The private transaction modules collaborate through one named execution contract instead of importing individual private helpers.
- Search-facing function names include their concept, such as `build_backlink_rebuild_plan`, `build_log_rotation_plan`, `collect_due_reviews`, and `contains_approval_path_placeholder`; do not add generic compatibility aliases.
- Run `python3 scripts/check_discoverability.py` after changing production interfaces. Production blockers fail; test and fixture observations are printed separately and remain advisory.

## Layer Architecture (L0-L4)

Every file in this project sits at one of five layers, defined by when it loads relative to a task. Knowing the layer tells a downstream agent whether to read a file unconditionally, on task entry, or only when a specific reference is needed.

| Layer | When loaded | Files |
|---|---|---|
| **L0** | Always: orientation and routing | `AGENTS.md` (`CLAUDE.md` is a pointer for Claude agents), `wiki/domain.md` status check, `CONTEXT.md` |
| **L1** | Route entry: selected by `CONTEXT.md` | `workflows/<workspace>/CONTEXT.md`, `SETUP.md`, or `wiki/index.md` only for browsing |
| **L2** | Task workflow: selected by route entry | `workflows/maintenance/*.md` and any task-specific workflow file named by the L1 route |
| **L3** | Per task: stable reference, loaded on demand | `REFERENCES.md`, `wiki/index.md`, `wiki/SCHEMA.md`, `wiki/glossary.md`, `wiki/primer.md`, `wiki/design-notes.md`, `wiki/contradictions.md`, `wiki/sourcing-queue.md`, `wiki/overview.md` |
| **L4** | During work: content read or written | `wiki/log.md`, `wiki/<entity>/*.md`, `raw/*` |

Loading principle: an agent starting a task should load L0, use `CONTEXT.md` to choose the route, then open only the routed workflow's Load / Skip list. Pull L3 references only when the workflow calls for them. `wiki/index.md` is on-demand for browsing, research, promotion, explicit lookup, and ingest link/index steps; it is not startup context.
