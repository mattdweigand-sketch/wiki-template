# Rotate Log

Use this workflow when `python3 scripts/lint.py` reports `log_rotation_due`.
Lint detects the oversized log; `scripts/rotate_log.py` performs the file
surgery. Do not put rotation in a git hook, cron job, or autonomous commit path.

## Load / Skip

- **Load:** `wiki/log.md`, `scripts/rotate_log.py`, and the `log_rotation_due`
  portion of `python3 scripts/lint.py` output.
- **Skip:** wiki entity pages, raw sources, backlink rebuilds, and evidence
  checks. Log rotation does not change the authored entity graph.

## Steps

1. Confirm the signal:

   ```bash
   python3 scripts/lint.py
   ```

2. Preview the cut:

   ```bash
   python3 scripts/rotate_log.py --dry-run
   ```

   The default target is intentionally below the lint threshold so the signal
   clears with headroom. Use `--target-lines N` only when there is a concrete
   reason to keep more or less recent history live.

3. Rotate:

   ```bash
   python3 scripts/rotate_log.py
   ```

   The script preserves every original log entry exactly once, cuts only at
   recognized entry headers, writes the archive under `archive/wiki-log/`, keeps
   at least the newest entry live, and appends the maintenance entry itself. It
   writes the archive first, then guards and atomically replaces the live log.

4. Verify:

   ```bash
   python3 scripts/wiki_eval.py --suite rotate-log
   python3 scripts/lint.py
   git diff --check
   ```

5. If the user explicitly asked for a commit, commit only the scoped files:
   `wiki/log.md` and the new `archive/wiki-log/*.md`. Otherwise leave the
   validated rotation uncommitted and report the changed files. A routine
   rotation touches nothing else.

## Notes

- The archive file has no frontmatter because `archive/` is outside the wiki
  entity corpus.
- Do not run `scripts/rebuild_referenced_by.py` for this task unless another
  changed file actually alters authored wiki links. `wiki/log.md` is a meta page,
  and archived logs are not wiki pages.
- **Interrupted rotation:** rerun the command. It reuses a byte-identical archive
  and completes the live-log write without creating a duplicate. A concurrent
  edit to either file is preserved and reported.
