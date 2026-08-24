# raw/

Source artifacts live here, organized by source type. Drop a file into the right subfolder with a kebab-case filename, then run the `wiki-ingest` workflow to triage, summarize, and link it into `wiki/`.

`raw/` is immutable. Never edit a file already here. New sources append; existing files stay as the canonical artifact that wiki citations point back to.

Source artifacts stay on the local machine and must never be committed. Git
tracks this guide, the raw bucket taxonomy, source pages, and
`scripts/raw-artifacts.json`. The manifest binds every source file by exact
path, size, and SHA-256. Use `wiki-export` for a complete local or explicitly
approved private off-device backup.

## Subfolders

The clone includes three neutral buckets. `scripts/raw-buckets.json` is their sole tracked taxonomy source and `scripts/lint.py --tier1` validates the folders against it. Change the registry, this table, and tracked bucket placeholders together only when a different source taxonomy is genuinely useful.

| Folder | Holds |
|---|---|
| `documents/` | Text documents, notes, transcripts, exports, and structured data |
| `imports/` | Source bundles or exports awaiting classification during ingest |
| `media/` | Audio, images, video, and other media artifacts |
