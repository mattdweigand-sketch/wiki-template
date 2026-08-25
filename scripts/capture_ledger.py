#!/usr/bin/env python3
"""Parse and validate the exact capture-application ledger."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, NewType

from _durable_files import DurableFileError, read_regular_bytes
from _repo_paths import MAY_CREATE_FILE, RepoPathError, resolve_repo_path
from _strict_json import reject_duplicate_json_keys


ALLOWED_CAPTURE_ROOTS = (
    "wiki/", "scripts/", "workflows/", ".agents/", ".claude/",
)
ALLOWED_CAPTURE_ROOT_FILES = {
    "AGENTS.md", "CLAUDE.md", "CONTEXT.md", "README.md", "REFERENCES.md",
}
CAPTURE_LEDGER_RECORD_TYPES = frozenset({"capture_application"})
CAPTURE_APPLICATION_BOUNDARIES = frozenset(
    {"analysis-capture", "artifact-promotion", "synthesis-promotion"}
)
CAPTURE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

CaptureLedgerLineSha256 = NewType("CaptureLedgerLineSha256", str)


class CaptureLedgerIntegrityError(ValueError):
    """The exact capture ledger failed deterministic validation."""

    def __init__(self, failures: str | list[str] | tuple[str, ...]) -> None:
        normalized = (failures,) if isinstance(failures, str) else tuple(failures)
        self.failures = normalized
        super().__init__("capture ledger integrity check failed: " + "; ".join(normalized))


@dataclass(frozen=True)
class ValidatedCaptureLedgerLine:
    record: dict[str, object]
    line_no: int
    line_text: str
    sha256: CaptureLedgerLineSha256


@dataclass(frozen=True)
class CaptureLedgerValidation:
    errors: tuple[str, ...]
    application_count: int
    applications: tuple[ValidatedCaptureLedgerLine, ...]


def is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_capture_timestamp(value: object, *, field: str) -> str | None:
    if not is_nonempty_string(value):
        return f"{field} must be a non-empty string"
    normalized = value.removesuffix("Z") + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return f"{field} must be ISO-8601 parseable"
    return None


def validate_capture_paths(
    editable_scope: list[str],
    *,
    primary_destination: object,
    repo_root: Path,
) -> list[str]:
    """Validate exact capture destinations against the durable write boundary."""
    errors: list[str] = []
    if primary_destination not in editable_scope:
        errors.append("primary_destination must be included in editable_scope")
    for path in editable_scope:
        try:
            resolve_repo_path(
                path,
                repo_root=repo_root,
                allowed_prefixes=tuple(
                    prefix.rstrip("/") for prefix in ALLOWED_CAPTURE_ROOTS
                ),
                allowed_root_files=ALLOWED_CAPTURE_ROOT_FILES,
                mode=MAY_CREATE_FILE,
            )
        except RepoPathError:
            errors.append(f"editable_scope path is outside the capture boundary: {path}")
    return errors


def _capture_ledger_line_sha256(line: str) -> CaptureLedgerLineSha256:
    return CaptureLedgerLineSha256(hashlib.sha256(line.encode("utf-8")).hexdigest())


def _capture_ledger_json_too_deep(value: object, maximum_depth: int = 128) -> bool:
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > maximum_depth:
            return True
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
    return False


def _validate_capture_ledger_schema(record: dict[str, object], line_no: int) -> list[str]:
    errors: list[str] = []
    if line_no != 1:
        errors.append("schema record must be the first line")
    if set(record) != {"record_type", "schema_version", "description"}:
        errors.append("schema record has missing or unknown fields")
    if not is_strict_int(record.get("schema_version")) or record.get("schema_version") != 1:
        errors.append("schema record must have schema_version 1")
    if not is_nonempty_string(record.get("description")):
        errors.append("schema record must have a description")
    return errors


def validate_capture_application(record: dict[str, object]) -> list[str]:
    """Validate the only supported capture-ledger application record."""
    fields = {
        "record_type", "schema_version", "application_status", "applied_at",
        "authorization_digest", "capture_boundary", "purpose",
        "primary_destination", "editable_scope", "targets",
    }
    errors: list[str] = []
    if set(record) != fields:
        missing = sorted(fields - set(record))
        unknown = sorted(set(record) - fields)
        if missing:
            errors.append(f"capture application missing fields: {missing}")
        if unknown:
            errors.append(f"capture application has unknown fields: {unknown}")
    schema_version = record.get("schema_version")
    if not is_strict_int(schema_version) or schema_version not in {2, 3}:
        errors.append("capture application must have schema_version 2 or 3")
    if record.get("application_status") != "applied":
        errors.append("application_status must be applied")
    timestamp_error = validate_capture_timestamp(
        record.get("applied_at"), field="applied_at"
    )
    if timestamp_error:
        errors.append(timestamp_error)
    digest = record.get("authorization_digest")
    if not isinstance(digest, str) or not CAPTURE_SHA256_RE.fullmatch(digest):
        errors.append("authorization_digest must be 64 lowercase hex characters")
    capture_boundary = record.get("capture_boundary")
    if (
        not isinstance(capture_boundary, str)
        or capture_boundary not in CAPTURE_APPLICATION_BOUNDARIES
    ):
        errors.append(
            f"capture_boundary must be one of {sorted(CAPTURE_APPLICATION_BOUNDARIES)}"
        )
    for field in ("purpose", "primary_destination"):
        if not is_nonempty_string(record.get(field)):
            errors.append(f"{field} must be a non-empty string")

    scope = record.get("editable_scope")
    if (
        not isinstance(scope, list)
        or not scope
        or not all(is_nonempty_string(path) for path in scope)
        or scope != sorted(set(scope))
    ):
        errors.append("editable_scope must be a non-empty sorted unique path list")
        scope = []
    else:
        errors.extend(
            validate_capture_paths(
                scope,
                primary_destination=record.get("primary_destination"),
                repo_root=Path.cwd(),
            )
        )

    targets = record.get("targets")
    target_paths: list[str] = []
    if not isinstance(targets, list) or not targets:
        errors.append("targets must be a non-empty list")
    else:
        for index, target in enumerate(targets):
            target_fields = {"path", "preimage_sha256", "postimage_sha256"}
            if schema_version == 3:
                target_fields |= {"preimage_mode", "postimage_mode"}
            if not isinstance(target, dict) or set(target) != target_fields:
                errors.append(f"targets[{index}] has invalid fields")
                continue
            path = target.get("path")
            if not is_nonempty_string(path):
                errors.append(f"targets[{index}].path must be non-empty")
            else:
                target_paths.append(path)
            preimage = target.get("preimage_sha256")
            postimage = target.get("postimage_sha256")
            if preimage is not None and (
                not isinstance(preimage, str)
                or not CAPTURE_SHA256_RE.fullmatch(preimage)
            ):
                errors.append(
                    f"targets[{index}].preimage_sha256 must be null or lowercase SHA-256"
                )
            if (
                not isinstance(postimage, str)
                or not CAPTURE_SHA256_RE.fullmatch(postimage)
            ):
                errors.append(
                    f"targets[{index}].postimage_sha256 must be lowercase SHA-256"
                )
            if schema_version == 3:
                preimage_mode = target.get("preimage_mode")
                postimage_mode = target.get("postimage_mode")
                if preimage is None:
                    if preimage_mode is not None:
                        errors.append(f"targets[{index}].preimage_mode must be null")
                elif (
                    not is_strict_int(preimage_mode)
                    or not 0 <= preimage_mode <= 0o7777
                ):
                    errors.append(f"targets[{index}].preimage_mode is invalid")
                if (
                    not is_strict_int(postimage_mode)
                    or not 0 <= postimage_mode <= 0o7777
                ):
                    errors.append(f"targets[{index}].postimage_mode is invalid")
    if target_paths != sorted(set(target_paths)):
        errors.append("target paths must be sorted and unique")
    if target_paths != scope:
        errors.append("target paths must exactly match editable_scope")
    return errors


def validate_capture_ledger_text(
    text: str,
    validate_application: Callable[[dict[str, object]], list[str]] = validate_capture_application,
) -> CaptureLedgerValidation:
    """Validate exact JSONL bytes after UTF-8 decoding."""
    if not text:
        return CaptureLedgerValidation(
            ("expected exactly one schema record, found 0",), 0, ()
        )
    if not text.strip():
        return CaptureLedgerValidation(
            ("capture ledger contains only whitespace",), 0, ()
        )

    lines = text.splitlines()
    errors: list[str] = []
    applications: list[ValidatedCaptureLedgerLine] = []
    schema_count = 0
    seen_digests: set[str] = set()
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"line {line_no}: blank lines are not allowed")
            continue
        try:
            record = json.loads(
                line, object_pairs_hook=reject_duplicate_json_keys
            )
        except (ValueError, RecursionError) as exc:
            errors.append(f"line {line_no}: invalid JSON: {getattr(exc, 'msg', str(exc))}")
            continue
        if _capture_ledger_json_too_deep(record):
            errors.append(f"line {line_no}: maximum JSON nesting depth exceeded")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {line_no}: record must be a JSON object")
            continue
        record_type = record.get("record_type")
        if record_type == "schema":
            schema_count += 1
            errors.extend(
                f"line {line_no}: {error}"
                for error in _validate_capture_ledger_schema(record, line_no)
            )
            continue
        if record_type not in CAPTURE_LEDGER_RECORD_TYPES:
            errors.append(f"line {line_no}: unsupported record_type {record_type!r}")
            continue
        errors.extend(
            f"line {line_no}: {error}" for error in validate_application(record)
        )
        digest = record.get("authorization_digest")
        if isinstance(digest, str):
            if digest in seen_digests:
                errors.append(
                    f"line {line_no}: duplicate capture application authorization_digest"
                )
            seen_digests.add(digest)
        applications.append(
            ValidatedCaptureLedgerLine(
                record=record,
                line_no=line_no,
                line_text=line,
                sha256=_capture_ledger_line_sha256(line),
            )
        )
    if schema_count != 1:
        errors.append(f"expected exactly one schema record, found {schema_count}")
    return CaptureLedgerValidation(
        tuple(errors), len(applications), tuple(applications)
    )


def validate_capture_ledger_file(
    path: Path,
    validate_application: Callable[[dict[str, object]], list[str]] = validate_capture_application,
) -> tuple[list[str], int]:
    """Read and validate one exact capture ledger file."""
    try:
        content, _ = read_regular_bytes(path)
    except (OSError, DurableFileError) as exc:
        return [f"cannot read {path}: {exc}"], 0
    assert content is not None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"{path} is not valid UTF-8: {exc}"], 0
    result = validate_capture_ledger_text(text, validate_application)
    return list(result.errors), result.application_count


__all__ = [
    "ALLOWED_CAPTURE_ROOT_FILES",
    "ALLOWED_CAPTURE_ROOTS",
    "CAPTURE_LEDGER_RECORD_TYPES",
    "CAPTURE_APPLICATION_BOUNDARIES",
    "CaptureLedgerIntegrityError",
    "CaptureLedgerValidation",
    "ValidatedCaptureLedgerLine",
    "is_nonempty_string",
    "is_strict_int",
    "validate_capture_ledger_file",
    "validate_capture_ledger_text",
    "validate_capture_application",
    "validate_capture_paths",
    "validate_capture_timestamp",
]
