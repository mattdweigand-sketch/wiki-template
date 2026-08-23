#!/usr/bin/env python3
"""Regression eval for export_wiki.py template include/exclude boundaries."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import export_wiki
import restore_wiki
from _file_transactions import run_transaction
from eval_lib import Results
from wiki_provenance import resolve_restored_source_closure


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT = REPO_ROOT / "scripts" / "export_wiki.py"

results = Results()


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fake_rclone(
    root: Path,
    *,
    target: str = "gdrive:wiki-exports/wiki-export.zip",
    size_delta: int = 0,
    configured: bool = False,
    corrupt: bool = False,
) -> Path:
    path = root / "rclone"
    state = root / "configured-remotes.txt"
    if configured:
        state.write_text("gdrive\n", encoding="utf-8")
    path.write_text(f"""#!{sys.executable}
import hashlib
import pathlib
import shutil
import sys

here = pathlib.Path(sys.argv[0]).parent
configured = here / "configured-remotes.txt"
config_calls = here / "config-calls.txt"
remote_zip = here / "remote.zip"
target = {target!r}
size_delta = {size_delta}
command = sys.argv[1] if len(sys.argv) > 1 else ""

def remote_names():
    if not configured.exists():
        return []
    return [line.strip() for line in configured.read_text().splitlines() if line.strip()]

if command == "listremotes":
    for remote in remote_names():
        print(remote + ":")
elif command == "config":
    if len(sys.argv) != 6 or sys.argv[2:6] != ["create", "gdrive", "drive", "config_is_local=true"]:
        print("unexpected config args", file=sys.stderr)
        sys.exit(2)
    config_calls.write_text(config_calls.read_text() + "x" if config_calls.exists() else "x")
    names = remote_names()
    if "gdrive" not in names:
        names.append("gdrive")
    configured.write_text("\\n".join(names) + "\\n")
elif command == "copyto":
    if len(sys.argv) != 4 or sys.argv[3] != target:
        print("unexpected copyto args", file=sys.stderr)
        sys.exit(2)
    data = pathlib.Path(sys.argv[2]).read_bytes()
    if {corrupt!r}:
        data = data[::-1]
    remote_zip.write_bytes(data)
elif command == "lsl":
    if len(sys.argv) != 3 or sys.argv[2] != target:
        print("unexpected lsl args", file=sys.stderr)
        sys.exit(2)
    if not remote_zip.exists():
        print("remote missing", file=sys.stderr)
        sys.exit(3)
    print(f"{{remote_zip.stat().st_size + size_delta}} 2026-07-08 00:00:00.000000000 wiki-export.zip")
elif command == "md5sum":
    if len(sys.argv) != 3 or sys.argv[2] != target:
        print("unexpected md5sum args", file=sys.stderr)
        sys.exit(2)
    if not remote_zip.exists():
        print("remote missing", file=sys.stderr)
        sys.exit(3)
    print(f"{{hashlib.md5(remote_zip.read_bytes()).hexdigest()}}  wiki-export.zip")
else:
    print("unexpected command", file=sys.stderr)
    sys.exit(2)
""", encoding="utf-8")
    path.chmod(0o755)
    return path


with tempfile.TemporaryDirectory(prefix="wiki-export-eval-") as td:
    root = Path(td)
    required_files = [
        ".gitignore",
        "AGENTS.md",
        "CLAUDE.md",
        "CONTEXT.md",
        "LICENSE",
        "README.md",
        "REFERENCES.md",
    ]
    for rel in required_files:
        write(root / rel)
    for rel in [
        ".claude/commands/wiki-ingest.md",
        ".agents/skills/wiki-ingest/SKILL.md",
        ".github/workflows/wiki-ci.yml",
        "raw/README.md",
        "raw/.gitkeep",
        "raw/customer-research/source.txt",
        "raw/customer-research/source.zip",
        "raw/customer-research/wiki-export-2026-06-24.zip",
        "scripts/lint.py",
        "wiki/index.md",
        "workflows/maintenance/export.md",
    ]:
        write(root / rel)
    for rel in [
        ".env",
        ".agents/local-state.json",
        ".claude/settings.local.json",
        ".claude/worktrees/private.txt",
        ".git/config",
        "deliverables/output/file.txt",
        "tmp/scratch.txt",
        "tmp/wiki-export-2026-06-24.zip",
        "wiki/.DS_Store",
    ]:
        write(root / rel)

    dry = subprocess.run(
        [sys.executable, str(EXPORT), "--repo-root", str(root), "--dry-run", "--date", "2026-06-24"],
        text=True,
        capture_output=True,
        check=False,
    )
    results.record(
        "dry-run-verifies-template-coverage",
        dry.returncode == 0 and "Required export coverage: yes" in dry.stdout,
        dry.stdout.replace("\n", " | ") + dry.stderr.replace("\n", " | "),
    )

    build = subprocess.run(
        [sys.executable, str(EXPORT), "--repo-root", str(root), "--date", "2026-06-24"],
        text=True,
        capture_output=True,
        check=False,
    )
    zip_path = root / "tmp" / "wiki-export-2026-06-24.zip"
    names: set[str] = set()
    if zip_path.exists():
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
    required_present = all(rel in names for rel in required_files)
    prefixes_present = all(
        any(name.startswith(prefix) for name in names)
        for prefix in (
            ".claude/commands/",
            ".agents/skills/",
            ".github/workflows/",
            "raw/",
            "scripts/",
            "wiki/",
            "workflows/",
        )
    )
    excluded_absent = all(
        rel not in names
        for rel in (
            ".env",
            ".agents/local-state.json",
            ".claude/settings.local.json",
            ".claude/worktrees/private.txt",
            ".git/config",
            "deliverables/output/file.txt",
            "tmp/scratch.txt",
            "tmp/wiki-export-2026-06-24.zip",
            "wiki/.DS_Store",
        )
    )
    legitimate_zip_sources_present = all(
        rel in names
        for rel in (
            "raw/customer-research/source.zip",
            "raw/customer-research/wiki-export-2026-06-24.zip",
        )
    )
    results.record(
        "build-includes-required-and-excludes-local",
        build.returncode == 0
        and required_present
        and prefixes_present
        and excluded_absent
        and legitimate_zip_sources_present,
        "stdout: " + build.stdout.replace("\n", " | ") + " names: " + repr(sorted(names)),
    )
    if zip_path.exists():
        count_ok, count_errors = export_wiki.verify_zip(zip_path, len(names) + 1)
        results.record(
            "verify-rejects-count-mismatch",
            not count_ok and any("did not match expected" in e for e in count_errors),
            f"verify_zip should fail on count mismatch; ok={count_ok} errors={count_errors}",
        )
        with zipfile.ZipFile(zip_path, "a") as zf:
            zf.writestr("tmp/wiki-export-2026-06-24.zip", "nested export")
        nested_ok, nested_errors = export_wiki.verify_zip(
            zip_path,
            len(names) + 1,
            "tmp/wiki-export-2026-06-24.zip",
        )
        results.record(
            "verify-rejects-nested-export-path",
            not nested_ok and any("archive unexpectedly contains itself" in e for e in nested_errors),
            f"verify_zip should reject nested export paths; ok={nested_ok} errors={nested_errors}",
        )
    else:
        results.record("verify-rejects-count-mismatch", False, "export zip was not created")
        results.record("verify-rejects-nested-export-path", False, "export zip was not created")

with tempfile.TemporaryDirectory(prefix="wiki-export-date-eval-") as td:
    root = Path(td)
    proc = subprocess.run(
        [
            sys.executable,
            str(EXPORT),
            "--repo-root",
            str(root),
            "--output-dir",
            "generated",
            "--date",
            "x/../../../outside",
            "--dry-run",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    results.record(
        "export-rejects-path-shaped-date-before-writing",
        proc.returncode == 2
        and "not a valid YYYY-MM-DD date" in proc.stderr
        and not (root / "generated").exists(),
        f"exit={proc.returncode}; stdout={proc.stdout!r}; stderr={proc.stderr!r}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-export-symlink-eval-") as td:
    root = Path(td)
    outside = root.parent / f"{root.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "escape-link").symlink_to(outside)
    proc = subprocess.run(
        [sys.executable, str(EXPORT), "--repo-root", str(root), "--dry-run"],
        text=True,
        capture_output=True,
        check=False,
    )
    results.record(
        "export-rejects-symlink-tree",
        proc.returncode == 1 and "contains symlink" in proc.stderr,
        f"exit={proc.returncode}; stderr={proc.stderr!r}",
    )
    outside.unlink()

with tempfile.TemporaryDirectory(prefix="wiki-export-upload-eval-") as td:
    root = Path(td)
    out = root / "wiki-export.zip"
    out.write_bytes(b"backup")
    rclone = fake_rclone(root, configured=True)
    ok, errors = export_wiki.upload_rclone(
        out, "gdrive:wiki-exports/wiki-export.zip", str(rclone)
    )
    remote = root / "remote.zip"
    results.record(
        "upload-rclone-copyto-and-size-verifies",
        ok and remote.read_bytes() == b"backup",
        f"upload should copy and verify exact byte size; ok={ok} errors={errors}",
    )
    results.record(
        "upload-rclone-skips-config-when-remote-exists",
        not (root / "config-calls.txt").exists(),
        "an existing rclone remote should not be reconfigured",
    )

with tempfile.TemporaryDirectory(prefix="wiki-export-upload-first-run-eval-") as td:
    root = Path(td)
    out = root / "wiki-export.zip"
    out.write_bytes(b"backup")
    rclone = fake_rclone(root, configured=False)
    ok, errors = export_wiki.upload_rclone(
        out,
        "gdrive:wiki-exports/wiki-export.zip",
        str(rclone),
        init_drive_remote="gdrive",
    )
    results.record(
        "upload-rclone-inits-missing-drive-remote",
        ok and (root / "config-calls.txt").read_text(encoding="utf-8") == "x",
        f"missing Drive remote should trigger one config create; ok={ok} errors={errors}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-export-upload-streaming-eval-") as td:
    root = Path(td)
    out = root / "wiki-export.zip"
    out.write_bytes(b"backup")
    rclone = fake_rclone(root, configured=True)
    try:
        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
            ok, errors = export_wiki.upload_rclone(
                out, "gdrive:wiki-exports/wiki-export.zip", str(rclone)
            )
        streamed = ok
    except AssertionError:
        streamed = False
        errors = ["upload read the whole local archive"]
    results.record(
        "upload-rclone-streams-local-hash",
        streamed,
        f"local hashing must not call Path.read_bytes; errors={errors}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-export-upload-mismatch-eval-") as td:
    root = Path(td)
    out = root / "wiki-export.zip"
    out.write_bytes(b"backup")
    rclone = fake_rclone(root, size_delta=1, configured=True)
    ok, errors = export_wiki.upload_rclone(
        out, "gdrive:wiki-exports/wiki-export.zip", str(rclone)
    )
    results.record(
        "upload-rclone-rejects-size-mismatch",
        not ok and any("did not match local size" in e for e in errors),
        f"upload must fail on remote/local size mismatch; ok={ok} errors={errors}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-export-upload-missing-eval-") as td:
    root = Path(td)
    out = root / "wiki-export.zip"
    out.write_bytes(b"backup")
    ok, errors = export_wiki.upload_rclone(
        out, "gdrive:wiki-exports/wiki-export.zip", str(root / "missing-rclone")
    )
    results.record(
        "upload-rclone-requires-rclone",
        not ok and any("not found" in e for e in errors),
        f"missing rclone must fail loudly; ok={ok} errors={errors}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-export-upload-corrupt-eval-") as td:
    root = Path(td)
    out = root / "wiki-export.zip"
    out.write_bytes(b"backup")
    rclone = fake_rclone(root, configured=True, corrupt=True)
    ok, errors = export_wiki.upload_rclone(
        out, "gdrive:wiki-exports/wiki-export.zip", str(rclone)
    )
    results.record(
        "upload-rclone-rejects-same-size-content-mismatch",
        not ok and any("did not match local md5" in error for error in errors),
        f"same-size wrong content must fail checksum verification; ok={ok} errors={errors}",
    )

with tempfile.TemporaryDirectory(prefix="wiki-export-upload-invalid-eval-") as td:
    root = Path(td)
    out = root / "wiki-export.zip"
    out.write_bytes(b"backup")
    rclone = fake_rclone(root, configured=True)
    ok, errors = export_wiki.upload_rclone(
        out,
        "other:wiki-exports/wiki-export.zip",
        str(rclone),
        init_drive_remote="gdrive",
    )
    results.record(
        "upload-rclone-rejects-init-target-mismatch",
        not ok and any("does not match" in e for e in errors),
        f"init remote must match upload target remote; ok={ok} errors={errors}",
    )

proc = subprocess.run(
    [
        sys.executable,
        str(EXPORT),
        "--dry-run",
        "--init-rclone-drive",
        "gdrive",
    ],
    text=True,
    capture_output=True,
    check=False,
)
results.record(
    "upload-init-requires-target",
    proc.returncode == 1 and "--init-rclone-drive requires --upload-target" in proc.stderr,
    f"exit {proc.returncode}; stdout: {proc.stdout!r}; stderr: {proc.stderr!r}",
)

with tempfile.TemporaryDirectory(prefix="wiki-export-transaction-eval-") as td:
    root = Path(td)
    for rel in export_wiki.REQUIRED_FILES:
        write(root / rel)
    for prefix in export_wiki.REQUIRED_PREFIXES:
        write(root / f"{prefix}fixture.txt")
    target = root / "wiki/fixture.txt"
    preimage = target.read_bytes()
    try:
        run_transaction(
            root,
            consumer="rebuild-referenced-by",
            outputs={"wiki/fixture.txt": b"new"},
            expected_preimages={"wiki/fixture.txt": preimage},
            allowed_prefixes=("wiki",),
            fault=lambda event: (_ for _ in ()).throw(RuntimeError("stop"))
            if event == "after_journal:PREPARED" else None,
        )
    except RuntimeError:
        pass
    proc = subprocess.run(
        [
            sys.executable,
            str(EXPORT),
            "--repo-root",
            str(root),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    results.record(
        "export-blocks-nonclean-transaction-before-archive-creation",
        proc.returncode == 1
        and ".wiki-transactions/ is nonclean" in proc.stderr
        and not list(root.rglob("*.zip")),
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}",
    )


def rewrite_archive(source: Path, target: Path, mutation: str) -> None:
    with zipfile.ZipFile(source) as original:
        entries = [(info, original.read(info.filename)) for info in original.infolist()]
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as rewritten:
        for info, content in entries:
            if mutation == "missing" and info.filename == "README.md":
                continue
            if mutation == "changed" and info.filename == "README.md":
                content += b"changed"
            if mutation == "duplicate-manifest-key" and info.filename == export_wiki.BACKUP_MANIFEST_NAME:
                content = b'{"schema_version":1,' + content[1:]
            rewritten.writestr(info, content)
        if mutation == "extra":
            rewritten.writestr("unexpected.txt", b"extra")
        elif mutation == "duplicate":
            rewritten.writestr("README.md", b"duplicate")
        elif mutation == "traversal":
            rewritten.writestr("../escape.txt", b"escape")
        elif mutation == "absolute":
            rewritten.writestr("/escape.txt", b"escape")
        elif mutation == "windows-absolute":
            rewritten.writestr("C:/escape.txt", b"escape")
        elif mutation == "case-collision":
            rewritten.writestr("agents.md", b"collision")
        elif mutation == "symlink":
            link = zipfile.ZipInfo("unsafe-link")
            link.external_attr = 0o120777 << 16
            rewritten.writestr(link, b"README.md")
        elif mutation == "special":
            special = zipfile.ZipInfo("unsafe-fifo")
            special.external_attr = 0o010666 << 16
            rewritten.writestr(special, b"")


with tempfile.TemporaryDirectory(prefix="wiki-restore-eval-") as td:
    root = Path(td)
    archive = root / "backup.zip"
    files = export_wiki.export_files(REPO_ROOT)
    export_wiki.build_zip(REPO_ROOT, archive, files)
    manifest, archive_errors = export_wiki.verify_backup_archive(archive)
    results.record(
        "backup-manifest-exactly-matches-member-set-and-hashes",
        manifest is not None
        and not archive_errors
        and export_wiki.BACKUP_MANIFEST_NAME not in {
            member["path"] for member in manifest["members"]
        }
        and manifest["raw_artifact_manifest_sha256"]
        == hashlib.sha256((REPO_ROOT / "scripts/raw-artifacts.json").read_bytes()).hexdigest(),
        repr(archive_errors),
    )

    mutation_results = {}
    for mutation in (
        "changed", "missing", "extra", "duplicate", "traversal", "absolute",
        "windows-absolute", "case-collision", "symlink", "special",
        "duplicate-manifest-key",
    ):
        mutated = root / f"{mutation}.zip"
        rewrite_archive(archive, mutated, mutation)
        checked, errors = export_wiki.verify_backup_archive(mutated)
        mutation_results[mutation] = checked is None and bool(errors)
    results.record(
        "backup-verifier-rejects-changed-missing-extra-duplicate-and-unsafe-members",
        all(mutation_results.values()),
        repr(mutation_results),
    )

    destination = root / "restored"
    commands: list[list[str]] = []
    real_run = subprocess.run

    def offline_run(command, *args, **kwargs):
        commands.append([str(part) for part in command])
        return real_run(command, *args, **kwargs)

    with patch.object(restore_wiki.subprocess, "run", side_effect=offline_run):
        restore_wiki.restore_backup_archive(archive, destination)
    exact_pairs = (
        "scripts/raw-artifacts.json",
        "wiki/domain.md",
        "wiki/sources/.gitkeep",
    )
    results.record(
        "valid-restore-is-member-exact-and-passes-deterministic-checks",
        all((destination / path).read_bytes() == (REPO_ROOT / path).read_bytes() for path in exact_pairs)
        and not (destination / ".git").exists()
        and all("git" not in Path(command[0]).name and "rclone" not in Path(command[0]).name for command in commands),
        repr(commands),
    )
    try:
        restore_wiki.restore_backup_archive(archive, destination)
    except restore_wiki.RestoreError as exc:
        existing_rejected = "must be absent" in str(exc)
    else:
        existing_rejected = False
    results.record("restore-refuses-existing-destination", existing_rejected)

    failed_destination = root / "failed-restore"
    try:
        restore_wiki.restore_backup_archive(root / "changed.zip", failed_destination)
    except restore_wiki.RestoreError:
        failed_cleanly = not failed_destination.exists()
    else:
        failed_cleanly = False
    results.record("failed-restore-leaves-no-partial-destination", failed_cleanly)

    raced_destination = root / "raced-restore"

    def create_competing_destination(_staged, _manifest):
        raced_destination.mkdir()
        (raced_destination / "owner.txt").write_text("third party", encoding="utf-8")
        return []

    try:
        with patch.object(
            restore_wiki,
            "verify_restored_wiki_tree",
            side_effect=create_competing_destination,
        ):
            restore_wiki.restore_backup_archive(archive, raced_destination)
    except restore_wiki.RestoreError:
        race_preserved = (
            (raced_destination / "owner.txt").read_text(encoding="utf-8") == "third party"
        )
    else:
        race_preserved = False
    results.record("restore-never-overwrites-concurrent-destination", race_preserved)

    configured_source = root / "configured-source"
    shutil.copytree(destination, configured_source)
    for folder in (configured_source / "wiki").iterdir():
        if folder.is_dir() and folder.name not in {"concepts", "sources"}:
            shutil.rmtree(folder)
    for folder_name in ("concepts", "sources"):
        folder = configured_source / "wiki" / folder_name
        for entry in folder.iterdir():
            entry.unlink()
    raw_root = configured_source / "raw"
    for entry in raw_root.iterdir():
        if entry.name != "README.md":
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    raw_bytes = b"configured restore evidence\n"
    raw_path = raw_root / "internal-memos/closure.txt"
    raw_path.parent.mkdir()
    raw_path.write_bytes(raw_bytes)
    raw_registry = {
        "description": "Configured restore fixture raw buckets.",
        "policy": "Fixture raw artifacts are immutable.",
        "buckets": {"internal-memos": "Restore evidence"},
    }
    (configured_source / "scripts/raw-buckets.json").write_text(
        json.dumps(raw_registry, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    domain = """---
title: Domain Config
type: domain
created: 2026-08-22
updated: 2026-08-22
status: configured
org: Restore Fixture
domain: exact configured restore validation
entity_types_active:
  - concept
  - source
raw_buckets:
  - internal-memos
example_queries:
  - What evidence supports the closure?
---

# Domain Config

Configured restore fixture.
"""
    (configured_source / "wiki/domain.md").write_text(domain, encoding="utf-8")
    source_page = """---
title: Closure Source
type: source
created: 2026-08-22
updated: 2026-08-22
sources: [raw/internal-memos/closure.txt]
source_type: other
tags: [restore]
confidence: high
---

# Closure Source

Exact configured restore evidence.

## Open questions / gaps

- None.

## Related pages

- Supports: [[closure-concept]]
"""
    concept_page = """---
title: Closure Concept
type: concept
created: 2026-08-22
updated: 2026-08-22
sources: [closure-source]
tags: [restore]
confidence: high
agent_use_cases:
  - verifying configured restore closure
---

# Closure Concept

The configured restore retains exact evidence. (source: [[closure-source]])

## Open questions / gaps

- None.

## Related pages

- Derived from: [[closure-source]]
"""
    (configured_source / "wiki/sources/closure-source.md").write_text(source_page, encoding="utf-8")
    (configured_source / "wiki/concepts/closure-concept.md").write_text(concept_page, encoding="utf-8")
    with (configured_source / "wiki/index.md").open("a", encoding="utf-8") as index:
        index.write(
            "\n| [Closure Source](sources/closure-source.md) | Restore evidence |\n"
            "| [Closure Concept](concepts/closure-concept.md) | Restore claim |\n"
        )
    raw_manifest = {
        "schema_version": 1,
        "artifacts": [{
            "source_slug": "closure-source",
            "captured_at": "2026-08-22",
            "files": [{
                "path": "raw/internal-memos/closure.txt",
                "size": len(raw_bytes),
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            }],
        }],
    }
    (configured_source / "scripts/raw-artifacts.json").write_bytes(
        json.dumps(raw_manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    configured_archive = root / "configured-backup.zip"
    export_wiki.build_zip(
        configured_source,
        configured_archive,
        export_wiki.export_files(configured_source),
    )
    configured_destination = root / "configured-restored"
    restore_wiki.restore_backup_archive(configured_archive, configured_destination)
    closure = resolve_restored_source_closure(configured_destination, "closure-source")
    results.record(
        "configured-restore-preserves-raw-source-citation-closure",
        closure.source_path == "wiki/sources/closure-source.md"
        and closure.files[0].path == "raw/internal-memos/closure.txt"
        and (configured_destination / closure.files[0].path).read_bytes() == raw_bytes
        and "(source: [[closure-source]])" in (
            configured_destination / "wiki/concepts/closure-concept.md"
        ).read_text(encoding="utf-8"),
    )
    broken_schema_source = root / "broken-schema-source"
    shutil.copytree(configured_source, broken_schema_source)
    agents_path = broken_schema_source / "AGENTS.md"
    agents_path.write_text(
        agents_path.read_text(encoding="utf-8").replace(
            "analyses, competitors", "analyses, bogus", 1
        ),
        encoding="utf-8",
    )
    broken_schema_archive = root / "broken-schema.zip"
    export_wiki.build_zip(
        broken_schema_source,
        broken_schema_archive,
        export_wiki.export_files(broken_schema_source),
    )
    broken_schema_destination = root / "broken-schema-restored"
    try:
        restore_wiki.restore_backup_archive(
            broken_schema_archive, broken_schema_destination
        )
    except restore_wiki.RestoreError as exc:
        broken_schema_rejected = (
            "schema parity" in str(exc) and not broken_schema_destination.exists()
        )
    else:
        broken_schema_rejected = False
    results.record(
        "restore-validates-schema-parity-against-staged-tree",
        broken_schema_rejected,
    )

sys.exit(results.finish())
