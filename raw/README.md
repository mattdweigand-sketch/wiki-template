# raw/

Source artifacts live here, organized by source type. Drop a file into the right subfolder with a kebab-case filename, then run the `wiki-ingest` workflow to triage, summarize, and link it into `wiki/`.

`raw/` is immutable. Never edit a file already here. New sources append; existing files stay as the canonical artifact that wiki citations point back to.

Source artifacts stay on the local machine and must never be committed. Git
tracks this guide, the raw bucket taxonomy, source pages, and
`scripts/raw-artifacts.json`. The manifest binds every source file by exact
path, size, and SHA-256. Use `wiki-export` for a complete local or explicitly
approved private off-device backup.

## Subfolders

[`scripts/raw-buckets.json`](../scripts/raw-buckets.json) is the sole tracked taxonomy. `scripts/lint.py --tier1` verifies that every `raw/` subfolder is registered there and rejects registered buckets that are missing from the tree. Read the registry to choose a destination. Change the registry and tracked bucket placeholders together only when a different source taxonomy is useful.
