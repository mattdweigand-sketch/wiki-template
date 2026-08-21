---
title: Domain Config
type: domain
created: 2026-05-17
updated: 2026-05-17
status: unconfigured
org: <Organization name>
domain: <One-line domain summary, e.g. "developer tools for payments">
entity_types_active: []
raw_buckets: []
example_queries: []
---

# Domain Config

Single source of truth for who this wiki is about and which parts of the governed entity catalog are active.

When `status: unconfigured`, this repository is still a fresh template. Follow [`SETUP.md`](../SETUP.md) once. The approved finalizer replaces this page, archives the setup answers, and removes the initializer.

When `status: configured`, the repository is a persistent wiki. Read this page and continue through [`CONTEXT.md`](../CONTEXT.md); there is no supported reconfiguration route.

| Field | Meaning |
|---|---|
| `org` | Organization, project, or personal context name |
| `domain` | One-line description of the subject area |
| `entity_types_active` | Explicit final selection from [`SCHEMA.md`](SCHEMA.md); these types govern the live entity folders |
| `raw_buckets` | Source-artifact bucket names registered under `raw/` |
| `example_queries` | Three to five questions the wiki should answer well |
