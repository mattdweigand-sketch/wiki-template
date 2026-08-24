#!/usr/bin/env python3
"""Load the governed page-schema vocabularies used by lint and authoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from _strict_json import DuplicateJsonKeyError, reject_duplicate_json_keys

SCHEMA_VOCABULARIES_PATH = Path(__file__).with_name("schema-vocabularies.json")
SCHEMA_VOCABULARY_FIELDS = {
    "schema_version",
    "authority_freshness",
    "authority_kinds",
    "confidence",
    "related_labels",
    "source_types",
}


class SchemaVocabularyError(ValueError):
    """The governed schema vocabulary file is missing or invalid."""


@dataclass(frozen=True)
class RelatedLabelSpec:
    label: str
    meaning: str


@dataclass(frozen=True)
class WikiSchemaVocabularies:
    confidence: tuple[str, ...]
    source_types: tuple[str, ...]
    authority_kinds: tuple[str, ...]
    authority_freshness: tuple[str, ...]
    related_labels: tuple[RelatedLabelSpec, ...]

    @property
    def related_label_names(self) -> tuple[str, ...]:
        return tuple(spec.label for spec in self.related_labels)


def _ordered_unique_strings(payload: object, field: str) -> tuple[str, ...]:
    if not isinstance(payload, list) or not payload:
        raise SchemaVocabularyError(f"{field} must be a nonempty string list")
    if any(not isinstance(value, str) or not value.strip() for value in payload):
        raise SchemaVocabularyError(f"{field} must contain nonempty strings")
    values = tuple(payload)
    if len(values) != len(set(values)):
        raise SchemaVocabularyError(f"{field} must not contain duplicates")
    return values


def load_wiki_schema_vocabularies(
    path: Path = SCHEMA_VOCABULARIES_PATH,
) -> WikiSchemaVocabularies:
    """Load and validate the single owned vocabulary record."""
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    except DuplicateJsonKeyError as exc:
        raise SchemaVocabularyError(
            f"duplicate schema vocabulary key {exc.key!r}"
        ) from exc
    except SchemaVocabularyError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaVocabularyError(f"cannot read schema vocabularies: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != SCHEMA_VOCABULARY_FIELDS:
        raise SchemaVocabularyError("schema vocabulary fields differ from the contract")
    if payload.get("schema_version") != 1 or isinstance(payload.get("schema_version"), bool):
        raise SchemaVocabularyError("schema vocabulary version must be integer 1")
    labels_payload = payload.get("related_labels")
    if not isinstance(labels_payload, list) or not labels_payload:
        raise SchemaVocabularyError("related_labels must be a nonempty object list")
    labels: list[RelatedLabelSpec] = []
    for index, item in enumerate(labels_payload, start=1):
        if not isinstance(item, dict) or set(item) != {"label", "meaning"}:
            raise SchemaVocabularyError(f"related label {index} fields are invalid")
        label = item.get("label")
        meaning = item.get("meaning")
        if not isinstance(label, str) or not label.strip():
            raise SchemaVocabularyError(f"related label {index} has no label")
        if not isinstance(meaning, str) or not meaning.strip():
            raise SchemaVocabularyError(f"related label {index} has no meaning")
        labels.append(RelatedLabelSpec(label=label, meaning=meaning))
    if len({spec.label for spec in labels}) != len(labels):
        raise SchemaVocabularyError("related label names must be unique")
    return WikiSchemaVocabularies(
        confidence=_ordered_unique_strings(payload.get("confidence"), "confidence"),
        source_types=_ordered_unique_strings(payload.get("source_types"), "source_types"),
        authority_kinds=_ordered_unique_strings(payload.get("authority_kinds"), "authority_kinds"),
        authority_freshness=_ordered_unique_strings(
            payload.get("authority_freshness"), "authority_freshness"
        ),
        related_labels=tuple(labels),
    )


__all__ = [
    "RelatedLabelSpec",
    "SCHEMA_VOCABULARIES_PATH",
    "SchemaVocabularyError",
    "WikiSchemaVocabularies",
    "load_wiki_schema_vocabularies",
]
