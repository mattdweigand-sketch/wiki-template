---
title: Domain Config
type: domain
created: 2026-05-17
updated: 2026-08-24
status: configured
org: <Organization name>
domain: <One-line domain summary, e.g. "developer tools for payments">
example_queries:
  - <What should this wiki help answer?>
  - <What durable context should an agent be able to find?>
  - <Which decisions or facts should stop being re-derived?>
---

# Domain Config

Single source of truth for who this wiki is about and what it should help answer.

The clone is ready to use. Say `setup` or invoke `wiki-setup` to answer the initial questions. You can also replace the placeholder values through ordinary edits, then continue through [`CONTEXT.md`](../CONTEXT.md). All governed entity folders remain available; unused folders may stay empty. [`scripts/raw-buckets.json`](../scripts/raw-buckets.json) governs raw source buckets.

| Field | Meaning |
|---|---|
| `org` | Organization, project, or personal context name |
| `domain` | One-line description of the subject area |
| `example_queries` | Three to five questions the wiki should answer well |
