---
name: wiki-export
description: Use this workflow when the user says "export the wiki" or wants a complete recovery snapshot, with optional explicit rclone upload.
---

# Export Workflow

## Load / Skip

- **Load:** nothing beyond this file. The export is mechanical; no wiki content needs to be read.
- **Skip:** all wiki pages, raw sources, other task files.

## Why this exists

This export builds one verified recovery archive of the complete local wiki tree.

## Steps

1. From the repo root, build and verify the zip into `tmp/` (gitignored), stamped with today's date:

   ```bash
   python3 scripts/export_wiki.py --date YYYY-MM-DD
   ```

   This includes every regular file under the repo root. That means wiki pages, local-only raw sources, workflows, scripts, wrappers, CI, Git history, local settings, scratch files, deliverables, and any existing backup receipt. Only the exact output archive is excluded. `BACKUP-MANIFEST.json` binds the exact sorted member set, sizes, hashes, creation time, and raw-artifact manifest hash; it does not list itself. `--date` accepts only a real ISO `YYYY-MM-DD` value before any output path is created. The export refuses any symlink in the tree and any nonclean `.wiki-transactions/` state.

2. If you need to inspect before building, run:

   ```bash
   python3 scripts/export_wiki.py --dry-run --date YYYY-MM-DD
   ```

   Verify or restore an existing archive offline with:

   ```bash
   python3 scripts/restore_wiki.py verify <archive.zip>
   python3 scripts/restore_wiki.py restore <archive.zip> <absent-destination>
   ```

   Restore refuses an existing destination, validates before extraction, runs restored-tree checks, and atomically installs only the complete verified directory. It restores included Git history without running Git.

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

The archive may contain source documents, credentials, local settings, deliverables, scratch files, and Git history. Do not upload, email, or share it without explicit user approval for the destination. Passing `--upload-target` is approval for that command invocation only.
