---
title: Design Notes
type: maintenance
created: 2026-05-17
updated: 2026-08-23
---

# Design Notes

Durable reasons for the live wiki design.

## One-time setup

A fresh clone uses one reviewed setup pass. The finalizer writes the configured domain, creates selected folders, records setup provenance, validates the result, and leaves uncommitted changes for review.

## Governed entity catalog

`scripts/entity-catalog.json` owns supported entity types and folder mappings. `scripts/wiki_entity_catalog.py` validates and exposes it.

A configured wiki contains only the entity folders selected during setup.

## Raw artifacts stay immutable

Raw source bytes stay local and read-only after placement. The wiki interprets sources without rewriting them.

## Source pages are the citation surface

Entity pages cite `wiki/sources/` pages where possible. Source pages give agents a short evidence view before they open raw files.

## Confidence and contradictions are first class

Pages state confidence. Conflicting claims go in [[contradictions]] before an owner page changes.

## Moving facts have one owner

Statuses, dates, prices, targets, and other changing values live on one owner page. Other pages link to that owner.

## Backlinks are generated

Agents write `## Related pages`. `scripts/rebuild_referenced_by.py` owns `## Referenced by`.

## No app is required

The wiki uses Markdown, Python, and vendor-neutral workflows.
