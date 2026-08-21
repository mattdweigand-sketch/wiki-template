# Wiki Eval

Run this workflow when the task is to verify the wiki system itself: scripts, durable file updates, recoverable transactions, gates, ledgers, backlink rebuilds, export and verified-backup receipt behavior, exact evidence-fidelity runs, optional current-state ownership, stale-text sweep proof, discoverability, wrapper parity, schema-doc parity, entity-catalog behavior, document reachability, and the deterministic Tier-1 gate. The `SUITES` registry in `scripts/wiki_eval.py` is the authoritative list of what runs.

The tooling supports Python 3.9 and newer. The eval runner prints the exact runtime version in its first line, and CI runs the full checks on Python 3.9 and 3.11 so the user-facing `python3` commands retain that compatibility contract.

This is different from `wiki-lint`: lint checks wiki content; eval checks the tools that check and protect the wiki.

## Wrapper Surface Contract

The live convenience surfaces are `.claude/commands/wiki-*.md` and `.agents/skills/wiki-*/SKILL.md`. `scripts/wiki-wrapper-contract.json` is the sole wrapper-name, description, route, and command-hint authority. The human-facing name lists in `AGENTS.md` and the README command table must match it.

Canonical procedure belongs in `workflows/`. A wrapper is a deterministic render: canonical routing paths plus at most one `scripts/*.py` command hint. Deleting wrapper folders does not remove the underlying wiki workflow; it only removes that agent surface's shortcut.

Use `python3 scripts/render_wiki_wrappers.py --render` after changing the manifest or renderer. `python3 scripts/render_wiki_wrappers.py --check` and `python3 scripts/check_wrapper_parity.py` enforce the contract; the `wrapper-parity` suite runs adversarial fixtures so the checks cannot go vacuous:

- both wrapper surfaces cover exactly the manifest names
- every tracked wrapper is byte-for-byte equal to the current manifest render
- every manifest workflow path exists and every optional command hint names a real `scripts/*.py` file
- `AGENTS.md` and the README command table expose exactly the same shortcut set

Do not hand-edit generated wrappers. Change canonical procedure in `workflows/`; change wrapper metadata or routing in the manifest; change output structure in the renderer.

## Durable Update Contract

Approved ledger writes use a stable sidecar lock and atomic full-file replacement. Backlink rebuilds and log rotations use the shared recoverable transaction authority under `.wiki-transactions/`. The transaction CLI is the operator surface:

```bash
python3 scripts/wiki_transactions.py status
python3 scripts/wiki_transactions.py recover
python3 scripts/wiki_transactions.py diagnose <transaction-id>
```

`status` is read-only and does not create the authority. `recover` applies only the deterministic recorded policy. `diagnose` reports paths, states, and hashes without dumping file contents. Never delete or empty `.wiki-transactions/` to make a guard pass. A clean interrupted transaction can be recovered; a conflict or corrupt record is preserved for diagnosis. Tier 1, pre-commit, and export fail closed while the authority is nonclean.

The `durable-files` and `transactions` suites exercise atomic replacement, locking, crashes, conflicts, corruption, CLI behavior, and each fail-closed guard. The gate, rebuild, and rotate-log suites add operation-specific concurrency, fault-injection, and recovery coverage.

Do not copy these repo-local skills into `~/.agents/skills/`. Identical personal installs can create duplicate skill entries; if duplicates appear, keep the tracked repo-local copy and remove the personal duplicate by hand.

## Policy-Constant Placement Contract

A chosen-policy value (a vocabulary, threshold, enum, or registry) that a script enforces and a workflow names may live as a named constant in that script rather than a governed JSON file. Default placement is the code constant while all of these hold: it is small enough to review in a diff, exactly one script owns it, the owning workflow file names it, and eval or Tier-1 coverage exercises it.

Migrate it to a governed `scripts/*.json` file when any one of these fires:

1. Routine maintenance extends the value, so agents edit it as data.
2. A second script needs the same value.
3. Governed data such as `scripts/lint-adjudications.json` must validate against it.
4. Growth makes review, ownership, or extension materially better as JSON than as a named constant.

A migration keeps the shape of the existing registries: a `description` field naming the purpose and owning workflow, Tier-1 validation of the config shape, existing eval coverage preserved against the new source, and doc pointers updated. When a vocabulary migrates to JSON, docs point at the file rather than re-enumerating it; deliberate duplication for authoring convenience requires a parity marker.

## Schema Doc Parity Contract

Entity folders, frontmatter types, purposes, review-date expectations, authority-freshness guidance, and verification guidance are canonical in `scripts/entity-catalog.json` and consumed through `scripts/wiki_entity_catalog.py`. Other frontmatter vocabularies (`confidence`, `source_type`, `authority_kind`, `authority_freshness`, and related-page labels) are canonical in `scripts/wiki_lint_contract.py`. Duplicated enumerations in `wiki/SCHEMA.md`, `REFERENCES.md`, and `AGENTS.md` carry parity markers.

`python3 scripts/check_schema_doc_parity.py` enforces the exact 24-row catalog table and set equality at every registered enum marker, including all three related-label sites. The `schema-docs` suite runs seeded field and site drift fixtures so the checker cannot go vacuous. Ordering remains editorial; catalog row content and enum membership do not.

A new doc enumeration of a canonical vocabulary must either defer to the source by name without re-enumerating, or carry a parity marker. An unmarked enumeration is a review finding, not an allowed state. A parity marker outside a registered doc site is also a failure; register the site in `scripts/check_schema_doc_parity.py` when extending coverage.

## Operational Document Reachability Contract

`scripts/document-reachability.json` declares graph roots, operational directories, exclusions, and intentional standalone documents. `scripts/check_document_reachability.py` follows local Markdown links only and fails on missing targets or operational documents that no declared route reaches. Change the manifest only when routing scope changes; do not add an obsolete document as standalone merely to silence the check.

## Load / Skip

- **Load:** `scripts/wiki_eval.py`; `scripts/wiki-wrapper-contract.json`, `scripts/render_wiki_wrappers.py`, and `scripts/check_wrapper_parity.py` when the task concerns wrappers; `scripts/wiki_transactions.py` when the task concerns recovery state; `scripts/entity-catalog.json`, `scripts/wiki_entity_catalog.py`, and `scripts/check_schema_doc_parity.py` when the task concerns configured types or schema docs; `scripts/document-reachability.json` and `scripts/check_document_reachability.py` when the task concerns document routing; `scripts/check_discoverability.py` when the task concerns production interfaces; any failing suite output if a run fails.
- **Skip:** wiki entity pages, raw sources, unrelated workflow files, and Tier-2/Tier-3 content review.

## Steps

1. From the repo root, run:

   ```bash
   python3 scripts/wiki_eval.py
   ```

2. If it fails, inspect only the failing suite and make the narrowest fix.
3. Re-run `python3 scripts/wiki_eval.py` until it passes or a blocker is clear.
4. Run `git diff --check` before finishing when files changed.

## Failure -> Eval Escalation

When a real tool or workflow failure repeats, has high blast radius, or could silently regress, add the smallest eval fixture that would have caught it. Do not add evals for one-off judgment calls or prose taste. The eval must fail before the fix and pass after the fix; otherwise leave it as a known limitation rather than adding hollow coverage.

## Report

Report whether `wiki_eval.py` passed, which suite failed if any, what was fixed, and whether `git diff --check` passed when relevant.
