#!/usr/bin/env python3
"""Verify exact capture records against immutable Git objects in a revision range."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from capture_gate import CAPTURE_LEDGER_PATH
from capture_ledger import validate_capture_application, validate_capture_ledger_text


class CaptureDiffError(ValueError):
    """The requested Git comparison cannot be inspected safely."""


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, check=check, capture_output=True, input=b""
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CaptureDiffError(f"git {' '.join(args)} failed: {exc}") from exc


def _verify_revision(root: Path, revision: str) -> None:
    if not revision or revision.startswith("-"):
        raise CaptureDiffError(f"invalid revision {revision!r}")
    _git(root, "rev-parse", "--verify", f"{revision}^{{tree}}")


def _object_bytes(root: Path, revision: str, path: str) -> bytes | None:
    listing = _git(root, "ls-tree", "-z", revision, "--", path).stdout
    if not listing:
        return None
    metadata, _path = listing.rstrip(b"\0").split(b"\t", 1)
    mode, kind, object_id = metadata.split()
    if kind != b"blob" or mode not in {b"100644", b"100755"}:
        raise CaptureDiffError(f"not a regular Git file: {revision}:{path}")
    return _git(root, "cat-file", "blob", object_id.decode()).stdout


def _object_mode(root: Path, revision: str, path: str) -> int | None:
    completed = _git(root, "ls-tree", revision, "--", path)
    if not completed.stdout:
        return None
    first = completed.stdout.split(b" ", 1)[0]
    try:
        return int(first, 8) & 0o7777
    except ValueError as exc:
        raise CaptureDiffError(f"cannot parse Git mode for {revision}:{path}") from exc


def _state(root: Path, revision: str, path: str) -> tuple[str | None, int | None]:
    content = _object_bytes(root, revision, path)
    if content is None:
        return None, None
    return hashlib.sha256(content).hexdigest(), _object_mode(root, revision, path)


def _changed_paths(root: Path, base: str, head: str, *, added_only: bool = False) -> set[str]:
    args = ["diff", "--no-renames", "--name-only", "-z"]
    if added_only:
        args.append("--diff-filter=A")
    args.extend([base, head, "--"])
    output = _git(root, *args).stdout
    return {
        item.decode("utf-8")
        for item in output.split(b"\0")
        if item
    }


def _new_application_records(
    root: Path, base: str, head: str
) -> tuple[list[dict[str, object]], list[str]]:
    base_ledger = _object_bytes(root, base, CAPTURE_LEDGER_PATH) or b""
    head_ledger = _object_bytes(root, head, CAPTURE_LEDGER_PATH)
    if head_ledger is None:
        if base_ledger:
            return [], [f"{CAPTURE_LEDGER_PATH} was deleted"]
        return [], []
    if not head_ledger.startswith(base_ledger):
        return [], [f"{CAPTURE_LEDGER_PATH} is not append-only across the range"]
    delta = head_ledger[len(base_ledger):]
    if not delta:
        return [], []
    if base_ledger and not base_ledger.endswith(b"\n"):
        return [], [f"{CAPTURE_LEDGER_PATH} base revision lacks a trailing newline"]
    try:
        validation = validate_capture_ledger_text(
            head_ledger.decode("utf-8"),
            lambda record: validate_capture_application(record, repo_root=root),
        )
    except UnicodeDecodeError as exc:
        return [], [f"capture ledger is not UTF-8: {exc}"]
    # The schema header belongs to the ledger, never to an application.
    records = [line.record for line in validation.applications
               if line.line_no > len(base_ledger.splitlines())]
    return records, list(validation.errors)


def _capture_transition_problems(repo_root: Path, base_revision: str, head_revision: str) -> list[str]:
    root = repo_root.resolve()
    try:
        _verify_revision(root, base_revision)
        _verify_revision(root, head_revision)
        changed = _changed_paths(root, base_revision, head_revision)
        added = _changed_paths(root, base_revision, head_revision, added_only=True)
        records, problems = _new_application_records(root, base_revision, head_revision)
    except CaptureDiffError as exc:
        return [str(exc)]

    path_states: dict[str, tuple[str | None, int | None]] = {}
    captured_paths: set[str] = set()
    analysis_primaries: set[str] = set()
    for record_index, record in enumerate(records, start=1):
        errors = validate_capture_application(record, repo_root=root)
        problems.extend(
            f"capture application {record_index}: {error}" for error in errors
        )
        if errors:
            continue
        if record.get("capture_boundary") == "analysis-capture":
            primary = record.get("primary_destination")
            if isinstance(primary, str):
                analysis_primaries.add(primary)
        targets = record.get("targets")
        if not isinstance(targets, list):
            continue
        for target in targets:
            if not isinstance(target, dict) or not isinstance(target.get("path"), str):
                continue
            path = str(target["path"])
            captured_paths.add(path)
            if path not in changed:
                problems.append(
                    f"capture application {record_index}: target was not changed: {path}"
                )
            current = path_states.setdefault(
                path, _state(root, base_revision, path)
            )
            expected = (target.get("preimage_sha256"), target.get("preimage_mode"))
            mode_mismatch = (record["schema_version"] == 3 and current[1] is not None
                             and expected[1] != current[1])
            if expected[0] != current[0] or mode_mismatch:
                problems.append(
                    f"capture application {record_index}: preimage state mismatch for {path}"
                )
            postimage = (target.get("postimage_sha256"), target.get("postimage_mode"))
            if postimage == expected:
                problems.append(
                    f"capture application {record_index}: target has unchanged postimage: {path}"
                )
            # A legacy record carries no mode proof, including for intermediate states.
            path_states[path] = postimage

    for path in sorted(captured_paths):
        final_state = _state(root, head_revision, path)
        expected_state = path_states[path]
        if (expected_state[0] != final_state[0]
                or expected_state[1] is not None and expected_state[1] != final_state[1]):
            problems.append(f"capture application postimage state mismatch for {path}")

    new_analyses = {
        path for path in added
        if path.startswith("wiki/analyses/") and path.endswith(".md")
    }
    for path in sorted(new_analyses - analysis_primaries):
        problems.append(f"new analysis lacks a matching analysis-capture record: {path}")
    return sorted(set(problems))


def _merge_capture_problems(root: Path, parents: list[str], head: str) -> list[str]:
    """A merge may inherit applications, but must not invent or discard them."""
    ledger = _object_bytes(root, head, CAPTURE_LEDGER_PATH) or b""
    inherited = [_object_bytes(root, parent, CAPTURE_LEDGER_PATH) or b"" for parent in parents]
    problems: list[str] = []
    if ledger not in inherited:
        problems.append("merge introduces capture records; apply captures in a separate non-merge commit")
    if any(not ledger.startswith(previous) for previous in inherited):
        problems.append("merge discards or rewrites a parent capture ledger; rebase divergent capture histories")
    # A new analysis brought in from a side branch must survive the merge exactly.
    for path in _changed_paths(root, parents[0], head, added_only=True):
        if path.startswith("wiki/analyses/") and path.endswith(".md"):
            if not any(_state(root, parent, path) == _state(root, head, path) for parent in parents):
                problems.append(f"merge adds or rewrites a new analysis without an exact parent: {path}")
    return problems


def capture_diff_problems(repo_root: Path, base_revision: str, head_revision: str) -> list[str]:
    """Check applications at their introducing commits, or one staged tree."""
    root = repo_root.resolve()
    try:
        initial_push = base_revision == "0" * 40
        if initial_push:
            base_revision = _git(root, "hash-object", "-w", "-t", "tree", "--stdin").stdout.decode().strip()
        _verify_revision(root, base_revision)
        _verify_revision(root, head_revision)
        base_commit = _git(root, "rev-parse", "--verify", f"{base_revision}^{{commit}}", check=False)
        head_commit = _git(root, "rev-parse", "--verify", f"{head_revision}^{{commit}}", check=False)
        if (base_commit.returncode and not initial_push) or head_commit.returncode:
            return _capture_transition_problems(root, base_revision, head_revision)
        base = base_revision if initial_push else base_commit.stdout.decode().strip()
        head = head_commit.stdout.decode().strip()
        if not initial_push and _git(root, "merge-base", "--is-ancestor", base, head, check=False).returncode:
            return ["capture range base must be an ancestor of head"]
        _records, problems = _new_application_records(root, base, head)
        commits = _git(root, "rev-list", "--reverse", "--topo-order", head if initial_push else f"{base}..{head}").stdout.decode().splitlines()
        for commit in commits:
            header = _git(root, "cat-file", "-p", commit).stdout.decode().split("\n\n", 1)[0]
            parents = [line.split()[1] for line in header.splitlines() if line.startswith("parent ")]
            for parent in parents:
                _verify_revision(root, parent)
            if len(parents) == 1:
                errors = _capture_transition_problems(root, parents[0], commit)
            elif len(parents) > 1:
                errors = _merge_capture_problems(root, parents, commit)
            elif initial_push:
                errors = _capture_transition_problems(root, base, commit)
            else:
                errors = ["unexpected root commit inside an ancestral capture range"]
            problems.extend(f"{commit[:12]}: {error}" for error in errors)
        return sorted(set(problems))
    except CaptureDiffError as exc:
        return [str(exc)]


__all__ = ["CaptureDiffError", "capture_diff_problems"]
