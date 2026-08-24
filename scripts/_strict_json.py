#!/usr/bin/env python3
"""Shared duplicate-key rejection for strict JSON contracts."""

from __future__ import annotations


class DuplicateJsonKeyError(ValueError):
    """A JSON object repeated a key that strict parsing must reject."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"duplicate JSON key: {key}")


def reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Build one JSON object while rejecting repeated keys at every depth."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(key)
        result[key] = value
    return result


__all__ = ["DuplicateJsonKeyError", "reject_duplicate_json_keys"]
