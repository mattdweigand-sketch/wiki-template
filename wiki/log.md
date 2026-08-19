---
title: Activity Log
type: log
created: 2026-05-17
updated: 2026-08-19
---

# Activity Log

Append-only history of ingest, lint, query, and decision-capture sessions. Newest entries on top.

---

## [2026-08-19] maintenance | repository rename

Change: Renamed the GitHub repository to `wiki-template` and updated the clone URL in the agent setup prompt.
Reason: Give the reusable template a direct, purpose-specific repository name.
Rejected alternative: Keep the refactor-era repository name and rely on GitHub redirects, which would leave new-clone guidance stale.
Accepted tradeoff: Existing clones and links may continue through GitHub's redirect until their `origin` URLs are updated.
Validation: PASS - live repository URL scan; full `python3 scripts/wiki_eval.py`; Tier-1 lint; `git diff --check`.

---

## [2026-08-19] maintenance | adoption review polish

Change: Made the direct-import discoverability regression path-specific and removed the transaction facade's nine method aliases so production and evaluation call sites use the named execution contract directly.
Reason: Ensure each adversarial import case proves its own detection path and keep the transaction module boundary visible instead of recreating the former private helper surface under local aliases.
Rejected alternative: Keep the aliases or restore them for evaluation convenience, which would preserve a duplicate internal API and hide the contract at its consumer sites.
Accepted tradeoff: Transaction call sites are longer, but their dependency is explicit and owned by one typed seam.
Validation: PASS - discoverability and transaction suites on Python 3.9.25, 3.11.15, and 3.12.13; full `python3 scripts/wiki_eval.py`; clean transaction authority; `git diff --check`.

---

## [2026-08-19] maintenance | runtime and interface contract hardening

Change: Made the documented `python3` tooling compatible with Python 3.9+, added the runtime version to eval output and a Python 3.9/3.11 CI matrix, extended discoverability enforcement to implicit public classes and declared local import edges, repaired the live lint interfaces, and replaced private transaction-helper imports with one named internal execution contract.
Reason: Close the two remaining adoption findings: the user-facing runtime promise failed on Python 3.9, and declared module boundaries could be bypassed without failing the discoverability gate.
Rejected alternative: Require Python 3.11+ or publish every private transaction helper through `__all__`; both would make adoption easier mechanically while weakening the template's low-friction setup or its internal boundary.
Accepted tradeoff: CI runs the full suite twice, and explicit `__all__` owners must keep local consumers synchronized; evaluation-only internal imports remain advisory.
Validation: PASS - full `python3 scripts/wiki_eval.py` on Python 3.9.25 and 3.11.15 (780 checks each); adversarial implicit-class, direct-import, and qualified-import discoverability cases; schema-doc parity; wrapper parity; Tier-1 lint; `git diff --check`.

---

## [2026-08-19] maintenance | parallel-refactor follow-up

Change: Folded the strongest targeted improvements from an independently implemented discoverability refactor into the modular tooling: renamed the due-review collector, typed Tier-1 and Tier-2 contexts and registries, removed confirmed dead lint remnants, and extended the discoverability check to reject generic collection interfaces and untyped explicitly exported constructors.
Reason: Preserve the structural benefits of the modular refactor while adopting the smaller implementation's sharper contributor-facing types, naming, and cleanup.
Rejected alternative: Replace the modular refactor with the smaller monolithic patch, which would reduce the immediate diff but restore the 2,500-line lint module and remove repository-native regression enforcement.
Accepted tradeoff: The discoverability contract is stricter and exported context constructors must remain fully typed; fixture and test observations remain advisory.
Validation: PASS - focused discoverability, review-due, and lint evals; full `python3 scripts/wiki_eval.py`; schema-doc parity; wrapper parity; Tier-1 lint; `git diff --check`.

---

## [2026-08-19] maintenance | discoverable tooling interfaces

Change: Refactored the deterministic tooling behind its stable command-line surfaces: split lint rules into concept-owned modules, separated capture approval policy from durable approval records, separated transaction contracts from execution and recovery, replaced generic helper names with concept-specific names, strengthened boundary types, and added a repository-native discoverability check and eval suite.
Reason: Make the tooling easier for people and agents to navigate, search, and change safely without altering the wiki's public workflows or command surface.
Rejected alternative: Rebuild the repository wholesale, which would have expanded the migration surface and risked behavioral drift across approval, recovery, lint, and export contracts.
Accepted tradeoff: The tooling now spans more focused files, and interface changes carry an additional discoverability check; stable CLI facades preserve the existing operator experience.
Validation: PASS - full `python3 scripts/wiki_eval.py`; `python3 scripts/check_schema_doc_parity.py`; `python3 scripts/check_wrapper_parity.py`; `python3 scripts/lint.py --tier1`; discoverability checks; `git diff --check`.

---

## [2026-08-17] maintenance | recoverable writes and generated wrapper contract

Change: Ported the template-safe durability and wrapper architecture from the maintained personal wiki: stable-lock atomic approval-ledger replacement, recoverable multi-file transactions for backlink rebuilds and log rotation, fail-closed transaction guards in Tier 1, pre-commit, and export, an operator status/recover/diagnose CLI, adversarial durability evals, and a manifest that deterministically renders both wrapper surfaces.
Reason: Bring `wiki-solo` up to date on the two approved architectural improvements without importing personal corpus content or configured-domain behavior.
Rejected alternative: Cherry-pick or mirror the source repository broadly, which would also import evidence-fidelity, transcript-specific, personal backup, and corpus policies outside this port's scope.
Accepted tradeoff: The template gains recovery-state and eval code weight, and wrapper edits must now go through the manifest or renderer instead of being made directly.
Validation: PASS - `python3 -m py_compile scripts/*.py`; `python3 scripts/wiki_transactions.py status`; targeted durable-files, transactions, gate, rebuild, rotate-log, export, lint, and wrapper-parity suites; wrapper render check; schema-doc parity; full `python3 scripts/wiki_eval.py`; Tier-1 and full lint; discoverable-code check; private-marker scan; `git diff --check`.

---

## [2026-07-14] maintenance | template parity refresh and research-overlay removal

Change: Ported the reusable mechanics committed in the maintained personal wiki after the prior template checkpoint, including shared repository-path containment, Markdown parser hardening, fail-closed approval-ledger writes, stronger lint and eval coverage, governance-document audit routing, workflow simplification, and export symlink/checksum verification. Removed the entire optional wiki-research overlay from the active template surface: wrappers, workflow, runtime, eval suite, owner registry, routes, and documentation references.
Reason: Keep `wiki-solo` current as a safe unconfigured template while intentionally offering only the ordinary wiki question-answering workflow.
Rejected alternative: Mirror the personal wiki tree literally, which would import private corpus content, configured-domain assumptions, and the research overlay this template no longer supports.
Accepted tradeoff: Historical log entries remain append-only and still describe when the removed overlay was previously added; every active surface is free of it.
Validation: PASS - full `python3 scripts/wiki_eval.py`; full `python3 scripts/lint.py`; `python3 scripts/check_wrapper_parity.py`; `python3 scripts/check_schema_doc_parity.py`; `python3 scripts/export_wiki.py --dry-run --date 2026-07-14`; `python3 -m py_compile scripts/*.py`; active-surface research-reference scan; private-marker scan; `git diff --check`.

---

## [2026-07-09] maintenance | wiki-research template port

Change: Ported the source-wiki deep-research mechanics into `wiki-solo`: renamed the public overlay and wrappers from `wiki-swarm` to `wiki-research`, added the claim-ledger/raw-confirmation runtime, registered the `research` eval suite, and updated root/workflow docs to the new command surface.
Reason: Keep the template aligned with the maintained wiki research contract while preserving `wiki/domain.md` as `status: unconfigured` and avoiding corpus-specific pages, property ingests, or configured-domain assumptions.
Rejected alternative: Cherry-pick the source commits directly, which failed against the template-specific surfaces and would have pulled in non-template history. The port was applied manually from the mechanics files, then sanitized with a private-marker scan.
Accepted tradeoff: The template now carries the stricter high-rigor research packet contract and legacy `wiki-swarm` tombstone behavior, but configured wikis still own their own current-state owner registry and raw-source corpus.
Validation: PASS - `python3 -m py_compile scripts/*.py`; `python3 scripts/wiki_eval.py --suite research` (113 passed); `python3 scripts/check_wrapper_parity.py`; `python3 scripts/wiki_eval.py --suite wrapper-parity`; full `python3 scripts/wiki_eval.py`; `python3 scripts/validate_capture_runs.py`; `python3 scripts/check_schema_doc_parity.py`; `python3 scripts/export_wiki.py --dry-run --date 2026-07-09`; `python3 scripts/lint.py --tier1`; full `python3 scripts/lint.py`; private-marker scan over changed files; `git diff --check`.

---

## [2026-07-09] maintenance | personal-wiki feature parity port

Change: Ported the template-safe pieces of the latest personal-wiki mechanics: operating-rule refinement clauses in `workflows/maintenance/artifact-promotion.md`, a general `unconsumed_sources` Tier-2 lint signal with eval coverage, and wiki-swarm scope-retention/runtime raw-file-cap guardrails.
Reason: Keep `wiki-solo` aligned with the maintained personal wiki architecture without importing personal corpus content, personal entity assumptions, source-page wiring cleanup, or source-repo backup policy.
Rejected alternative: Copy the personal wiki commits directly, which would pull in personal knowledge-layer pages and corpus-specific source cleanup that do not belong in the template.
Accepted tradeoff: The template carries the reusable mechanics and deterministic guards; configured wikis still decide which source pages need owner-page links or adjudication.
Validation: PASS - `py_compile`; `python3 scripts/wiki_eval.py --suite lint` (160 passed); `python3 scripts/wiki_eval.py --suite wiki-swarm` (46 passed); full `python3 scripts/wiki_eval.py`; `python3 scripts/validate_capture_runs.py`; `python3 scripts/check_wrapper_parity.py`; `python3 scripts/check_schema_doc_parity.py`; `python3 scripts/export_wiki.py --dry-run --date 2026-07-09`; `python3 scripts/lint.py --tier1`; full `python3 scripts/lint.py`; private-marker scan; `git diff --check`.

---

## [2026-07-04] maintenance | root-doc congruence corrections

Change: Corrected the setup replacement table so the `CONTEXT.md` heading uses the actual hyphenated title shape. Reviewed historical log references that mention a retired `scripts/sync_codex_skills.py` helper and an older "13 default entity types" phrasing; left those historical entries in place because current active docs now point to 12 schema entity types and `scripts/check_wrapper_parity.py` as the live wrapper contract.
Reason: Keep active setup guidance literal and current without rewriting append-only maintenance history.
Rejected alternative: Edit older log entries in place, which would make the historical record less faithful.
Accepted tradeoff: A current correction entry makes the active contract clear while preserving older change records as dated history.
Validation: PASS - `lint.py --tier1`, full `lint.py`, `validate_capture_runs.py`, `check_wrapper_parity.py`, full `wiki_eval.py`, and `git diff --check`.

---

## [2026-07-04] maintenance | stale-status hardening parity

Change: Ported the template-safe stale-status hardening from the personal wiki into `wiki-solo`: glossary volatile-status lint, structured stale-text sweep proof for new ingest logs, a read-only stale-text sweep helper, eval coverage, command-shape validation, and lint workflow doctrine for when signals should remain Tier 2.
Reason: Keep the public template aligned with the maintained personal wiki mechanics while avoiding personal corpus content, configured-domain assumptions, current-state registries, or property-specific checks.
Rejected alternative: Copy the personal repo content or promote broad stale/current-state judgment into hard deterministic gates.
Accepted tradeoff: The helper and proof schema make stale sweeps auditable, while semantic completeness remains a review judgment.
Validation: PASS - `py_compile`, targeted stale-text and lint evals, full `wiki_eval.py`, Tier-1 lint, full lint, approval-ledger validation, wrapper parity, export dry-run for 2026-07-04, and `git diff --check`.

---

## [2026-07-03] maintenance | personal mechanics parity refactor

Change: Ported template-safe operational mechanics from the personal wiki into `wiki-solo`: shared parser and backlink hardening, unified capture workflow, consolidated capture/synthesis gate behavior, wrapper parity checking, log rotation workflow and evals, refreshed ledger validation, and deterministic lint signals for sourcing-queue counts, log rotation, recompile candidates, review checkpoints, synthesis due, and dead adjudications.
Reason: Keep the template aligned with the maintained personal wiki operating layer without copying personal corpus content, personal entity assumptions, backup policy, corpus-mix checks, current-state registries, or property/home-record mechanics.
Rejected alternative: Copy the personal repo wholesale or keep `wiki-solo` on the older duplicate-global-wrapper and split-capture workflow model.
Accepted tradeoff: Retained template defaults and generic export/setup behavior; personal-only mechanics remain out of scope unless they are later generalized through an explicit template decision.
Validation: PASS - `py_compile`, full `wiki_eval.py`, Tier-1 lint, full lint, approval-ledger validation, export dry-run for 2026-07-03, and `git diff --check`.

---

## [2026-06-26] maintenance | source-wiki enhancement port

Change: Ported template-safe source-wiki improvements into `wiki-solo`: analysis capture now stages drafts with `--path`, review due pages are routable from root docs, schema provenance/current-state rules are explicit, wrapper parity is documented in the eval workflow, lint eval coverage is expanded, rebuild eval reporting uses the shared result helper, and root meta pages now include starter templates for contradictions, sourcing gaps, glossary terms, design notes, and synthesis.
Reason: The public template should capture reusable mechanics and operating judgment from the source wiki without importing source-only content, configured-entity assumptions, or source-repo-specific export behavior.
Rejected alternative: Copy source-wiki folders, source buckets, current-state registries, source-specific lint rules, ledger history, or source-repo export semantics.
Accepted tradeoff: Keep the changes generic and mechanics-focused; richer domain behavior remains setup-driven or an explicit future schema/tooling decision.
Validation: PASS - `rebuild_referenced_by.py`, targeted lint eval, rebuild eval, wrapper parity, full `wiki_eval.py`, Tier-1 lint, full lint, approval-ledger validation, export dry-run, and `git diff --check`.

---

## [2026-06-25] maintenance | source-repo workflow calibration port

Change: Ported the template-safe parts of the recent source-repo workflow improvements into `wiki-solo`: memo-first synthesis with explicit no-change outcomes, Good/Bad calibration examples for ingest/research/artifact-promotion, and an operating-rule norm to record reason, one rejected alternative, and accepted tradeoff.
Reason: Future agents need concrete calibration at the point of execution, not only abstract routing rules.
Rejected alternative: Copy the source diffs directly, including domain-specific lint, source-repo backup target, and source-repo content.
Accepted tradeoff: Keep the port narrow and generic; the template gains reusable workflow judgment while excluding private content, private domain routing, and source-repo export policy.
Validation: PASS - `rebuild_referenced_by.py`, Tier-1 lint, full lint, approval-ledger validation, wrapper parity, export dry-run, full `wiki_eval.py`, targeted private-content scan, and `git diff --check`.

---

## [2026-06-16] maintenance | promotion apply phase clarity

Change: `workflows/maintenance/artifact-promotion.md` now states that an apply route uses `--phase accepted` (in the mode-description paragraph and in step 5). The direct `capture_gate.py` path no longer leaves the approval-triggering phase unspecified.
Reason: Ported from the personal wiki audit. `--phase drafting` derives `chat-only` and exits 0, so an agent that picked the wrong phase for an apply could skip the promotion approval gate. No other audit finding transferred: the operational eval suite already covers wrapper sync, the Codex synthesize skill already names the synthesis gate, the log is correctly newest-on-top, and the content-level fixes have no template content to touch.
Validation: PASS — Tier-1 lint, full `wiki_eval.py`, and `git diff --check`.

---

## [2026-06-15] maintenance | audit cleanup and operational coverage

Change: Cleaned up root-accountability audit findings: research chat-only answers no longer require log writes, promotion apply intent excludes ordinary ingest/commit requests, capture workflows update the index for new pages, setup/domain docs use the correct 13 default entity types, export verification checks promised coverage and excludes `.agents/`, duplicate global Codex skill removal refuses divergent copies, and operational evals now cover export, promotion, sync, and approved ledger validators.
Reason: The template should keep deterministic checks clean, avoid unintended writes, and preserve generic wrapper/export boundaries without relying on manual validation.
Validation: PASS — Tier-1 lint, full wiki eval including operational helpers, export dry-run, ledger validators, py_compile, temporary `CODEX_HOME` duplicate-skill checks, and `git diff --check`.

---

## [2026-06-15] maintenance | command-surface refactor alignment

Change: Aligned the template command surface with the current wiki operating model: repo-local Codex skills are canonical, duplicate global `wiki-*` skills are detected and removable, `/wiki-lint` authorizes the full lint workflow with verifier evidence checks by default, and artifact promotion now states the no-mid-draft/no-context-only write-intent safeguards.
Reason: The template should preserve the recent workflow-control improvements without copying personal wiki content or personal entity assumptions.
Validation: PASS — `py_compile`, Tier-1 lint, capture/synthesis ledger validators, export dry-run, temp `CODEX_HOME` duplicate-skill detect/remove check, full wiki eval, and `git diff --check`.

---

## [2026-06-15] maintenance | structured command guardrails

Change: Ported structured approval ledgers, capture/synthesis ledger validators, the synthesis approval gate, export zip builder, and updated command workflow docs and wrappers.
Reason: The template should keep deterministic approval and export boundaries in scripts while preserving generic, repo-local workflow judgment.
Validation: PASS — capture/synthesis ledger validators, gate evals, export dry-run, full wiki eval, lint, temp `CODEX_HOME` Codex skill sync check, `py_compile`, and `git diff --check`.

---

## [2026-06-13] maintenance | tracked Codex skill wrappers

Change: Added tracked `.codex/skills/wiki-*` Codex skill wrappers, documented the Claude/Codex wrapper split, and added `scripts/sync_codex_skills.py` for installing the tracked Codex wrappers into a user's local Codex skill directory.
Reason: General users should be able to use `/wiki-ingest`, `/wiki-capture`, `/wiki-promote`, `/wiki-lint`, `/wiki-synthesize`, and `/wiki-export` in Codex without relying on untracked local skill files.
Validation: PASS — temp `CODEX_HOME` sync plus `--check`, `py_compile`, Tier-1 lint, full wiki eval, and `git diff --check`.

---

## [2026-06-08] maintenance | agent-neutral promotion shortcut

Change: Added an agent-neutral promotion audit workflow, documented it in root routing, and clarified the README boundary between analysis and promotion.
Reason: Promotion should have a convenient entrypoint without making `.claude/commands/` canonical, and readers should understand that analysis is a saved answer while promotion is a routing decision for ambiguous durable artifacts.
Validation: PASS — shortcut audit mode, apply-gate approval path, `py_compile`, backlink rebuild, Tier-1 lint, provider manifest validation, full wiki eval, and `git diff --check`.

---

## [2026-06-08] maintenance | README promotion workflow

Change: Simplified README usage sections for reusable-output promotion, image/screenshot source ingest, and save/review thresholds.
Reason: The README should explain the agent-agnostic user-facing routes without command-heavy route tables. Detailed route-policy, lint, approval, visual-evidence, and tool-shortcut mechanics stay in the workflow docs.
Validation: PASS — doc-audit loop, Tier-1 lint, full wiki eval, markdown-link audit, and `git diff --check`.

---

## [2026-06-08] maintenance | doc-refactor alignment

Change: Audited root, setup, reference, source, research, and maintenance docs against the template-modernization refactor.
Fixes: Aligned default entity-type counts with `wiki/SCHEMA.md`; corrected moved contradiction and sourcing-queue paths; updated research and root capture-gate instructions to use `scripts/capture_gate.py` with required route arguments; replaced a stale harness PRD pointer with the live modernization spec.
Validation: PASS — `rebuild_referenced_by.py`, `lint.py --tier1`, `wiki_validate_provider_manifest.py`, full `wiki_eval.py`, markdown-link audit, and `git diff --check`.

---

## [2026-06-06] maintenance | typed related-page labels

Change: Added lightweight typed labels for `## Related pages` links while preserving ordinary `[[wikilink]]` syntax.
Allowed labels: `Supports:`, `Contradicts:`, `Depends on:`, `Derived from:`, `Part of:`, `Related:`.
Validation: PASS — backlink rebuild completed; `python3 scripts/lint.py` and `git diff --check` passed.

---

## [2026-05-17] template initialized

Template state. Awaiting domain configuration — see [`SETUP.md`](../SETUP.md) and [`domain.md`](domain.md).
