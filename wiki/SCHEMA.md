# Wiki Schema Reference

Reference spec for entity types, page format, and source-type summary templates. Load during ingest and any time you author or audit a wiki page. The machine-readable catalog lives in `scripts/entity-catalog.json` and is consumed only through `scripts/wiki_entity_catalog.py`.

---

## Entity Types

<!-- parity:catalog key=entity-catalog -->
<!-- parity:enum key=entity-table-folders -->
| Type | Location | Presets | Purpose | Review date | Authority freshness | Verification |
|---|---|---|---|---|---|---|
| **Analysis** | `wiki/analyses/` | organization, personal, hybrid | A synthesized answer, comparison, brief, or other durable output. | optional | contextual | when-authority-requires |
| **Competitor** | `wiki/competitors/` | organization, hybrid | A competing vendor, alternative, or substitute and its positioning. | optional | contextual | when-authority-requires |
| **Concept** | `wiki/concepts/` | organization, personal, hybrid | An idea, term, framework, or mental model used in the configured domain. | optional | stable-meaning | when-authority-requires |
| **Customer** | `wiki/customers/` | organization, hybrid | A named customer or segment, its use cases, relationship, and risks. | optional | contextual | when-authority-requires |
| **Decision** | `wiki/decisions/` | organization, personal, hybrid | A historical choice, its rationale, alternatives, and outcome-review checkpoint. | expected | contextual | when-authority-requires |
| **Feature** | `wiki/features/` | organization, hybrid | A specific customer-facing capability and the jobs it supports. | optional | contextual | when-authority-requires |
| **Goal** | `wiki/goals/` | organization, personal, hybrid | A desired outcome with status, blockers, and a dated outcome review. | expected | current-state | before-consequential-action |
| **Health** | `wiki/health/` | personal, hybrid | Health protocols, experiments, practices, and current context; not medical advice. | optional | current-state | before-consequential-action |
| **Initiative** | `wiki/initiatives/` | organization, hybrid | A strategic program or bet that may coordinate several projects. | optional | contextual | when-authority-requires |
| **Investment** | `wiki/investments/` | personal, hybrid | An investment thesis, position, current view, risks, and open questions; not financial advice. | optional | current-state | before-consequential-action |
| **Learning** | `wiki/learnings/` | organization, personal, hybrid | A durable lesson tied to evidence or lived experience. | optional | stable-meaning | when-authority-requires |
| **Metric** | `wiki/metrics/` | organization, hybrid | A measurement definition, formula, owner, and observed values. | optional | contextual | when-authority-requires |
| **Partner** | `wiki/partners/` | organization, hybrid | A vendor, integration partner, channel partner, or collaborator. | optional | contextual | when-authority-requires |
| **Person** | `wiki/people/` | organization, personal, hybrid | An individual, stakeholder, or role and its responsibilities. | optional | stable-meaning | when-authority-requires |
| **Persona** | `wiki/personas/` | organization, hybrid | A user or buyer archetype with goals, pain points, and authority. | optional | stable-meaning | when-authority-requires |
| **Policy** | `wiki/policies/` | organization, hybrid | A currently binding rule, its scope, authority, exceptions, and review expectations. | optional | contextual | when-authority-requires |
| **Process** | `wiki/processes/` | organization, hybrid | An organizational procedure with triggers, inputs, steps, outputs, owners, and exceptions. | optional | contextual | when-authority-requires |
| **Product** | `wiki/products/` | organization, hybrid | A customer-facing offering, its positioning, users, and core jobs. | optional | contextual | when-authority-requires |
| **Project** | `wiki/projects/` | organization, personal, hybrid | Bounded work with a concrete output or completion condition. | optional | contextual | when-authority-requires |
| **Property** | `wiki/properties/` | personal, hybrid | An owner manual for a residence or operated property: systems, maintenance, vendors, records, and status. | optional | current-state | before-consequential-action |
| **Skill** | `wiki/skills/` | organization, personal, hybrid | A demonstrated capability and the evidence behind proficiency. | optional | stable-meaning | when-authority-requires |
| **Source** | `wiki/sources/` | organization, personal, hybrid | A summary of one raw artifact and what that evidence supports. | optional | immutable-source | when-authority-requires |
| **System** | `wiki/systems/` | organization, hybrid | A technical or operational dependency with ownership, interfaces, and failure modes. | optional | contextual | when-authority-requires |
| **Team** | `wiki/teams/` | organization, hybrid | An organizational group with responsibilities and interfaces. | optional | contextual | when-authority-requires |

---

## Page Format

Every entity page (any page inside a `wiki/<entity-type>/` folder) must have this YAML frontmatter. `scripts/lint.py` checks the full entity-page contract there. Meta pages at the `wiki/` root, such as `index.md`, `log.md`, `overview.md`, `glossary.md`, `primer.md`, `sourcing-queue.md`, `contradictions.md`, `design-notes.md`, `SCHEMA.md`, and `synthesis.md`, are infrastructure and may use their own lightweight frontmatter with descriptive `type` values outside the entity enum.

The parity-marker comments shown in this reference are doc-tooling markers, not page template content. Omit them when authoring page frontmatter.

```yaml
---
title: <page title>
<!-- parity:enum key=entity-type -->
type: analysis | competitor | concept | customer | decision | feature | goal | health | initiative | investment | learning | metric | partner | person | persona | policy | process | product | project | property | skill | source | system | team
created: YYYY-MM-DD
updated: YYYY-MM-DD
review_by: YYYY-MM-DD         # OPTIONAL — outcome-review checkpoint, especially for decisions
sources: [list of raw source filenames or "experience: <brief description>" entries that informed this page]
<!-- parity:enum key=source-type -->
source_type: help-doc | slack-thread | call-transcript | exec-memo | deck | crm-export | strategy-doc | release-note | press | analyst-report | competitor-collateral | sales-battlecard | product-spec | board-doc | synthesis | other  # SOURCE PAGES ONLY — describes the underlying raw artifact
tags: [relevant tags]
<!-- parity:enum key=confidence -->
confidence: high | medium | low | contested   # how well-sourced this page is; "contested" means active disagreement across sources
agent_use_cases:                  # which downstream-agent questions this page is meant to answer
  - <e.g., "answering buyer-side product questions">
  - <e.g., "comparing our product to a competitor's">
---
```

`source_type` is required on pages in `wiki/sources/` and omitted elsewhere. `agent_use_cases` is required on every entity page except `sources/`; root meta pages such as `index.md`, `log.md`, and `glossary.md` are infrastructure, not retrievable answers.

`sources:` accepts, per item: a `raw/` path, a bare kebab-case slug naming a `wiki/sources/` page, a URL, or free-text provenance prefixed `experience`, `web`, `deliverable`, or `source` followed by a colon or space (for example `experience: <brief description>`). `scripts/lint.py` checks the machine-checkable subset of this grammar: `raw/` paths must exist on disk, and bare kebab-case slugs must resolve to source pages.

`review_by` is optional on most pages and recommended when a claim or forecast should be graded against future outcomes. Decisions and goals should carry a checkpoint unless there is a clear reason not to enroll them in the outcome-review loop.

Optional authority metadata:

<!-- parity:enum key=authority-kind -->
- `authority_kind: raw-source | source-page | owner-page | external-url | local-resource | mixed | none`
- `authority_ref: <repo-relative path, URL, or short prose for mixed/local-resource>`
<!-- parity:enum key=authority-freshness -->
- `authority_freshness: immutable-source | stable-meaning | current-state | event-log | predictive | deprecated`
- `verify_before_action: true | false`
- `last_verified: YYYY-MM-DD`

`sources:` is provenance: what evidence produced the page. `authority_*` is current truth: what an agent should trust or re-check before acting on volatile claims. Adoption is incremental; these fields are optional, but `authority_kind` is required whenever any other authority field is present.

`authority_ref` always uses full repo-relative paths or URLs, never the bare-slug shorthand accepted by `sources:`. Use `raw/...` for raw artifacts, `wiki/sources/name.md` for source pages, `wiki/<folder>/name.md` for owner pages, `http://` or `https://` for external authority, and `source:` prose only for mixed/local-resource cases where one deterministic path is not enough.

Freshness defaults guide authoring; lint does not infer them. Write `authority_freshness` only when the page differs from its type default, acts as the owner for live/current state, or is explicitly predictive/deprecated.

<!-- parity:enum key=freshness-defaults -->
| authority_freshness | Default for |
|---|---|
| `immutable-source` | `sources/` pages |
| `stable-meaning` | `concepts/`, `people/`, `skills/`, `learnings/`, or settled `decisions/` |
| `current-state` | goals and live health, investment, property, product, feature, initiative, metric, or other configured owner pages |
| `event-log` | ledger-style pages where newest dated entry matters |
| `predictive` | opt-in forward-looking `analyses/` or `decisions/`; requires `review_by` |
| `deprecated` | no default; always explicit |

Source page example (`raw-source` authority; `authority_freshness` stays omitted because `immutable-source` is the `sources/` type default):

```yaml
type: source
source_type: strategy-doc
sources: [raw/strategy/q3-product-strategy.md]
authority_kind: raw-source
authority_ref: raw/strategy/q3-product-strategy.md
```

Compiled page pointing at a source-page authority:

```yaml
type: concept
sources: [q3-product-strategy]
authority_kind: source-page
authority_ref: wiki/sources/q3-product-strategy.md
```

Current-state owner example:

```yaml
type: initiative
authority_kind: mixed
authority_ref: "source: launch owner page, linked source pages, and latest status notes"
authority_freshness: current-state
verify_before_action: true
last_verified: 2026-07-04
```

Followed by:
1. **One-line summary** (used in `index.md` and in agent-retrieved snippets)
2. **Body** — structured with headers, lists, and tables
3. **Open questions / gaps** section — what we don't know yet. Required on non-source entity pages; optional on source pages when the source leaves real unknowns.
4. **Related pages** section — `[[wiki-page-name]]` links, with typed labels when the relationship is clear. Plain-text entries without `[[ ]]` are permitted for pages that do not exist yet or for terms deliberately kept as prose; they carry no graph edge.

**Filenames:** kebab-case, no extension prefix. Page titles in frontmatter may be title-cased.

**Citations:** When stating a specific fact, append `(source: [[source-filename]])`. When stating an opinion or inference, prefix with "Inference:" or "Hypothesis:".

Three provenance rules:

1. **Quotes are verbatim or unmarked.** Text inside quotation marks attributed to a source must appear in that source word for word. If the page compressed, paraphrased, or synthesized the source, drop the quotation marks or label it as synthesized from `[[page]]`.
2. **Vague stays vague.** If the source says "a recent study," "last month," or similar relative language, do not upgrade it to a named or dated reference. Convert relative dates only when the source supports the conversion, and preserve uncertainty in the wording.
3. **Assembled lists are labeled.** An enumeration compiled from points scattered across a source is synthesis, not extraction. Prefix it with `Inference:` or state that the list is synthesized.

**Live current-state:** Do not restate volatile values for a changing thread across many pages. Put targets, prices, statuses, dates, rates, stage labels, model states, or similar moving values on one owner page, then have other pages link that owner with stable pointer language. If a configured wiki later needs script-backed drift detection, add that as an explicit schema/tooling decision instead of inventing hidden registry requirements.

## Related Page Labels

Use lightweight labels in `## Related pages` to say why two pages are connected. The label is plain markdown text; the page reference stays an ordinary `[[wikilink]]` so backlink and index scripts still work.

Allowed labels:

| Label | Meaning |
|---|---|
| `Supports: [[page]]` | This page strengthens, evidences, or confirms the linked page. |
| `Contradicts: [[page]]` | This page conflicts with or materially challenges the linked page. |
| `Depends on: [[page]]` | This page requires the linked page to be understood first or true. |
| `Derived from: [[page]]` | This page was created from, generalized from, or synthesized out of the linked page. |
| `Part of: [[page]]` | This page is a component of the linked larger system, project, or framework. |
| `Related: [[page]]` | Meaningful connection, but no stronger typed relationship fits. |

Examples:

```markdown
## Related pages
- Depends on: [[workflow-automation]]
- Supports: [[q3-board-deck]]
- Part of: [[enterprise-onboarding]]
- Derived from: [[customer-discovery-notes]]
- Related: [[pricing-packaging]]
```

Plain links remain valid:

```markdown
- [[page]]
```

Do not mechanically backfill every existing related link. Add labels when touching or adjudicating a page, especially in `## Related pages`. Use `Related:` as the fallback when the relationship matters but is not precise.

---

## Source-Type Summary Templates

When ingesting a source, the summary in `wiki/sources/` should be shaped by what that source can be trusted for:

<!-- parity:enum key=source-type-table -->
| `source_type` | Trustworthy for | Treat with care | Summary should emphasize |
|---|---|---|---|
| `help-doc` | product surface, terminology | strategy, pricing, customers | feature inventory, user workflows |
| `slack-thread` | informal context, decisions-in-progress | facts (often half-formed) | who said what, decisions reached, open threads |
| `call-transcript` | customer voice, objections, exact quotes | speaker accuracy, abridgements | quotes, named accounts, objections raised |
| `exec-memo` | strategy, intent, internal narrative | implementation status | thesis, assertions, decisions made |
| `deck` | positioning, claims | nuance, caveats | claims as bullet points, audience, date |
| `crm-export` | named accounts, deal stage, structured data | qualitative color | structured tables, totals, ranges |
| `strategy-doc` | initiatives, north stars, multi-year goals | tactical detail | goals, owners, dependencies |
| `release-note` | shipped capabilities, dates | strategy | dated feature list, what changed |
| `press` | external positioning | internal accuracy | quotes, dates, reach |
| `analyst-report` | market view, peer set | internal claims about the organization | market size, peer comparisons, the organization's rating |
| `competitor-collateral` | competitor's stated positioning | objectivity | their claims verbatim, gaps to attack |
| `sales-battlecard` | what we tell sellers about a competitor | factual claims about the competitor (our POV, not neutral) | "Why we win / lose," objection handling, competitor tells |
| `product-spec` | engineering ground truth | GTM framing | requirements, constraints, edge cases |
| `board-doc` | strategic priorities, metric targets | day-to-day truth | priorities, targets, board asks |
| `synthesis` | LLM-synthesized analysis integrating multiple sources | source integration methodology not transparent; may embed interpreter bias | main findings, high-level synthesis, caveats on sources |
| `other` | source-specific evidence not covered by a narrower type | overgeneralizing from an uncategorized source | why the source matters and what it can safely support |

---

## Confidence Values

<!-- parity:enum key=confidence-values -->
- `high` — multiple sources agree, or an authoritative internal source (spec, exec statement, official doc)
- `medium` — single source, or strong inference from consistent signals
- `low` — speculation, early hypothesis, or single off-hand mention
- `contested` — sources actively disagree; page records both positions and links to [[contradictions]] for the open question

When confidence is `low` or `contested`, state it in the page body too — downstream agents may skip frontmatter. For `contested`, the body must include a "Disagreement" section that names the sources on each side.

## Referenced by

_No inbound links yet._
