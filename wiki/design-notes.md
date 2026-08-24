---
title: Design Notes
type: maintenance
created: 2026-05-17
updated: 2026-08-23
---

# Design Notes

Durable reasons for the live wiki design.

## Ready-to-use clone

A fresh clone is operational immediately. The user customizes `wiki/domain.md` through ordinary edits instead of running a separate initializer.

## Governed entity catalog

`scripts/entity-catalog.json` owns supported entity types and folder mappings. `scripts/wiki_entity_catalog.py` validates and exposes it.

Every governed entity folder ships with the template. Unused folders stay empty, so changing the domain does not change workflow capabilities or require structural migration.

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
