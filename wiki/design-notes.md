---
title: Design Notes
type: maintenance
created: 2026-05-17
updated: 2026-09-03
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


## Reviewed text remains tied to its evidence

Independent review checks claim support and scope. Deterministic validation checks that the cited files belong to the captured source closure and actually contain the decisive quotation. Response drafts select claim IDs; the renderer supplies captured text and source links. Neither hash agreement nor a matching quotation proves semantic support.

## Validate history where a change entered

Capture records describe a particular application. Checking their introducing commits permits later routine corrections while detecting invalid captures even after a revert. Provenance uses the same historical scope within its existing owner, `wiki_provenance.py`, without adding a second raw registry or tracking private source bytes. Legacy capture records cannot prove file modes they never recorded.

## Two finishes with one log renderer

Routine work finishes through backlink generation, a serialized log write, and one full lint run. Approved work stages all those postimages before approval and finishes with validation only. Both paths use the same log rendering rules and existing durable write primitives; the approval gate remains the only transactional capture engine.

Complete archives can validate their present raw/source closure and finish routine work without Git. They cannot reconstruct uncommitted changes or historical raw bytes. Failed routine finalization is retryable but does not roll back prior authored work.

## Navigation reads the authored catalog

Bounded catalog and log lookup reduces default loading without adding an index registry or cache. Explicit audits can still read whole files. The configured domain, setup flow, and entity catalog remain independent of these helpers.
