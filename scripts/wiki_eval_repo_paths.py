#!/usr/bin/env python3
"""Regression eval for repository-relative path confinement."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from eval_lib import Results

results = Results()
check = results.record

try:
    repo_paths = importlib.import_module("_repo_paths")
except ImportError:
    repo_paths = None
check("shared-repo-path-module-present", repo_paths is not None)

with tempfile.TemporaryDirectory() as td:
    path_root = Path(td) / "repo"
    (path_root / "raw" / "notes").mkdir(parents=True)
    (path_root / "wiki" / "sources").mkdir(parents=True)
    (path_root / "tmp").mkdir()
    (path_root / "AGENTS.md").write_text("agent map", encoding="utf-8")
    (path_root / "raw" / "notes" / "inside.txt").write_text("inside", encoding="utf-8")
    (path_root / "wiki" / "sources" / "inside.md").write_text("inside", encoding="utf-8")
    (path_root / "wiki" / "index.md").write_text("index", encoding="utf-8")
    outside = Path(td) / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (path_root / "raw" / "notes" / "escape.txt").symlink_to(outside)
    (path_root / "raw" / "notes" / "loop-a").symlink_to("loop-b")
    (path_root / "raw" / "notes" / "loop-b").symlink_to("loop-a")
    (path_root / "alias").symlink_to("raw", target_is_directory=True)
    (path_root / "ROOT.md").symlink_to("raw/notes/inside.txt")
    if hasattr(os, "mkfifo"):
        os.mkfifo(path_root / "raw" / "notes" / "pipe")

    path_results: dict[str, object] = {}
    if repo_paths is not None:
        resolve_repo_path = getattr(repo_paths, "resolve_repo_path", None)
        RepoPathError = getattr(repo_paths, "RepoPathError", ValueError)

        def resolve(value: str, prefixes: tuple[str, ...], mode: str = "existing_file"):
            return resolve_repo_path(
                value,
                repo_root=path_root,
                allowed_prefixes=prefixes,
                mode=mode,
            )

        for value in (
            "raw/../outside.txt",
            "wiki/sources/../../outside.md",
            "/absolute.txt",
            "raw\\notes\\inside.txt",
            "https://example.com/source",
            "raw//notes/inside.txt",
            "raw/./notes/inside.txt",
            "raw/notes/escape.txt",
            "raw/notes/loop-a",
        ):
            try:
                resolve(value, ("raw", "wiki/sources"))
            except RepoPathError:
                path_results[value] = "rejected"
            except Exception as exc:
                path_results[value] = type(exc).__name__
            else:
                path_results[value] = "accepted"
        try:
            path_results["valid_raw"] = resolve("raw/notes/inside.txt", ("raw",))
            path_results["valid_wiki"] = resolve("wiki/sources/inside.md", ("wiki/sources",))
            path_results["create"] = resolve(
                "tmp/not-created.md", ("tmp",), mode="may_create_file"
            )
            path_results["generator_prefixes"] = resolve_repo_path(
                "wiki/sources/inside.md",
                repo_root=path_root,
                allowed_prefixes=(value for value in ("wiki/sources",)),
                mode="existing_file",
            )
            path_results["exact_root"] = resolve_repo_path(
                "AGENTS.md",
                repo_root=path_root,
                allowed_root_files=("AGENTS.md",),
                mode="existing_file",
            )
            try:
                resolve("wiki/index.md/child.md", ("wiki",), mode="may_create_file")
            except RepoPathError:
                path_results["file_parent_create"] = "rejected"
            else:
                path_results["file_parent_create"] = "accepted"
            try:
                resolve("alias/notes/inside.txt", ("alias",))
            except RepoPathError:
                path_results["symlinked_root"] = "rejected"
            else:
                path_results["symlinked_root"] = "accepted"
            try:
                resolve_repo_path(
                    "ROOT.md",
                    repo_root=path_root,
                    allowed_root_files=("ROOT.md",),
                    mode="existing_file",
                )
            except RepoPathError:
                path_results["symlinked_root_file"] = "rejected"
            else:
                path_results["symlinked_root_file"] = "accepted"
            if hasattr(os, "mkfifo"):
                try:
                    resolve("raw/notes/pipe", ("raw",), mode="may_create_file")
                except RepoPathError:
                    path_results["existing_special_file"] = "rejected"
                else:
                    path_results["existing_special_file"] = "accepted"
            else:
                path_results["existing_special_file"] = "unsupported"
        except Exception as exc:
            path_results["valid_error"] = type(exc).__name__

    unsafe_values = {
        "raw/../outside.txt",
        "wiki/sources/../../outside.md",
        "/absolute.txt",
        "raw\\notes\\inside.txt",
        "https://example.com/source",
        "raw//notes/inside.txt",
        "raw/./notes/inside.txt",
        "raw/notes/escape.txt",
        "raw/notes/loop-a",
    }
    check(
        "repo-path-unsafe-inputs-rejected",
        repo_paths is not None
        and all(path_results.get(value) == "rejected" for value in unsafe_values),
        detail=str(path_results),
    )
    check(
        "repo-path-valid-existing-and-create-modes",
        repo_paths is not None
        and path_results.get("valid_raw") == "raw/notes/inside.txt"
        and path_results.get("valid_wiki") == "wiki/sources/inside.md"
        and path_results.get("create") == "tmp/not-created.md",
        detail=str(path_results),
    )
    check(
        "repo-path-materializes-one-shot-scope-iterables",
        path_results.get("generator_prefixes") == "wiki/sources/inside.md",
        detail=str(path_results),
    )
    check(
        "repo-path-exact-root-file",
        repo_paths is not None and path_results.get("exact_root") == "AGENTS.md",
        detail=str(path_results),
    )
    check(
        "repo-path-create-requires-directory-parent",
        repo_paths is not None and path_results.get("file_parent_create") == "rejected",
        detail=str(path_results),
    )
    check(
        "repo-path-rejects-symlinked-authority-roots",
        repo_paths is not None
        and path_results.get("symlinked_root") == "rejected"
        and path_results.get("symlinked_root_file") == "rejected",
        detail=str(path_results),
    )
    check(
        "repo-path-create-rejects-special-file",
        repo_paths is not None
        and path_results.get("existing_special_file") in {"rejected", "unsupported"},
        detail=str(path_results),
    )

raise SystemExit(results.finish())
