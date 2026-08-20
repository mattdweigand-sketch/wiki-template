# Configure This Wiki

Use this workflow once for a fresh clone, or when the user explicitly asks to reconfigure an existing wiki. Setup is agent-applied but planner-governed: the planner validates and previews; it never writes.

## Trigger

Read `wiki/domain.md`. If `status: unconfigured`, tell the user:

> This wiki is in template state. I can run a short setup interview and preview every entity-folder change before applying it. Want to configure it now?

If the user declines, stop setup without changing files. Do not gate unrelated work on configuration.

## Privacy warning

Before offering the `personal` or `hybrid` preset, state this plainly:

> Raw artifacts under `raw/` are ignored by Git, but derived pages under `wiki/` are tracked and may be pushed to a remote. Health, financial, relationship, and property information may therefore be published if this clone is connected to a public repository. Exports include both wiki pages and raw sources. This template provides no encryption or access control.

The user must knowingly continue before sensitive personal categories are selected. Do not imply that local Markdown, `.gitignore`, or the export workflow protects tracked wiki pages.

## Interview

Ask these in order. Keep it conversational; one question at a time unless the user answers several at once.

1. **Organization or context name.** "What is the name of the organization, project, or personal context this wiki is about?"
2. **Domain.** "One line: what subject area does this wiki cover?"
3. **Preset.** Offer:
   - `organization` — 21 types for business, operations, projects, goals, skills, and learnings.
   - `personal` — 12 types for sources, concepts, decisions, people, analyses, projects, goals, skills, learnings, health, investments, and property.
   - `hybrid` — all 24 supported types.
4. **Active types.** Show the selected preset's proposed list from `scripts/entity-catalog.json`. The user may remove proposed types or add any other supported catalog type. Ordinary setup cannot invent a type outside the catalog.
5. **Source taxonomy.** Ask which kebab-case subfolders should exist under `raw/`, based on where source artifacts originate.
6. **Example queries.** Ask for 3–5 questions the wiki should answer well.

## Plan before writing

Run the read-only planner from the repository root, passing the final explicit type list:

```bash
python3 scripts/plan_wiki_setup.py \
  --preset <organization|personal|hybrid> \
  --active <comma-separated-type-list>
```

The JSON result contains:

- `configuration_version` and `selected_preset`;
- the normalized `active_types` list;
- `create_folders`;
- empty-placeholder `remove_folders`;
- `blocked_removals` for nonempty folders;
- migration `advisories`;
- validation `errors` and a final `valid` value.

The command is read-only. A nonzero exit or `valid: false` blocks setup. Unsupported types fail here before any unsupported folder is created. Never delete or relocate entity pages to satisfy a plan. A folder is removable only when it is empty or contains exactly a regular `.gitkeep` file; a page, nested directory, symlink, or other entry blocks removal.

## Apply an approved valid plan

### 1. Update `wiki/domain.md`

Set:

```yaml
status: configured
configuration_version: 2
org: <configured name>
domain: <configured one-line domain>
entity_preset: <selected preset>
entity_types_active:
  - <every normalized active type from the plan>
raw_taxonomy:
  - <every configured raw bucket>
example_queries:
  - <3-5 configured questions>
```

Remove the obsolete `entity_types_custom` field. Set `updated:` to today's date.

Legacy configured wikis without `configuration_version` or `entity_preset` remain readable and receive a migration advisory. An empty legacy `entity_types_custom` may be removed during migration. A populated legacy custom-type list requires manual schema resolution and blocks automatic reconfiguration.

### 2. Replace organization placeholders

Replace the first-line `<Organization>` placeholder in:

- `README.md`
- `AGENTS.md`
- `CONTEXT.md`

Do not rewrite `CLAUDE.md`; it remains a thin wrapper around `AGENTS.md`.

### 3. Apply only the planned entity-folder changes

Create each planned `wiki/<folder>/` with a `.gitkeep`. Remove only folders listed in `remove_folders`, and only after confirming they still contain no entry other than a regular `.gitkeep`. Do nothing to `blocked_removals`.

The configured wiki must contain exactly the folders mapped from `entity_types_active`. Preset membership is only a starting point; the explicit active list governs.

### 4. Configure raw buckets

For each `raw_taxonomy` entry, create `raw/<bucket>/`. Update `raw/README.md` and `scripts/raw-buckets.json` with the same bucket names and descriptions. `scripts/raw-buckets.json` is the machine authority read by Tier‑1 lint.

Raw source artifacts stay local-only and immutable after placement. Never force-add a raw artifact or raw-bucket placeholder to Git; only `raw/.gitkeep` and `raw/README.md` are tracked.

### 5. Log configuration

Append to `wiki/log.md`:

```markdown
## 2026-MM-DD — domain configured

Context: <configured name>
Domain: <one-line summary>
Configuration version: 2
Entity preset: <preset>
Active entity types: <explicit list>
Raw taxonomy: <list>
```

### 6. Post-validate

Rerun the exact same planner command. A correctly applied plan returns no folder changes, blocked removals, or errors. Then run:

```bash
python3 scripts/lint.py --tier1
```

Report the selected preset, final active types, changed files, both validation outcomes, and any unresolved migration advisory.

## Entity boundaries that commonly overlap

- **Project / initiative:** a project is bounded work with a concrete output or completion condition; an initiative is a broader strategic program or bet.
- **Goal / metric:** a goal is a desired outcome; a metric defines how something is measured.
- **Learning / analysis:** a learning is a durable lesson from evidence or experience; an analysis is a synthesized output or answer.
- **Skill / concept:** a skill is a demonstrated capability; a concept is an idea, term, framework, or mental model.
- **Team / person:** a team is an organizational group; a person is an individual, stakeholder, or role. Existing person pages that describe teams remain valid.
- **System / product:** a system is a technical or operational dependency; products and features are customer-facing offerings.
- **Process / workflow:** a process is a domain procedure recorded as knowledge; files under `workflows/` are framework operating instructions.
- **Policy / decision:** a policy is a currently binding rule; a decision is the historical choice and rationale that may have created it.
- **Partner / customer / competitor:** use the primary current relationship on one canonical page and record secondary roles without duplicating the entity.
- **Property / investment:** property pages are owner manuals; investment pages hold return theses. A primary residence belongs under property unless the page's purpose is an investment thesis.

## Authoring guidance from the catalog

- Goals and decisions should normally carry `review_by`; missing enrollment is a Tier‑2 advisory, not a hard failure.
- Goal pages use `current-state` as authoring guidance. A completed goal may instead become `stable-meaning` or `event-log` when that better describes the page.
- Health, investment, and property pages use `current-state` when they own live facts and should be verified before consequential action.
- Skills and learnings use `stable-meaning` by default.
- Lint never silently inserts or infers authority metadata. Authors record it only when it changes how a future agent should verify the page.

The template ships `scripts/current-state-owners.json` disabled and empty, so a fresh or newly configured wiki receives no owner-registry warnings. A wiki that needs script-backed live-state drift detection may opt in after setup: set `enabled` to `true`, list sorted `folder/name.md` paths relative to `wiki/`, and give every registered page explicit `authority_freshness: current-state`. Tier 1 rejects malformed, duplicate, missing, or non-current-state owner entries; Tier 2 then reports dated-status drift for review. Setup does not infer or populate this registry.

## What setup does not change

- `scripts/entity-catalog.json` or executable scripts
- `.claude/commands/` or `.codex/skills/`
- workflow routers or maintenance workflows
- schema mechanics outside the configured domain fields
- existing entity pages

Adding an unsupported entity type is an engineering change to the catalog, schema documentation, lint behavior, and evaluation coverage—not a setup operation.

## Idempotency and reconfiguration

If `wiki/domain.md` is already configured, treat its values as interview defaults. Always plan before editing. Reapplying the same valid selection produces an empty folder plan. Reconfiguration fails before writing when a removed type owns a nonempty folder; no process automatically deletes or migrates its pages.
