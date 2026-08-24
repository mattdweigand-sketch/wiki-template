#!/usr/bin/env python3
"""Regression checks for the governed schema vocabulary record."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from eval_lib import Results
from wiki_schema_vocabularies import (
    SCHEMA_VOCABULARIES_PATH,
    SchemaVocabularyError,
    load_wiki_schema_vocabularies,
)


results = Results()


def schema_vocabulary_payload() -> dict[str, object]:
    """Return one mutable copy of the live governed record."""
    return json.loads(SCHEMA_VOCABULARIES_PATH.read_text(encoding="utf-8"))


def schema_vocabulary_case_rejects(
    name: str,
    payload: dict[str, object] | str,
    expected_error: str,
) -> None:
    """Record one malformed record that the loader must reject."""
    with tempfile.TemporaryDirectory(prefix="wiki-schema-vocab-") as directory:
        path = Path(directory) / "schema-vocabularies.json"
        text = payload if isinstance(payload, str) else json.dumps(payload)
        path.write_text(text, encoding="utf-8")
        try:
            load_wiki_schema_vocabularies(path)
        except SchemaVocabularyError as exc:
            results.record(name, expected_error in str(exc), str(exc))
        else:
            results.record(name, False, "malformed vocabulary record was accepted")


live = load_wiki_schema_vocabularies()
results.record(
    "live-schema-vocabularies-load",
    bool(live.confidence and live.source_types and live.related_labels),
    repr(live),
)

duplicate_confidence = schema_vocabulary_payload()
duplicate_confidence["confidence"] = ["high", "high"]
schema_vocabulary_case_rejects(
    "duplicate-schema-vocabulary-value-fails",
    duplicate_confidence,
    "must not contain duplicates",
)

bad_label = schema_vocabulary_payload()
bad_label["related_labels"] = [{"label": "Related"}]
schema_vocabulary_case_rejects(
    "malformed-related-label-fails",
    bad_label,
    "fields are invalid",
)

schema_vocabulary_case_rejects(
    "duplicate-schema-vocabulary-key-fails",
    '{"schema_version":1,"schema_version":1}',
    "duplicate schema vocabulary key",
)

sys.exit(results.finish())
