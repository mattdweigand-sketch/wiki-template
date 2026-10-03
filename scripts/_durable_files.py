#!/usr/bin/env python3
"""POSIX durable file operations anchored to opened directory objects.

Path wrappers remain available. A directory_scope keeps the same directory
handles across a multi-file operation; callers never reopen a substituted path.
Locks serialize only writers that participate in the same lock domain.
"""

from __future__ import annotations

import contextlib
import contextvars
import fcntl
import hashlib
import os
import secrets
import stat
from pathlib import Path
from typing import Callable, Iterator


class DurableFileError(OSError):
    """A filesystem entry or durable step violated the supported contract."""


FaultHook = Callable[[str], None]
_UNSET = object()
_SCOPES: contextvars.ContextVar[tuple['_DirectoryHandles', ...]] = contextvars.ContextVar(
    'durable_directory_scopes', default=()
)


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _open_flags(base: int) -> int:
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
        raise DurableFileError('descriptor-relative no-follow filesystem operations are unavailable')
    return base | getattr(os, 'O_CLOEXEC', 0) | os.O_NOFOLLOW


def _require_capabilities() -> None:
    required = (os.open, os.stat, os.unlink, os.mkdir, os.rmdir, os.rename)
    if (
        os.name != 'posix'
        or not hasattr(os, 'O_NOFOLLOW')
        or not hasattr(os, 'O_DIRECTORY')
        or any(operation not in os.supports_dir_fd for operation in required)
        or os.stat not in os.supports_follow_symlinks
        or os.listdir not in os.supports_fd
    ):
        raise DurableFileError('required descriptor-relative filesystem operations are unavailable')


class _DirectoryHandles:
    """One selected root plus lazily opened, identity-checked descendants."""

    def __init__(self, root: Path) -> None:
        _require_capabilities()
        self.root = Path(os.path.abspath(root))
        self.alias = self.root.resolve()
        self.handles: dict[tuple[str, ...], int] = {}
        before = self.root.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise DurableFileError(f'parent is a symlink: {root}')
        if not stat.S_ISDIR(before.st_mode):
            raise DurableFileError(f'directory root is not a real directory: {root}')
        fd = os.open(self.root, _open_flags(os.O_RDONLY | os.O_DIRECTORY))
        if _identity(os.fstat(fd)) != _identity(before):
            os.close(fd)
            raise DurableFileError(f'directory root changed while opening: {root}')
        self.handles[()] = fd

    def relative(self, path: Path) -> tuple[str, ...] | None:
        absolute = Path(os.path.abspath(path))
        for root in (self.root, self.alias):
            try:
                return absolute.relative_to(root).parts
            except ValueError:
                pass
        return None

    def close(self) -> None:
        for fd in self.handles.values():
            os.close(fd)
        self.handles.clear()

    def check(self, parts: tuple[str, ...]) -> None:
        try:
            current = self.root.lstat()
            if not stat.S_ISDIR(current.st_mode) or _identity(current) != _identity(os.fstat(self.handles[()])):
                raise DurableFileError(f'directory namespace changed: {self.root}')
            for index, component in enumerate(parts):
                parent = parts[:index]
                child = parts[:index + 1]
                current = os.stat(component, dir_fd=self.handles[parent], follow_symlinks=False)
                if not stat.S_ISDIR(current.st_mode) or _identity(current) != _identity(os.fstat(self.handles[child])):
                    raise DurableFileError(f'directory namespace changed: {self.root.joinpath(*child)}')
        except OSError as exc:
            if isinstance(exc, DurableFileError):
                raise
            raise DurableFileError(f'cannot verify directory namespace: {self.root.joinpath(*parts)}: {exc}') from exc

    def directory(self, path: Path) -> int:
        parts = self.relative(path)
        if parts is None:
            raise DurableFileError(f'path is outside opened root: {path}')
        self.check(())
        for index, component in enumerate(parts):
            parent = parts[:index]
            child = parts[:index + 1]
            if child not in self.handles:
                self.check(parent)
                try:
                    before = os.stat(component, dir_fd=self.handles[parent], follow_symlinks=False)
                    if not stat.S_ISDIR(before.st_mode):
                        raise DurableFileError(f'parent is a symlink or not a directory: {self.root.joinpath(*child)}')
                    fd = os.open(component, _open_flags(os.O_RDONLY | os.O_DIRECTORY), dir_fd=self.handles[parent])
                    if _identity(os.fstat(fd)) != _identity(before):
                        os.close(fd)
                        raise DurableFileError(f'directory changed while opening: {self.root.joinpath(*child)}')
                    self.handles[child] = fd
                except OSError as exc:
                    if isinstance(exc, DurableFileError):
                        raise
                    raise DurableFileError(f'cannot open directory {self.root.joinpath(*child)}: {exc}') from exc
            self.check(child)
        return self.handles[parts]

    def moved(self, source: Path, destination: Path) -> None:
        old = self.relative(source)
        new = self.relative(destination)
        assert old is not None and new is not None
        affected = {key: fd for key, fd in self.handles.items() if key[:len(old)] == old}
        for key in affected:
            del self.handles[key]
        for key, fd in affected.items():
            replacement = new + key[len(old):]
            previous = self.handles.pop(replacement, None)
            if previous is not None:
                os.close(previous)
            self.handles[replacement] = fd

    def removed(self, path: Path) -> None:
        parts = self.relative(path)
        assert parts is not None
        for key in list(self.handles):
            if key[:len(parts)] == parts:
                os.close(self.handles.pop(key))


@contextlib.contextmanager
def directory_scope(root: Path) -> Iterator[None]:
    """Retain descendant handles across an operation; never serialize handles.

    The caller selects the trusted root. System aliases above that root are
    permitted; descendants are walked without following symlinks. A directory
    moved by another process stays the same opened object, not a global path
    confinement guarantee against arbitrary external renames.
    """
    for scope in reversed(_SCOPES.get()):
        if scope.relative(root) is not None:
            scope.directory(root)
            yield
            return
    try:
        scope = _DirectoryHandles(root)
    except OSError as exc:
        if isinstance(exc, DurableFileError):
            raise
        raise DurableFileError(f'cannot open directory scope {root}: {exc}') from exc
    token = _SCOPES.set((*_SCOPES.get(), scope))
    try:
        yield
    finally:
        _SCOPES.reset(token)
        scope.close()


@contextlib.contextmanager
def _directory(path: Path) -> Iterator[tuple[_DirectoryHandles, int]]:
    for scope in reversed(_SCOPES.get()):
        if scope.relative(path) is not None:
            yield scope, scope.directory(path)
            return
    with directory_scope(path):
        scope = _SCOPES.get()[-1]
        yield scope, scope.directory(path)


@contextlib.contextmanager
def pinned_parent(path: Path) -> Iterator[tuple[int, str]]:
    """Yield a borrowed parent descriptor and basename; callers must not close it."""
    with _directory(path.parent) as (scope, fd):
        yield fd, path.name
        scope.directory(path.parent)


def assert_directory_identity(path: Path) -> None:
    """Check that a retained directory chain still names its opened objects."""
    with _directory(path):
        pass


def anchored_lstat(path: Path) -> os.stat_result:
    for scope in reversed(_SCOPES.get()):
        if scope.relative(path) == ():
            return os.fstat(scope.directory(path))
    with pinned_parent(path) as (fd, name):
        return os.stat(name, dir_fd=fd, follow_symlinks=False)


def anchored_iterdir(path: Path) -> list[Path]:
    with _directory(path) as (scope, fd):
        names = os.listdir(fd)
        scope.directory(path)
        return [path / name for name in names]


def anchored_mkdir(path: Path, *, mode: int = 0o700) -> None:
    with pinned_parent(path) as (fd, name):
        os.mkdir(name, mode, dir_fd=fd)


def anchored_rmdir(path: Path) -> None:
    with _directory(path) as (scope, _fd):
        with pinned_parent(path) as (parent_fd, name):
            scope.directory(path)
            os.rmdir(name, dir_fd=parent_fd)
            scope.removed(path)


def anchored_replace_directory(source: Path, destination: Path) -> None:
    """Rename a validated directory within an active directory scope."""
    with _directory(source) as (scope, _fd):
        with pinned_parent(source) as (source_fd, source_name), pinned_parent(destination) as (dest_fd, dest_name):
            scope.directory(source)
            # Recovery authority renames never replace another directory.
            try:
                os.stat(dest_name, dir_fd=dest_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise DurableFileError(f'directory rename destination exists: {destination}')
            os.replace(source_name, dest_name, src_dir_fd=source_fd, dst_dir_fd=dest_fd)
            scope.moved(source, destination)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def classify_entry(path: Path) -> str:
    try:
        mode = anchored_lstat(path).st_mode
    except FileNotFoundError:
        return 'missing'
    if stat.S_ISREG(mode):
        return 'regular'
    if stat.S_ISDIR(mode):
        return 'directory'
    if stat.S_ISLNK(mode):
        return 'symlink'
    return 'special'


def require_safe_parent(path: Path) -> os.stat_result:
    with pinned_parent(path) as (fd, _name):
        return os.fstat(fd)


def _regular_at(fd: int, name: str, path: Path, *, allow_missing: bool = False) -> os.stat_result | None:
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return None
        raise DurableFileError(f'required file is missing: {path}')
    if not stat.S_ISREG(info.st_mode):
        raise DurableFileError(f'refusing non-regular or symlink authority file: {path}')
    if info.st_nlink != 1:
        raise DurableFileError(f'refusing authority file with link count {info.st_nlink}: {path}')
    return info


def require_single_link_regular(path: Path, *, allow_missing: bool = False) -> os.stat_result | None:
    with pinned_parent(path) as (fd, name):
        return _regular_at(fd, name, path, allow_missing=allow_missing)


def _read_at(parent_fd: int, name: str, path: Path, *, allow_missing: bool = False) -> tuple[bytes | None, os.stat_result | None]:
    before = _regular_at(parent_fd, name, path, allow_missing=allow_missing)
    if before is None:
        return None, None
    fd = os.open(name, _open_flags(os.O_RDONLY | os.O_NONBLOCK), dir_fd=parent_fd)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or _identity(opened) != _identity(before):
            raise DurableFileError(f'entry changed while opening: {path}')
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        current = _regular_at(parent_fd, name, path)
        if current is None or _identity(current) != _identity(opened):
            raise DurableFileError(f'entry changed while reading: {path}')
        return b''.join(chunks), opened
    finally:
        os.close(fd)


def read_regular_bytes(path: Path, *, allow_missing: bool = False) -> tuple[bytes | None, os.stat_result | None]:
    with pinned_parent(path) as (fd, name):
        return _read_at(fd, name, path, allow_missing=allow_missing)


def fsync_directory(path: Path) -> None:
    try:
        with _directory(path) as (scope, fd):
            os.fsync(fd)
            scope.directory(path)
    except OSError as exc:
        if isinstance(exc, DurableFileError):
            raise
        raise DurableFileError(f'cannot fsync directory {path}: {exc}') from exc


@contextlib.contextmanager
def stable_lock(lock_path: Path) -> Iterator[int]:
    """Exclusively lock one sidecar inode through its retained parent handle."""
    with pinned_parent(lock_path) as (parent_fd, name):
        before = _regular_at(parent_fd, name, lock_path, allow_missing=True)
        created = False
        if before is None:
            try:
                fd = os.open(name, _open_flags(os.O_RDWR | os.O_CREAT | os.O_EXCL), 0o600, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                # Another participating writer won first creation. Reopen
                # without O_CREAT: Darwin can return ENOENT when two openat
                # O_CREAT|O_NOFOLLOW calls race on the initial creation.
                fd = os.open(name, _open_flags(os.O_RDWR), dir_fd=parent_fd)
        else:
            fd = os.open(name, _open_flags(os.O_RDWR), dir_fd=parent_fd)
        try:
            opened = os.fstat(fd)
            current = _regular_at(parent_fd, name, lock_path)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or current is None
                or _identity(opened) != _identity(current)
                or (before is not None and _identity(opened) != _identity(before))
            ):
                raise DurableFileError(f'stable lock changed while opening: {lock_path}')
            os.fchmod(fd, 0o600)
            if created:
                os.fsync(fd)
                os.fsync(parent_fd)
            fcntl.flock(fd, fcntl.LOCK_EX)
            assert_directory_identity(lock_path.parent)
            current = _regular_at(parent_fd, name, lock_path)
            if current is None or _identity(opened) != _identity(current):
                raise DurableFileError(f'stable lock inode changed while waiting: {lock_path}')
            yield fd
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _write_once(fd: int, content: memoryview) -> int:
    return os.write(fd, content)


def _call_fault(fault: FaultHook | None, stage: str) -> None:
    if fault is not None:
        fault(stage)


def _recheck_at(parent_fd: int, name: str, path: Path, expected_sha256: object) -> None:
    current, _ = _read_at(parent_fd, name, path, allow_missing=True)
    if expected_sha256 is None:
        if current is not None:
            raise DurableFileError(f'target appeared after planning: {path}')
    elif current is None or sha256_bytes(current) != expected_sha256:
        raise DurableFileError(f'target changed after planning: {path}')


def atomic_replace_bytes(
    path: Path,
    content: bytes,
    *,
    mode: int = 0o600,
    expected_sha256: str | None | object = _UNSET,
    fault: FaultHook | None = None,
) -> str:
    """Durably install bytes in the opened parent, detecting namespace changes.

    ``expected_sha256=None`` requires absence. A digest requires those bytes.
    Omission snapshots and rechecks the target. This is not compare-and-swap
    against an uncooperative writer between the recheck and replacement.
    """
    if not isinstance(content, bytes):
        raise TypeError('content must be bytes')
    with pinned_parent(path) as (parent_fd, name):
        initial, _ = _read_at(parent_fd, name, path, allow_missing=True)
        if expected_sha256 is _UNSET:
            expected_sha256 = sha256_bytes(initial) if initial is not None else None
        else:
            _recheck_at(parent_fd, name, path, expected_sha256)
        temporary_name: str | None = None
        temporary_identity: tuple[int, int] | None = None
        fd = -1
        try:
            for _ in range(100):
                candidate = f'.{name}.{secrets.token_hex(8)}'
                try:
                    fd = os.open(candidate, _open_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), mode, dir_fd=parent_fd)
                except FileExistsError:
                    continue
                temporary_name = candidate
                temporary_identity = _identity(os.fstat(fd))
                break
            else:
                raise DurableFileError(f'cannot create unique temporary file: {path}')
            os.fchmod(fd, mode)
            _call_fault(fault, 'before_write')
            remaining = memoryview(content)
            while remaining:
                written = _write_once(fd, remaining)
                if written <= 0:
                    raise DurableFileError('zero-progress write')
                remaining = remaining[written:]
            _call_fault(fault, 'after_write')
            os.fsync(fd)
            _call_fault(fault, 'after_file_fsync')
            os.close(fd)
            fd = -1
            assert_directory_identity(path.parent)
            _recheck_at(parent_fd, name, path, expected_sha256)
            _call_fault(fault, 'before_replace')
            assert_directory_identity(path.parent)
            temporary_info = _regular_at(parent_fd, temporary_name, path.parent / temporary_name)
            if temporary_info is None or _identity(temporary_info) != temporary_identity:
                raise DurableFileError(f'temporary file changed before replacement: {path}')
            os.replace(temporary_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            temporary_name = None
            _call_fault(fault, 'after_replace')
            os.fsync(parent_fd)
            _call_fault(fault, 'after_dir_fsync')
            _call_fault(fault, 'before_reopen')
            assert_directory_identity(path.parent)
            installed, installed_info = _read_at(parent_fd, name, path)
            _call_fault(fault, 'after_reopen')
            if installed != content or installed_info is None or stat.S_IMODE(installed_info.st_mode) != mode:
                raise DurableFileError(f'installed-byte or mode verification failed: {path}')
            _call_fault(fault, 'after_verify')
            assert_directory_identity(path.parent)
            return sha256_bytes(content)
        except OSError as exc:
            if isinstance(exc, DurableFileError):
                raise
            raise DurableFileError(f'durable replacement failed for {path}: {exc}') from exc
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary_name is not None:
                try:
                    info = os.stat(temporary_name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and _identity(info) == temporary_identity:
                        os.unlink(temporary_name, dir_fd=parent_fd)
                        os.fsync(parent_fd)


def durable_unlink(path: Path, *, expected_sha256: str) -> None:
    """Remove exact bytes through the same parent used to validate them."""
    with pinned_parent(path) as (parent_fd, name):
        current, _ = _read_at(parent_fd, name, path)
        if current is None or sha256_bytes(current) != expected_sha256:
            raise DurableFileError(f'target changed before durable unlink: {path}')
        assert_directory_identity(path.parent)
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)


__all__ = [
    'DurableFileError', 'FaultHook', 'anchored_iterdir', 'anchored_lstat',
    'anchored_mkdir', 'anchored_replace_directory', 'anchored_rmdir',
    'assert_directory_identity', 'atomic_replace_bytes', 'classify_entry',
    'directory_scope', 'durable_unlink', 'fsync_directory', 'pinned_parent',
    'read_regular_bytes', 'require_safe_parent', 'require_single_link_regular',
    'sha256_bytes', 'stable_lock',
]
