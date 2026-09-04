#!/usr/bin/env python3
"""Serialize newest-first records into ``wiki/log.md``."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from _durable_files import (
    DurableFileError,
    FaultHook,
    atomic_replace_bytes,
    read_regular_bytes,
    sha256_bytes,
    stable_lock,
)
from _wiki_parse import parse_log_entry_date


WIKI_LOG_PATH = Path("wiki/log.md")
WIKI_LOG_LOCK_PATH = Path("scripts/.wiki-log.lock")


class WikiLogError(RuntimeError):
    """A log entry or durable log write violated the record contract."""


@dataclass(frozen=True)
class WikiLogRecordResult:
    """Observable result of one serialized log-record attempt."""

    result_code: str
    sha256: str


def _decode_utf8(content: bytes, label: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WikiLogError(f"{label} is not valid UTF-8: {exc}") from exc


def _normalized_log_entry(entry: bytes) -> tuple[str, bytes]:
    text = _decode_utf8(entry, "log entry")
    lines = text.splitlines()
    if not lines or parse_log_entry_date(lines[0]) is None:
        raise WikiLogError("log entry must start with one recognized dated header")
    try:
        date.fromisoformat(parse_log_entry_date(lines[0]) or "")
    except ValueError as exc:
        raise WikiLogError("log entry header contains an invalid calendar date") from exc
    headers = [line for line in lines if line.startswith("## ")]
    if len(headers) != 1:
        raise WikiLogError("log entry must contain exactly one level-two header")
    normalized_text = text.rstrip("\r\n") + "\n\n"
    return normalized_text, normalized_text.encode("utf-8")


def render_wiki_log_postimage(preimage: bytes, entry: bytes) -> bytes:
    """Return the exact newest-first log bytes for one validated entry."""
    log_text = _decode_utf8(preimage, "wiki log")
    entry_text, normalized_entry = _normalized_log_entry(entry)
    if entry_text in log_text:
        return preimage

    lines = log_text.splitlines(keepends=True)
    insertion = len(log_text)
    offset = 0
    for line in lines:
        if parse_log_entry_date(line) is not None:
            insertion = offset
            break
        offset += len(line)
    prefix = log_text[:insertion]
    suffix = log_text[insertion:]
    if prefix and not prefix.endswith("\n\n"):
        prefix = prefix.rstrip("\r\n") + "\n\n"
    rendered = prefix.encode("utf-8") + normalized_entry + suffix.encode("utf-8")
    _decode_utf8(rendered, "rendered wiki log")
    return rendered


def record_wiki_log_entry(
    repo_root: Path,
    entry: bytes,
    *,
    fault: FaultHook | None = None,
) -> WikiLogRecordResult:
    """Record one entry under a stable lock and atomically install the result."""
    root = repo_root.resolve()
    log_path = root / WIKI_LOG_PATH
    lock_path = root / WIKI_LOG_LOCK_PATH
    try:
        with stable_lock(lock_path):
            preimage, info = read_regular_bytes(log_path)
            assert preimage is not None and info is not None
            postimage = render_wiki_log_postimage(preimage, entry)
            digest = sha256_bytes(postimage)
            if postimage == preimage:
                return WikiLogRecordResult("ALREADY_RECORDED", digest)
            atomic_replace_bytes(
                log_path,
                postimage,
                mode=stat.S_IMODE(info.st_mode),
                expected_sha256=sha256_bytes(preimage),
                fault=fault,
            )
            installed, _ = read_regular_bytes(log_path)
            if installed != postimage:
                raise WikiLogError("installed wiki log differs from rendered postimage")
            return WikiLogRecordResult("RECORDED", digest)
    except (DurableFileError, OSError) as exc:
        if isinstance(exc, WikiLogError):
            raise
        raise WikiLogError(str(exc)) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record", help="record one newest-first log entry")
    record.add_argument("--entry-file", required=True)
    record.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    entry_path = Path(args.entry_file)
    try:
        entry, _ = read_regular_bytes(entry_path)
        assert entry is not None
        result = record_wiki_log_entry(Path.cwd(), entry)
    except (DurableFileError, WikiLogError, OSError) as exc:
        print(f"wiki-log error: {exc}", file=sys.stderr)
        return 1
    payload = {"result_code": result.result_code, "sha256": result.sha256}
    print(json.dumps(payload, sort_keys=True) if args.json else result.result_code)
    return 0


__all__ = [
    "WikiLogError",
    "WikiLogRecordResult",
    "record_wiki_log_entry",
    "render_wiki_log_postimage",
]


if __name__ == "__main__":
    sys.exit(main())
