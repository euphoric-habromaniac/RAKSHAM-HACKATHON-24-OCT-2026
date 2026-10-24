"""Single-writer lock so two GPU jobs cannot run at once on the shared laptop.

The lock is a file holding the owner's pid, created atomically. A lock whose
pid is no longer running is treated as stale and replaced.

    with gpu_lock():           # data/.gpu_lock
        ...train or score...
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK = ROOT / "data" / ".gpu_lock"


class LockHeld(RuntimeError):
    """Another live process owns the GPU lock."""


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0) would TERMINATE the process on Windows
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_owner(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def acquire(path: Path = DEFAULT_LOCK) -> None:
    """Create the lock file or raise LockHeld. Replaces a stale lock once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = read_owner(path)
            if owner is not None and pid_alive(owner):
                raise LockHeld(f"GPU lock {path} is held by running pid {owner}; wait for it to finish")
            print(f"removing stale GPU lock {path} (pid {owner} is not running)")
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return
    raise LockHeld(f"could not acquire GPU lock {path}")


def release(path: Path = DEFAULT_LOCK) -> None:
    if read_owner(path) == os.getpid():
        path.unlink(missing_ok=True)


@contextlib.contextmanager
def gpu_lock(path: Path = DEFAULT_LOCK):
    acquire(path)
    try:
        yield
    finally:
        release(path)
