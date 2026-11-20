"""Descriptor-relative file access and atomic local file promotion."""

import ctypes
import errno
import fcntl
import os
import shutil
import stat
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from .manifest import CaptureError, safe_text

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_RENAME_NOREPLACE = 1
_CHUNK = 1024 * 1024


def absolute(path):
    path = Path(path).absolute()
    if path.anchor != "/" or ".." in path.parts:
        raise CaptureError("UNSAFE_ROOT")
    return path


def parts(path):
    split = path.split("/")
    if any(
        part in ("", ".", "..") or "\\" in part or ":" in part or not safe_text(part)
        for part in split
    ):
        raise CaptureError("UNSAFE_INPUT_PATH")
    return split


@contextmanager
def directory(base, components, *, outside_git=False):
    fd = os.dup(base)
    try:
        for component in components:
            next_fd = os.open(component, _DIR, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            if outside_git and present(fd, ".git"):
                raise CaptureError("OUTPUT_INSIDE_GIT")
        yield fd
    finally:
        os.close(fd)


@contextmanager
def root(path, *, private=False):
    system = os.open("/", _DIR)
    try:
        with directory(system, path.parts[1:], outside_git=private) as fd:
            info = os.fstat(fd)
            if private and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
                raise CaptureError("OUTPUT_ROOT_NOT_PRIVATE")
            yield fd
    finally:
        os.close(system)


def present(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


@contextmanager
def regular(parent, name):
    fd = os.open(name, _READ, dir_fd=parent)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise CaptureError("NOT_REGULAR_FILE")
        yield handle


def read_input(parent, relative, *, limit):
    components = parts(relative)
    try:
        with directory(parent, components[:-1]) as container:
            with regular(container, components[-1]) as handle:
                return handle.read(limit + 1)
    except OSError:
        raise CaptureError("INPUT_PATH_UNAVAILABLE_OR_UNSAFE") from None


@contextmanager
def lock(parent, name):
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(name, flags, 0o600, dir_fd=parent)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CaptureError("UNSAFE_LOCK_FILE")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def promote(parent, temporary, final):
    # Same parent descriptor fixes the filesystem. Linux renameat2 also
    # guarantees that even a non-cooperating writer cannot be clobbered.
    try:
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise CaptureError("ATOMIC_RENAME_UNAVAILABLE") from None
    rename.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    if rename(
        parent, os.fsencode(temporary), parent, os.fsencode(final), _RENAME_NOREPLACE
    ):
        error = ctypes.get_errno()
        if error in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.EXDEV):
            raise CaptureError("ATOMIC_RENAME_UNAVAILABLE")
        raise OSError(error, os.strerror(error))
    os.fsync(parent)


def fingerprint(parent, name):
    hasher = sha256()
    size = 0
    with regular(parent, name) as handle:
        if os.fstat(handle.fileno()).st_mode & 0o222:
            raise CaptureError("RETAINED_FILE_WRITABLE")
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest(), size


def write_file(parent, name, chunks):
    fd = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
    )
    hasher = sha256()
    size = 0
    with os.fdopen(fd, "wb") as handle:
        for chunk in chunks:
            handle.write(chunk)
            hasher.update(chunk)
            size += len(chunk)
        handle.flush()
        os.fchmod(fd, 0o400)
        os.fsync(fd)
    return hasher.hexdigest(), size


def retain(parent, name, content, expected):
    temporary = f".{name}.partial"
    # The caller holds the corresponding store lock.
    if present(parent, temporary):
        os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)
    if present(parent, name):
        if fingerprint(parent, name) != expected:
            raise CaptureError("RETAINED_FILE_MISMATCH")
        return
    try:
        write_file(parent, temporary, (content,))
        if fingerprint(parent, temporary) != expected:
            raise CaptureError("RETAINED_FILE_MISMATCH")
        promote(parent, temporary, name)
    finally:
        if present(parent, temporary):
            os.unlink(temporary, dir_fd=parent)


def remove_stage_temporary(parent, name):
    if present(parent, name):
        if not shutil.rmtree.avoids_symlink_attacks:
            raise CaptureError("SAFE_DIRECTORY_REMOVAL_UNAVAILABLE")
        shutil.rmtree(name, dir_fd=parent)
        os.fsync(parent)
