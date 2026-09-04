#!/usr/bin/env python3
"""Assemble one complete capture proposal from staged authored judgment."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path

from _durable_files import read_regular_bytes, sha256_bytes
from _repo_paths import EXISTING_FILE, MAY_CREATE_FILE, RepoPathError, resolve_repo_path
from _strict_json import DuplicateJsonKeyError, reject_duplicate_json_keys
from _wiki_parse import get_entity_pages
from capture_gate import (
    CAPTURE_LEDGER_PATH,
    CaptureProposalError,
    canonical_capture_proposal_bytes,
    prepare_capture_proposal,
)
from capture_ledger import (ALLOWED_CAPTURE_ROOT_FILES as ALLOWED_ROOT_FILES,
                            ALLOWED_CAPTURE_ROOTS as ALLOWED_ROOTS)
from rebuild_referenced_by import PageSnapshot, build_backlink_rebuild_plan, load_page_texts
from wiki_log import render_wiki_log_postimage


STAGING_REQUEST_FIELDS = {
    "schema_version",
    "capture_boundary",
    "purpose",
    "primary_destination",
    "authored_targets",
    "log_entry_path",
    "rebuild_referenced_by",
}
AUTHORED_TARGET_FIELDS = {"destination", "staged_path"}
DERIVED_TARGETS = {"wiki/log.md", CAPTURE_LEDGER_PATH}


class CaptureStagingError(ValueError):
    """A staging request cannot produce one safe final capture proposal."""


@dataclass(frozen=True)
class CaptureStagingResult:
    """Observable result of building one deterministic staging directory."""

    result_code: str
    proposal_path: str
    target_paths: tuple[str, ...]


def _existing_tmp_file(root: Path, value: object) -> str:
    return resolve_repo_path(
        value,
        repo_root=root,
        allowed_prefixes=("tmp",),
        mode=EXISTING_FILE,
    )


def _capture_destination(root: Path, value: object) -> str:
    return resolve_repo_path(
        value,
        repo_root=root,
        allowed_prefixes=tuple(prefix.rstrip("/") for prefix in ALLOWED_ROOTS),
        allowed_root_files=ALLOWED_ROOT_FILES,
        mode=MAY_CREATE_FILE,
    )


def _load_staging_request(root: Path, request_path: str) -> dict[str, object]:
    relative = _existing_tmp_file(root, request_path)
    content, _ = read_regular_bytes(root / relative)
    assert content is not None
    try:
        request = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        raise CaptureStagingError(f"invalid staging request: {exc}") from exc
    if not isinstance(request, dict) or set(request) != STAGING_REQUEST_FIELDS:
        raise CaptureStagingError("staging request has missing or unknown fields")
    if content != canonical_capture_proposal_bytes(request):
        raise CaptureStagingError("staging request must be canonical JSON with one trailing LF")
    if isinstance(request.get("schema_version"), bool) or request.get("schema_version") != 1:
        raise CaptureStagingError("staging request schema_version must be integer 1")
    if request.get("rebuild_referenced_by") is not True:
        raise CaptureStagingError("rebuild_referenced_by must be true for a final capture state")
    return request


def _output_relative(root: Path, output_directory: str) -> str:
    sentinel = f"{output_directory}/proposal.json"
    resolved = resolve_repo_path(
        sentinel,
        repo_root=root,
        allowed_prefixes=("tmp",),
        mode=MAY_CREATE_FILE,
    )
    return str(Path(resolved).parent.as_posix())


def _authored_postimages(
    root: Path,
    request: dict[str, object],
) -> tuple[dict[str, bytes], dict[str, int]]:
    raw_targets = request.get("authored_targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise CaptureStagingError("authored_targets must be a non-empty list")
    postimages: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    for index, target in enumerate(raw_targets):
        if not isinstance(target, dict) or set(target) != AUTHORED_TARGET_FIELDS:
            raise CaptureStagingError(f"authored_targets[{index}] has invalid fields")
        destination = _capture_destination(root, target.get("destination"))
        if destination in DERIVED_TARGETS:
            raise CaptureStagingError(f"caller may not declare derived target {destination}")
        if destination in postimages:
            raise CaptureStagingError(f"duplicate authored destination: {destination}")
        staged = _existing_tmp_file(root, target.get("staged_path"))
        content, staged_info = read_regular_bytes(root / staged)
        assert content is not None and staged_info is not None
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CaptureStagingError(f"authored target is not UTF-8: {staged}") from exc
        current, current_info = read_regular_bytes(root / destination, allow_missing=True)
        postimages[destination] = content
        modes[destination] = (
            stat.S_IMODE(current_info.st_mode) if current_info is not None else 0o644
        )
    primary = request.get("primary_destination")
    if not isinstance(primary, str) or primary not in postimages:
        raise CaptureStagingError("primary_destination must be an authored target")
    return postimages, modes


def _is_entity_markdown(relative: str) -> bool:
    parts = Path(relative).parts
    return len(parts) == 3 and parts[0] == "wiki" and relative.endswith(".md")


def _with_generated_backlinks(
    root: Path,
    authored: dict[str, bytes],
    modes: dict[str, int],
) -> tuple[dict[str, bytes], dict[str, int]]:
    wiki_root = root / "wiki"
    snapshot = load_page_texts(get_entity_pages(wiki_root))
    authored_entity_paths: set[Path] = set()
    for relative, content in authored.items():
        if not _is_entity_markdown(relative):
            continue
        path = root / relative
        authored_entity_paths.add(path)
        text = content.decode("utf-8")
        snapshot[path] = PageSnapshot(
            text=text,
            content=content,
            sha256=sha256_bytes(content),
            mode=modes[relative],
        )
    changed, _counts = build_backlink_rebuild_plan(snapshot, wiki_root)
    final = dict(authored)
    final_modes = dict(modes)
    for path, text in changed.items():
        relative = path.relative_to(root).as_posix()
        final[relative] = text.encode("utf-8")
        final_modes[relative] = snapshot[path].mode
    for path in authored_entity_paths:
        relative = path.relative_to(root).as_posix()
        if path not in changed:
            final[relative] = snapshot[path].content
    return final, final_modes


def _with_log_postimage(
    root: Path,
    request: dict[str, object],
    postimages: dict[str, bytes],
    modes: dict[str, int],
) -> None:
    entry_relative = _existing_tmp_file(root, request.get("log_entry_path"))
    entry, _ = read_regular_bytes(root / entry_relative)
    log_preimage, log_info = read_regular_bytes(root / "wiki/log.md")
    assert entry is not None and log_preimage is not None and log_info is not None
    postimages["wiki/log.md"] = render_wiki_log_postimage(log_preimage, entry)
    modes["wiki/log.md"] = stat.S_IMODE(log_info.st_mode)


def _changed_postimages(
    root: Path,
    primary_destination: str,
    postimages: dict[str, bytes],
    modes: dict[str, int],
) -> tuple[dict[str, bytes], dict[str, int]]:
    changed: dict[str, bytes] = {}
    changed_modes: dict[str, int] = {}
    for relative, content in postimages.items():
        preimage, preimage_info = read_regular_bytes(root / relative, allow_missing=True)
        preimage_mode = stat.S_IMODE(preimage_info.st_mode) if preimage_info is not None else None
        if preimage == content and preimage_mode == modes[relative]:
            continue
        changed[relative] = content
        changed_modes[relative] = modes[relative]
    if primary_destination not in changed:
        raise CaptureStagingError("primary destination has no final byte or mode change")
    return changed, changed_modes


def _proposal_outputs(
    root: Path,
    output_relative: str,
    request: dict[str, object],
    postimages: dict[str, bytes],
    modes: dict[str, int],
) -> dict[str, bytes]:
    target_paths = sorted(postimages)
    targets: list[dict[str, object]] = []
    files: dict[str, bytes] = {}
    target_summaries: list[dict[str, object]] = []
    for index, destination in enumerate(target_paths):
        content = postimages[destination]
        preimage, preimage_info = read_regular_bytes(root / destination, allow_missing=True)
        staged_relative = (
            f"{output_relative}/postimages/{index:04d}-"
            + destination.replace("/", "--")
        )
        files[staged_relative] = content
        targets.append(
            {
                "destination": destination,
                "expected_preimage": "ABSENT" if preimage is None else sha256_bytes(preimage),
                "expected_preimage_mode": (
                    None if preimage_info is None else stat.S_IMODE(preimage_info.st_mode)
                ),
                "staged_path": staged_relative,
                "postimage_sha256": sha256_bytes(content),
                "postimage_mode": modes[destination],
            }
        )
        target_summaries.append(
            {
                "destination": destination,
                "postimage_sha256": sha256_bytes(content),
                "postimage_mode": modes[destination],
            }
        )
    proposal = {
        "schema_version": 2,
        "capture_boundary": request["capture_boundary"],
        "purpose": request["purpose"],
        "primary_destination": request["primary_destination"],
        "editable_scope": target_paths,
        "targets": targets,
    }
    files[f"{output_relative}/proposal.json"] = canonical_capture_proposal_bytes(proposal)
    files[f"{output_relative}/staging-result.json"] = canonical_capture_proposal_bytes(
        {
            "schema_version": 1,
            "proposal_path": f"{output_relative}/proposal.json",
            "targets": target_summaries,
        }
    )
    return files


def _install_or_match_staging_files(
    root: Path,
    output_relative: str,
    files: dict[str, bytes],
) -> str:
    output = root / output_relative
    if output.exists() and (output.is_symlink() or not output.is_dir()):
        raise CaptureStagingError(f"staging output is not a safe directory: {output_relative}")
    # Reject redirected output descendants before any scratch write.
    if output.exists():
        for path in output.rglob("*"):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise CaptureStagingError(f"unsafe staging output entry: {path.relative_to(root)}")
    existing_files = (
        {
            path.relative_to(root).as_posix(): path
            for path in output.rglob("*")
            if path.is_file()
        }
        if output.exists()
        else {}
    )
    if existing_files:
        if set(existing_files) != set(files):
            raise CaptureStagingError("existing staging output has a different file set")
        for relative, path in existing_files.items():
            content, info = read_regular_bytes(path)
            if content != files[relative] or info is None or stat.S_IMODE(info.st_mode) != 0o644:
                raise CaptureStagingError(f"existing staging output differs: {relative}")
        return "ALREADY_STAGED"
    output.mkdir(parents=True, exist_ok=True)
    for relative, content in sorted(files.items()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o644)
    return "STAGED"


def stage_capture_proposal(
    repo_root: Path,
    request_path: str,
    output_directory: str,
) -> CaptureStagingResult:
    """Build or verify one deterministic final-state proposal under ``tmp/``."""
    root = repo_root.resolve()
    try:
        request = _load_staging_request(root, request_path)
        output_relative = _output_relative(root, output_directory)
        authored, modes = _authored_postimages(root, request)
        postimages, modes = _with_generated_backlinks(root, authored, modes)
        _with_log_postimage(root, request, postimages, modes)
        primary = str(request["primary_destination"])
        postimages, modes = _changed_postimages(root, primary, postimages, modes)
        files = _proposal_outputs(root, output_relative, request, postimages, modes)
        result_code = _install_or_match_staging_files(root, output_relative, files)
        proposal_path = f"{output_relative}/proposal.json"
        prepare_capture_proposal(root, proposal_path)
        return CaptureStagingResult(result_code, proposal_path, tuple(sorted(postimages)))
    except (CaptureProposalError, RepoPathError, OSError, ValueError) as exc:
        if isinstance(exc, CaptureStagingError):
            raise
        raise CaptureStagingError(str(exc)) from exc


__all__ = [
    "CaptureStagingError",
    "CaptureStagingResult",
    "stage_capture_proposal",
]
