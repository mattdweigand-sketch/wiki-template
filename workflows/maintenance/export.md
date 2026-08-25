---
name: wiki-export
description: Use this workflow when the user says "export the wiki" or wants a complete private backup, with an optional copy to an explicitly approved private off-device destination.
---

# Export Workflow

## Load / Skip

- **Load:** nothing beyond this file. The export is mechanical; no wiki content needs to be read.
- **Skip:** all wiki pages, raw sources, other task files.

## Why this exists

`wiki-export` builds one verified private backup of the complete local wiki tree.

## Steps

1. From the repo root, build and verify the zip into `tmp/` (gitignored), stamped with today's date:

   ```bash
   python3 scripts/export_wiki.py --date YYYY-MM-DD
   ```

   This includes every regular file under the repo root except generated `wiki-export-YYYY-MM-DD.zip` archives outside `raw/`. Wiki pages, local-only raw sources, workflows, scripts, wrappers, CI, Git history, local settings, other scratch files, deliverables, and any existing backup receipt remain included. A source artifact under `raw/` remains included even when its filename matches the export pattern. `BACKUP-MANIFEST.json` binds the exact sorted member set, sizes, hashes, POSIX permission modes, creation time, and raw-artifact manifest hash; it does not list itself. `--date` accepts only a real ISO `YYYY-MM-DD` value before any output path is created. The export refuses any symlink in the tree and any nonclean `.wiki-transactions/` state.

2. If you need to inspect before building, run:

   ```bash
   python3 scripts/export_wiki.py --dry-run --date YYYY-MM-DD
   ```

   Verify or restore an existing archive offline with:

   ```bash
   python3 scripts/restore_wiki.py verify <archive.zip>
   python3 scripts/restore_wiki.py restore <archive.zip> <absent-destination>
   ```

   Restore refuses an existing destination, validates before extraction, restores file and directory permission modes, runs restored-tree checks, flushes restored files and directories plus the destination parent, and atomically installs only the complete verified directory. It restores included Git history without running Git. Version 1 and 2 backups remain supported. New version 3 backups bind file and directory modes in the manifest. Verification is portable. Restore requires macOS or Linux because other supported Python platforms do not expose the atomic no-replace directory rename this safety contract needs.

3. Report the absolute path to the zip. Do not copy it off-device unless the user explicitly approves a private backup destination.

4. An optional private off-device backup copy uses `rclone` and requires an explicit target. Nothing is hardcoded into the template. A first-time Google Drive backup can initialize the user's local `rclone` remote and request browser or terminal auth:

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

   The script runs `rclone copyto`, verifies the remote byte size with `rclone lsl`, verifies content identity with `rclone md5sum`, and leaves credentials in the user's local `rclone` config. Only after both checks pass does it atomically update the gitignored `scripts/backup-receipt.json`. The receipt stores a UTC verification time, streamed SHA-256 content hash, byte count, and an opaque hash of the destination; it contains no provider, account, path, or URL. A local-only backup or failed remote verification never advances it. Do not commit credentials, tokens, user-specific targets, or the local receipt.

   Report the optional freshness state at any time without turning it into a gate:

   ```bash
   python3 scripts/backup_state.py
   ```

   Missing, invalid, stale, and future-dated receipts are advisories. A fresh clone intentionally reports no verified backup rather than shipping a false success claim.

5. No `wiki/log.md` entry. The export changes no wiki content; the zip in `tmp/` is a disposable artifact until the user moves it.

## Privacy

The archive may contain source documents, credentials, local settings, deliverables, scratch files, and Git history. It is a private backup, not a sharing artifact. Do not email, publish, or copy it to a public or shared destination. Passing `--upload-target` approves only the named private backup destination for that command invocation.
