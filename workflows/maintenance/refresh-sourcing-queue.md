---
name: wiki-refresh-sourcing-queue
description: Use this workflow when the user says "refresh sourcing queue". Re-prioritizes knowledge gaps based on recent ingests.
---

## Load / Skip

- **Load:** `wiki/sourcing-queue.md` if present and the last ~10 entries of `wiki/log.md` to see what recent ingests revealed.
- **Skip:** the full wiki, entity pages, and raw sources.

## Steps

1. Read `wiki/sourcing-queue.md` if present; otherwise create it only if the current wiki structure makes a sourcing queue useful.
2. Re-prioritize based on what the latest ingests revealed
3. For each priority gap, name the source artifact most likely to fill it, such as CRM export, win/loss note, call transcript, product spec, board deck, research memo, or support thread.
4. Append to `wiki/log.md`:

```
## [YYYY-MM-DD] refresh-sourcing-queue
Changes: ...
```
