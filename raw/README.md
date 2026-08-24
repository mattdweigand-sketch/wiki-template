# raw/

Source artifacts live here, organized by source type. Drop a file into the right subfolder with a kebab-case filename, then run the `wiki-ingest` workflow to triage, summarize, and link it into `wiki/`.

`raw/` is immutable. Never edit a file already here. New sources append; existing files stay as the canonical artifact that wiki citations point back to.

Source artifacts stay on the local machine and must never be committed. Git
tracks this guide, the raw bucket taxonomy, source pages, and
`scripts/raw-artifacts.json`. The manifest binds every source file by exact
path, size, and SHA-256. Use `wiki-export` for a complete local or explicitly
approved private off-device backup.

## Subfolders

This template starts unconfigured. The one-time initializer replaces the placeholder rows below, creates the selected `raw/<bucket>/` folders, and writes the same definitions to `scripts/raw-buckets.json`. That JSON file is the tracked taxonomy source that `scripts/lint.py --tier1` reads for structural checks.

| Folder | Holds |
|---|---|
| `customer-research/` | Customer interview notes, support findings, and user research |
| `internal-memos/` | Strategy, planning, and operating memos |
| `release-notes/` | Product, API, and changelog artifacts |
| `ai-research/` | Example AI research and workflow sources, if present in this checkout |
| `social/` | Example social or screenshot captures, if present in this checkout |
| `videos/` | Example video transcript captures, if present in this checkout |
