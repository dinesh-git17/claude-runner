"""Flock-based session concurrency guard."""

from __future__ import annotations

import fcntl
import os

from orchestrator.config import LOCK_FILE


class SessionAlreadyRunning(RuntimeError):
    """Raised when another session holds the lock."""


def acquire_lock() -> int:
    """Acquire exclusive session lock via flock.

    Returns:
        File descriptor for the lock (caller must pass to release_lock).

    Raises:
        SessionAlreadyRunning: If the lock is already held.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        msg = f"session lock held: {LOCK_FILE}"
        raise SessionAlreadyRunning(msg) from None
    # Write PID for debugging
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def release_lock(fd: int) -> None:
    """Release the session lock."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
