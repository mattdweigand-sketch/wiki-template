---
name: wiki-export
description: Use this workflow when the user says "export the wiki" or wants a local corpus zip. Builds a zip of the template, wiki, and gitignored raw/ sources, with optional explicit rclone upload.
---

# Export Workflow

## Load / Skip

- **Load:** nothing beyond this file. The export is mechanical; no wiki content needs to be read.
- **Skip:** all wiki pages, raw sources, other task files.

## Why this exists

`raw/` is gitignored, so the git remote may not hold source artifacts. This export builds a local zip of the corpus and operating framework: wiki pages plus raw sources plus workflows, scripts, wrappers, CI, and top-level docs.

## Steps

1. From the repo root, build and verify the zip into `tmp/` (gitignored), stamped with today's date:

   ```bash
   python3 scripts/export_wiki.py --date YYYY-MM-DD
   ```

   This includes `wiki/`, `raw/`, `workflows/`, `scripts/` with fixtures and ledgers, `.claude/commands/`, `.codex/skills/`, `.github/workflows/`, and the top-level docs. It excludes `.git/`, `tmp/`, `deliverables/`, Claude worktrees, local Claude settings, Finder metadata, `.env`, and the local backup receipt. ZIP source artifacts are retained; only the exact output archive is excluded. `--date` accepts only a real ISO `YYYY-MM-DD` value before any output path is created. The export refuses any symlink in the tree so it cannot silently archive content from outside the repository or omit a broken link. It also refuses nonclean `.wiki-transactions/` state before creating an archive; inspect with `python3 scripts/wiki_transactions.py status` and recover or diagnose the recorded transaction instead of deleting it.

2. If you need to inspect before building, run:

   ```bash
   python3 scripts/export_wiki.py --dry-run --date YYYY-MM-DD
   ```

3. Report the absolute path to the zip. Do not upload it anywhere unless the user explicitly gives a destination.

4. Optional off-device upload uses `rclone` and requires an explicit target. Nothing is hardcoded into the template. A first-time Google Drive upload can initialize the user's local `rclone` remote and request browser or terminal auth:

   ```bash
   python3 scripts/export_wiki.py --date YYYY-MM-DD \
     --upload-target gdrive:wiki-exports/wiki-export-YYYY-MM-DD.zip \
     --init-rclone-drive gdrive
   ```

   After the remote exists, the init flag is no longer needed:

   ```bash
   python3 scripts/export_wiki.py --date YYYY-MM-DD \
     --upload-target gdrive:wiki-exports/wiki-export-YYYY-MM-DD.zip
   ```

   The script runs `rclone copyto`, verifies the remote byte size with `rclone lsl`, verifies content identity with `rclone md5sum`, and leaves credentials in the user's local `rclone` config. Only after both checks pass does it atomically update the gitignored `scripts/backup-receipt.json`. The receipt stores a UTC verification time, streamed SHA-256 content hash, byte count, and an opaque hash of the destination; it contains no provider, account, path, or URL. A local-only export or failed remote verification never advances it. Do not commit credentials, tokens, user-specific targets, or the local receipt.

   Report the optional freshness state at any time without turning it into a gate:

   ```bash
   python3 scripts/backup_state.py
   ```

   Missing, invalid, stale, and future-dated receipts are advisories. A fresh clone intentionally reports no verified backup rather than shipping a false success claim.

5. No `wiki/log.md` entry. The export changes no wiki content; the zip in `tmp/` is a disposable artifact until the user moves it.

## Privacy

The corpus may contain sensitive organization data. Do not upload, email, or share an export without explicit user approval for the destination. Passing `--upload-target` is explicit destination approval for that command invocation only.
