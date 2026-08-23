# Configure This Wiki

This is a one-time initializer for a fresh clone. It turns the template into a configured wiki and then removes itself. The resulting repository has no supported setup or reconfiguration path.

Git remains the recovery mechanism while initialization is being reviewed: the finalizer leaves ordinary working-tree changes and does not commit them. After the user commits those changes, the repository is their persistent wiki.

## 1. Confirm privacy

Before asking for personal or hybrid content, state this plainly:

> Raw source files stay local and must never be committed. Wiki pages and source metadata are tracked by Git and may still contain sensitive summaries. Complete exports include raw sources, local settings, scratch files, deliverables, and Git history. Use a private repository and an approved private backup destination. This template provides no encryption or access control.

Continue only after the user acknowledges that warning.

## 2. Ask the setup questions

Collect these answers:

1. The organization, project, or personal context name.
2. A one-line description of the domain.
3. A starting preset: `organization`, `personal`, or `hybrid`.
4. The final explicit active-type list. Read the preset defaults from `scripts/wiki-setup-presets.json`; the user may add or remove any type listed in `scripts/entity-catalog.json`. Keep the final list in catalog order.
5. One or more kebab-case `raw/` bucket names and a short description for each.
6. Three to five example questions the wiki should answer well.

The preset is only an interview aid. The final active-type list governs the configured wiki, and the preset is not retained as live configuration.

All three presets include `source`, `analysis`, and `decision` because the standard ingest, analysis-capture, and decision-capture routes write to those folders. The initializer accepts any nonempty supported selection and does not add removed types back. Remove one only when that route will be unavailable in the configured wiki.

## 3. Write the temporary answers

Write canonical JSON to exactly `tmp/wiki-setup-answers.json`: UTF-8, lexically sorted keys, compact separators, and one final newline.

```json
{"active_types":["analysis","concept","decision","goal","health","investment","learning","person","project","property","skill","source"],"context_name":"Example Wiki","domain":"Personal knowledge and durable context","example_queries":["What decisions have I made?","What am I working on?","What have I learned?"],"preset":"personal","privacy_acknowledged":true,"raw_buckets":{"documents":"Documents and notes","media":"Audio, images, and video"},"schema_version":1}
```

Do not place durable source material in `tmp/`; this answers file is consumed and deleted during finalization.

## 4. Preview

From the repository root, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/finalize_wiki_setup.py preview --answers tmp/wiki-setup-answers.json
```

Preview is read-only. Show the complete JSON result to the user. It reports the exact active types, entity and raw folders created or removed, blocked removals, files written, files deleted (including the temporary answers), validation errors, and `valid`.

The initializer owns only document fragments identified by named `wiki-setup` markers. Multi-line fragments use start/end pairs; single rows carry one line marker. Preview fails if a required marker is missing, duplicated, reversed, or left unconsumed. Rewording template prose inside a marked fragment does not break marker lookup. The configured replacement text remains defined in `scripts/wiki_setup_initializer.py`.

Stop if `valid` is false. The finalizer never removes a nonempty or symlinked entity folder and never invents an unsupported type.

## 5. Apply once

After the user approves the displayed preview, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/finalize_wiki_setup.py apply --answers tmp/wiki-setup-answers.json --approve
```

Apply requires a normal Git clone with no tracked working-tree changes. It:

- writes the configured `wiki/domain.md`;
- updates the live operating documents;
- creates the selected entity folders and removes only inactive placeholder folders;
- creates the raw buckets and their registry;
- replaces the template log entry with the initialization entry in `wiki/log.md`;
- archives the exact answers and a compact receipt under `archive/setup/`;
- deletes the temporary answers and all initializer files, including this guide;
- runs the complete eval suite and Tier‑1 lint; and
- leaves the result as uncommitted Git changes for review.

The only setup artifacts retained are:

- `archive/setup/answers.json`
- `archive/setup/finalization-receipt.json`

There is no reconfigure command. If apply reports a validation failure, inspect or restore the ordinary Git changes before committing. Do not rebuild a setup subsystem inside the configured wiki.

## 6. Hand off the configured wiki

Report:

- the configured context and active types;
- the changed and deleted paths;
- the eval and Tier‑1 lint outcomes; and
- that no commit was created.

The user can review and commit the changes. From then on, agents start with `AGENTS.md`, read the configured `wiki/domain.md`, and route through `CONTEXT.md`.
