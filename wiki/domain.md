---
title: Domain Config
type: domain
created: 2026-05-17
updated: 2026-05-17
status: unconfigured
configuration_version: 2
org: <Organization name>
domain: <One-line domain summary, e.g. "developer tools for payments">
entity_preset:
entity_types_active: []
raw_taxonomy: []
example_queries: []
---

# Domain Config

Single source of truth for **who this wiki is about**. Framework files defer to this page instead of hardcoding an organization name.

## Status

When `status: unconfigured` (the default for a fresh clone), this wiki is a blank template. An agent in a new session should notice this flag and route to [`SETUP.md`](../SETUP.md), which walks the user through an interview to fill this file out.

When `status: configured`, the wiki is ready to ingest sources and answer questions.

## Fields

| Field | Meaning |
|---|---|
| `org` | The organization (company, team, project) this wiki is about |
| `domain` | One-line description of the subject area |
| `configuration_version` | Version of the configured-domain contract. New configurations use `2`; missing values identify legacy configured wikis. |
| `entity_preset` | Setup starting point: `organization`, `personal`, or `hybrid`. Required once configured. |
| `entity_types_active` | Explicit final selection from the supported catalog in [`SCHEMA.md`](SCHEMA.md). This list, not preset membership alone, governs the configured folders. |
| `raw_taxonomy` | Subfolder names that should exist under `raw/` for source-document organization |
| `example_queries` | 3–5 questions the wiki should answer well — useful for sanity-checking coverage |

## After configuration

The agent updates this file's `status:` to `configured`, replaces `<Organization>` placeholders in the framework files (see [`SETUP.md`](../SETUP.md) for the exact list), and appends a log entry to [`log.md`](log.md).
