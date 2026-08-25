---
name: wiki-connect
description: Optionally connect a clone to its GitHub repository and a private rclone backup destination.
---

# Connect GitHub and private backup

Use this workflow only when the user explicitly requests connection help or accepts the optional handoff from `wiki-setup`. GitHub and off-device backup are independent and optional. Run only the section the user accepted.

## Load / Skip

- **Load:** Git state through the commands below. For backup, also load [`export.md`](export.md) and `scripts/export_wiki.py` command help.
- **Skip:** wiki entity pages, raw source contents, unrelated workflows, and credential files.

## Authority and privacy

- Read-only inspection does not authorize remote creation, remote changes, authentication, pushes, archive creation, or uploads.
- Before an external change, show the exact account, repository or backup target, visibility where relevant, and command. Obtain explicit approval for that exact action.
- Never put GitHub tokens, rclone credentials, repository URLs, backup targets, or account identifiers in tracked wiki files. Git remotes belong in local `.git/config`. Authentication belongs in the user's GitHub or rclone configuration.
- A backup may contain raw sources, local settings, scratch files, deliverables, credentials, and Git history. Require confirmation that the exact destination is private before uploading.
- On authentication, command, verification, or partial-success failure, stop. Do not choose another account, repository, destination, protocol, or visibility as a fallback.

## GitHub repository

1. Inspect without writing:

   ```bash
   git branch --show-current
   git status --short
   git remote -v
   ```

2. Ask for the exact desired GitHub repository when it cannot be inferred from a user-provided URL. If creation is needed, confirm the authenticated GitHub account, repository name, and visibility. Default to private only as a proposal. Do not create it without approval.
3. Classify the current state:
   - If `origin` already names the desired repository, make no remote change.
   - If no `origin` exists, propose `git remote add origin <URL>`.
   - If `origin` names the template or another repository and `upstream` is unused, preserve it by proposing `git remote rename origin upstream`, then `git remote add origin <URL>`.
   - If `upstream` already exists, stop and ask which unused name should preserve the old `origin`. Do not overwrite, delete, or repoint either remote silently.
4. Show the exact remote mutation and push commands. After approval, run only those commands. Creating a repository with `gh repo create` requires separate approval of the exact account, name, and visibility.
5. After a push, verify the branch and all three commit identities:

   ```bash
   git rev-parse HEAD
   git rev-parse '@{upstream}'
   git ls-remote --heads origin <branch>
   ```

   Report success only when the local, tracking, and remote branch SHAs match. A failed or unavailable remote check is a limit, not success.

## Private off-device backup

1. Ask for the exact private rclone target, such as `gdrive:wiki-exports/wiki-export-YYYY-MM-DD.zip`. Do not persist the target in a tracked file.
2. Confirm that `rclone` is installed. A first Google Drive connection may use the repository's explicit initializer:

   ```bash
   python3 scripts/export_wiki.py \
     --upload-target gdrive:wiki-exports/wiki-export-YYYY-MM-DD.zip \
     --init-rclone-drive gdrive
   ```

   The browser or terminal authentication writes to the user's local rclone configuration, not this repository. Other providers use an existing rclone remote configured outside the wiki.
3. Before running the command, show the exact target and state that the archive is private and may contain the complete local tree. Obtain explicit approval for that upload.
4. For later backups, omit the initializer:

   ```bash
   python3 scripts/export_wiki.py \
     --upload-target <remote>:<private-path>/wiki-export-YYYY-MM-DD.zip
   ```

5. Require the export command's remote size and checksum verification to pass. Then run `python3 scripts/backup_state.py`. Report the archive path, exact approved target, receipt state, and any failure. A local archive without a verified receipt is not proof of an off-device backup.

## Report

Report each connection separately. Include inspected state, exact approved mutations or uploads, verification results, files changed, and anything deferred. State when no action was needed. Do not expose credential values.
