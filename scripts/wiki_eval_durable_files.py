#!/usr/bin/env python3
"""Adversarial evals for durable single-file replacement and stable locks."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import _durable_files as durable
from eval_lib import Results


REPO_ROOT = Path(__file__).resolve().parents[1]
results = Results()


with tempfile.TemporaryDirectory(prefix="wiki-durable-eval-") as td:
    root = Path(td)
    target = root / "target"
    target.write_bytes(b"old")
    digest = durable.atomic_replace_bytes(target, b"new")
    results.record("complete-replacement-passes", target.read_bytes() == b"new" and digest == durable.sha256_bytes(b"new"), "replacement mismatch")

    original_write = durable._write_once
    calls = 0

    def short_write(fd, content):
        nonlocal_calls[0] += 1
        return original_write(fd, content[:1])

    nonlocal_calls = [0]
    durable._write_once = short_write
    try:
        durable.atomic_replace_bytes(target, b"abcdef")
        ok = target.read_bytes() == b"abcdef" and nonlocal_calls[0] >= 6
    finally:
        durable._write_once = original_write
    results.record("short-writes-loop-to-completion", ok, f"calls={nonlocal_calls[0]}")

    durable._write_once = lambda _fd, _content: 0
    before = target.read_bytes()
    try:
        durable.atomic_replace_bytes(target, b"zero")
    except durable.DurableFileError as exc:
        ok = "zero-progress" in str(exc) and target.read_bytes() == before
        detail = str(exc)
    else:
        ok = False
        detail = "zero-progress write passed"
    finally:
        durable._write_once = original_write
    results.record("zero-progress-write-fails-old-intact", ok, detail)

    stages = (
        "before_write", "after_write", "after_file_fsync", "before_replace",
        "after_replace", "after_dir_fsync", "before_reopen", "after_reopen", "after_verify",
    )
    for stage in stages:
        path = root / f"fault-{stage}"
        path.write_bytes(b"old")
        try:
            durable.atomic_replace_bytes(
                path,
                b"new",
                fault=lambda current, wanted=stage: (_ for _ in ()).throw(RuntimeError(wanted)) if current == wanted else None,
            )
        except RuntimeError:
            ok = path.read_bytes() in {b"old", b"new"}
            detail = f"bytes={path.read_bytes()!r}"
        else:
            ok = False
            detail = "fault did not fire"
        results.record(f"fault-{stage}-leaves-complete-file", ok, detail)

    changed = root / "concurrent"
    changed.write_bytes(b"planned")
    expected = durable.sha256_bytes(b"planned")
    changed.write_bytes(b"third-party")
    try:
        durable.atomic_replace_bytes(changed, b"output", expected_sha256=expected)
    except durable.DurableFileError as exc:
        ok = "changed after planning" in str(exc) and changed.read_bytes() == b"third-party"
        detail = str(exc)
    else:
        ok = False
        detail = "concurrent edit was overwritten"
    results.record("preimage-recheck-preserves-third-party-bytes", ok, detail)

    absent = root / "absent"
    durable.atomic_replace_bytes(absent, b"created", expected_sha256=None)
    results.record("missing-target-can-be-created", absent.read_bytes() == b"created", "create failed")

    for kind in ("symlink", "hardlink", "directory", "fifo", "socket"):
        victim = root / f"unsafe-{kind}"
        anchor = root / f"anchor-{kind}"
        anchor.write_bytes(b"anchor")
        sock = None
        if kind == "symlink":
            victim.symlink_to(anchor)
        elif kind == "hardlink":
            os.link(anchor, victim)
        elif kind == "directory":
            victim.mkdir()
        elif kind == "fifo":
            os.mkfifo(victim)
        else:
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(victim))
        try:
            try:
                durable.atomic_replace_bytes(victim, b"new")
            except durable.DurableFileError:
                ok = True
            else:
                ok = False
        finally:
            if sock is not None:
                sock.close()
        results.record(f"unsafe-{kind}-target-fails", ok, f"accepted {kind}")

    real_parent = root / "real-parent"
    real_parent.mkdir()
    link_parent = root / "link-parent"
    link_parent.symlink_to(real_parent, target_is_directory=True)
    try:
        durable.atomic_replace_bytes(link_parent / "file", b"x")
    except durable.DurableFileError as exc:
        ok = "parent is a symlink" in str(exc)
        detail = str(exc)
    else:
        ok = False
        detail = "symlink parent accepted"
    results.record("symlinked-parent-fails", ok, detail)

    lock = root / ".stable.lock"
    child_code = """
import sys
from pathlib import Path
from _durable_files import stable_lock
print('READY', flush=True)
with stable_lock(Path(sys.argv[1])):
    print('ACQUIRED', flush=True)
"""
    with durable.stable_lock(lock):
        inode_before = lock.stat().st_ino
        protected = root / "protected"
        protected.write_bytes(b"old")
        durable.atomic_replace_bytes(protected, b"new")
        proc = subprocess.Popen(
            [sys.executable, "-c", child_code, str(lock)],
            cwd=REPO_ROOT / "scripts", text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.stdout is not None
        ready = proc.stdout.readline().strip()
        try:
            proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            blocked = True
        else:
            blocked = False
    stdout, stderr = proc.communicate(timeout=5)
    results.record(
        "stable-lock-excludes-across-target-replacement",
        ready == "READY" and blocked and "ACQUIRED" in stdout and lock.stat().st_ino == inode_before,
        f"ready={ready!r} blocked={blocked} stdout={stdout!r} stderr={stderr!r}",
    )


# These faults replace an ancestor after its handle has been opened. The
# replacement tree must never receive a write, including missing targets.
for event, missing in (("before_replace", False), ("before_replace", True),
                       ("before_reopen", False), ("after_verify", False)):
    with tempfile.TemporaryDirectory(prefix="wiki-durable-namespace-") as td:
        root = Path(td) / "repo"
        outside = Path(td) / "outside"
        (root / "wiki/concepts").mkdir(parents=True)
        (outside / "concepts").mkdir(parents=True)
        target = root / "wiki/concepts/a.md"
        external = outside / "concepts/a.md"
        if not missing:
            target.write_bytes(b"old")
            external.write_bytes(b"unrelated")

        def substitute(current):
            if current == event:
                (root / "wiki").rename(root / "original-wiki")
                (root / "wiki").symlink_to(outside, target_is_directory=True)

        try:
            with durable.directory_scope(root):
                durable.atomic_replace_bytes(target, b"new", fault=substitute)
        except durable.DurableFileError:
            blocked = True
        else:
            blocked = False
        original_parent = root / "original-wiki/concepts"
        results.record(
            f"namespace-{event}-{'absent' if missing else 'existing'}-preserves-outside",
            blocked
            and (not external.exists() if missing else external.read_bytes() == b"unrelated")
            and not list(original_parent.glob(".a.md.*")),
        )

with tempfile.TemporaryDirectory(prefix="wiki-durable-read-namespace-") as td:
    root = Path(td)
    (root / "data/deep").mkdir(parents=True)
    (root / "outside/deep").mkdir(parents=True)
    target = root / "data/deep/a.txt"
    target.write_bytes(b"trusted")
    (root / "outside/deep/a.txt").write_bytes(b"unrelated")
    real_read = os.read
    switched = False

    def swap_during_read(fd, size):
        global switched
        content = real_read(fd, size)
        if not switched:
            switched = True
            (root / "data").rename(root / "saved-data")
            (root / "data").symlink_to(root / "outside", target_is_directory=True)
        return content

    os.read = swap_during_read
    try:
        try:
            with durable.directory_scope(root):
                durable.read_regular_bytes(target)
        except durable.DurableFileError:
            read_blocked = True
        else:
            read_blocked = False
    finally:
        os.read = real_read
    results.record("read-rejects-mid-read-ancestor-substitution", switched and read_blocked)

with tempfile.TemporaryDirectory(prefix="wiki-durable-capabilities-") as td:
    target = Path(td) / "new"
    capabilities = os.supports_dir_fd
    os.supports_dir_fd = capabilities - {os.open}
    try:
        try:
            durable.atomic_replace_bytes(target, b"new")
        except durable.DurableFileError as exc:
            rejected = "unavailable" in str(exc)
        else:
            rejected = False
    finally:
        os.supports_dir_fd = capabilities
    results.record("unsupported-dirfd-fails-before-mutation", rejected and not list(Path(td).iterdir()))

# Real first-creation contention exercises the shared sidecar inode, rather
# than starting with a precreated lock that avoids the creation race.
with tempfile.TemporaryDirectory(prefix="wiki-durable-first-lock-") as td:
    lock = Path(td) / ".first.lock"
    child_code = """
import sys
from pathlib import Path
from _durable_files import stable_lock
with stable_lock(Path(sys.argv[1])):
    print('LOCKED', flush=True)
"""
    children = [subprocess.Popen(
        [sys.executable, "-c", child_code, str(lock)],
        cwd=REPO_ROOT / "scripts", text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ) for _ in range(4)]
    outputs = [child.communicate(timeout=10) for child in children]
    results.record(
        "concurrent-first-lock-creation-succeeds",
        all(child.returncode == 0 and output[0].strip() == "LOCKED"
            for child, output in zip(children, outputs)),
        repr(outputs),
    )

with tempfile.TemporaryDirectory(prefix="wiki-durable-fifo-swap-") as td:
    child_code = """
import os, sys
from pathlib import Path
import _durable_files as durable
target = Path(sys.argv[1]) / 'target'
target.write_bytes(b'old')
original = durable._regular_at
swapped = False
def swap_after_stat(fd, name, path, **kwargs):
    global swapped
    result = original(fd, name, path, **kwargs)
    if not swapped and path == target:
        swapped = True
        os.unlink(name, dir_fd=fd)
        os.mkfifo(target)
    return result
durable._regular_at = swap_after_stat
try:
    durable.read_regular_bytes(target)
except durable.DurableFileError:
    print('REJECTED')
"""
    try:
        child = subprocess.run([sys.executable, "-c", child_code, td], cwd=REPO_ROOT / "scripts",
                               text=True, capture_output=True, timeout=5)
        rejected = child.returncode == 0 and child.stdout.strip() == "REJECTED"
        detail = child.stderr
    except subprocess.TimeoutExpired:
        rejected, detail = False, "read blocked on substituted FIFO"
    results.record("regular-file-swapped-to-fifo-does-not-block", rejected, detail)

sys.exit(results.finish())
