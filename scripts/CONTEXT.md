# Tooling entry points

For tooling changes and validation, follow the [maintenance eval workflow](../workflows/maintenance/eval.md) and the [change-impact table](../REFERENCES.md#tooling-change-impact). The [module boundaries](../REFERENCES.md#tooling-module-boundaries) identify shared owners; `wiki_eval.py` owns the suite registry.

`wiki_lookup.py` provides read-only catalog lookup (`index`), cataloged entity-body excerpts (`content`), and recent activity windows (`log`). All outputs are paginated navigation aids with original line references and a 12,000-character cap. Content lookup requires a nonempty query, accepts governed folder scopes, and returns up to 12 exact source windows of at most 500 characters with omission markers. See [bounded navigation](../REFERENCES.md#bounded-navigation) for command details and the [ask workflow](../workflows/research/ask.md) for canonical retrieval procedure.
