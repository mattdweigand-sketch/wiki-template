# Wiki Eval

Run this workflow when the task is to verify the wiki system itself. It covers scripts, durable writes, exact capture transactions, gates, ledgers, backlinks, backup and restore, evidence runs, stale-text proof, wrapper parity, schema data, document routing, and Tier-1 lint. The `SUITES` registry in `scripts/wiki_eval.py` is the full list.

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

Approved multi-file capture uses the recovery authority under `.wiki-transactions/`. The transaction CLI is the operator surface:

```bash
python3 scripts/wiki_transactions.py status
python3 scripts/wiki_transactions.py recover
python3 scripts/wiki_transactions.py diagnose <transaction-id>
```

`status` is read-only and does not create the authority. `recover` applies only the deterministic recorded policy. `diagnose` reports paths, states, and hashes without dumping file contents. Never delete or empty `.wiki-transactions/` to make a guard pass. A clean interrupted transaction can be recovered; a conflict or corrupt record is preserved for diagnosis. Tier 1, pre-commit, and export fail closed while the authority is nonclean.

The `durable-files` suite checks guarded atomic replacement. The `transactions` suite checks the capture-only recovery path. Backlink and log rotation suites check interruption, concurrent edits, and safe reruns without transaction journals.

Do not copy these repo-local skills into `~/.agents/skills/`. Identical personal installs can create duplicate skill entries; if duplicates appear, keep the tracked repo-local copy and remove the personal duplicate by hand.

## Governed Schema Data

`scripts/entity-catalog.json` owns entity folders, frontmatter types, and authoring semantics. `scripts/schema-vocabularies.json` owns confidence, source type, authority, and related-link vocabularies. Docs point to these records instead of copying their full lists. The `entity-catalog` and `schema-vocabularies` suites validate both records and their loaders.

## Operational Document Reachability Contract

`scripts/document-reachability.json` declares graph roots, operational directories, exclusions, and intentional standalone documents. `scripts/check_document_reachability.py` follows local Markdown links only and fails on missing targets or operational documents that no declared route reaches. Change the manifest only when routing scope changes; do not add an obsolete document as standalone merely to silence the check.

## Load / Skip

- **Load:** `scripts/wiki_eval.py`; wrapper files when the task concerns wrappers; `scripts/wiki_transactions.py` when the task concerns recovery state; the entity catalog and schema vocabulary files when the task concerns schema; the document reachability files when the task concerns routing; and any failing suite output.
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
