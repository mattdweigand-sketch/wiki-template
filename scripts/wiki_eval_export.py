#!/usr/bin/env python3
"""Regression eval for export_wiki.py template include/exclude boundaries."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import export_wiki
from _file_transactions import run_transaction
from eval_lib import Results


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
        "SETUP.md",
    ]
    for rel in required_files:
        write(root / rel)
    for rel in [
        ".claude/commands/wiki-ingest.md",
        ".codex/skills/wiki-ingest/SKILL.md",
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
            ".codex/skills/",
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

sys.exit(results.finish())
