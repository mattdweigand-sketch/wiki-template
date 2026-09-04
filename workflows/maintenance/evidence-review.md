# Claim Evidence Review

This is the independent review step inside `wiki-lint`. The linting agent orchestrates it but does not judge its own sample.

1. Create a fresh run with operating-system randomness.

   ```bash
   python3 scripts/build_evidence_sample.py --run-id YYYYMMDD-HHMMSS --count 25
   ```

2. Create one hidden `plant.json` under that run directory. Copy one sampled claim's `claim_id`, path, line number, and cited slugs. Set `schema_version` to `1`, `plant_id` to `plant-01`, and `invalid_verdict` to `VERIFIED`. Replace the text with a clear unsupported overstatement. Never place or reveal the plant in the corpus or verifier prompt.

3. Publish two or three exact batches.

   ```bash
   python3 scripts/build_verifier_batches.py \
     --run-dir tmp/evidence-check/YYYYMMDD-HHMMSS --batches 3
   ```

4. Give each prompt to a separate verifier in a fresh context. Each verifier checks only assigned item IDs against cited pages and raw closure. Save strict JSON to `verdicts/<batch-id>.json`. Valid verdicts are `VERIFIED`, `OVEREXTENDED`, `CONFLATED`, `MISMATCH`, and `NOT-FOUND`. Every item needs a decisive quote and canonical evidence paths from its captured source closure: the cited source page or its recorded raw files, never the sampled claim page itself. The whitespace-normalized quote must occur in at least one cited UTF-8 file. Binary evidence needs a captured textual excerpt. Missing, unrelated, unsafe, or invented evidence fails validation; quotation identity alone does not prove support.

5. Validate exact accounting and snapshot freshness.

   ```bash
   python3 scripts/verify_evidence_run.py \
     --run-dir tmp/evidence-check/YYYYMMDD-HHMMSS
   ```

Treat structure, snapshot, and review as separate outcomes. A caught plant does not hide a flagged real claim. Missing verdicts, altered prompts, invalid structure, a verified plant, or stale source bytes require a fresh run. Runs with older generated prompts also need fresh IDs; never rewrite scratch history to make it appear current.

Adjudicate real flags. Fix confirmed overreach by correcting the claim, confidence, or citation. Record durable false positives only when the same judgment should suppress a future lint candidate.
