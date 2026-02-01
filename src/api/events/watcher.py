"""Async-friendly filesystem watcher with debouncing."""

import asyncio
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import structlog
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from api.events.types import TEMP_FILE_PATTERNS

logger = structlog.get_logger()

EVENT_PRIORITY: dict[type[FileSystemEvent], int] = {
    FileCreatedEvent: 3,
    FileDeletedEvent: 2,
    FileModifiedEvent: 1,
}


def is_temp_file(path: str) -> bool:
    """Check if path is a temporary file that should be ignored.

    Args:
        path: File path to check.

    Returns:
        True if the file is a temporary file.
    """
    name = Path(path).name
    return any(
        name.endswith(pattern) or name.startswith(pattern.lstrip("."))
        for pattern in TEMP_FILE_PATTERNS
    )


def get_event_priority(event: FileSystemEvent) -> int:
    """Get priority value for an event type.

    Higher priority events take precedence during debouncing.

    Args:
        event: Filesystem event.

    Returns:
        Priority value (higher = more important).
    """
    return EVENT_PRIORITY.get(type(event), 0)


class DebouncingHandler(FileSystemEventHandler):
    """Watchdog event handler with time-based debouncing.

    During the debounce window, tracks the highest-priority event type
    to ensure created/deleted events are not lost to subsequent modified
    or closed events.

    Attributes:
        debounce_ms: Debounce window in milliseconds.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        callback: Callable[[FileSystemEvent], Coroutine[Any, Any, None]],
        debounce_ms: int = 50,
    ) -> None:
        """Initialize debouncing handler.

        Args:
            loop: Event loop for scheduling async callbacks.
            callback: Async function to call with debounced events.
            debounce_ms: Debounce window in milliseconds.
        """
        super().__init__()
        self._loop = loop
        self._callback = callback
        self._debounce_ms = debounce_ms
        self._pending: dict[str, tuple[threading.Timer, FileSystemEvent, int]] = {}
        self._lock = threading.Lock()
        self._coalesced_count = 0

    @property
    def coalesced_events(self) -> int:
        """Number of events coalesced by debouncing."""
        return self._coalesced_count

    def _emit_event(self, path: str) -> None:
        """Emit debounced event to async callback.

        Args:
            path: Path key for the pending event.
        """
        with self._lock:
            entry = self._pending.pop(path, None)
            if entry is None:
                return
            _, event, _ = entry

        logger.debug("watcher_emit", path=path, event_type=event.event_type)
        try:
            future = asyncio.run_coroutine_threadsafe(self._callback(event), self._loop)
            future.result(timeout=5.0)
        except Exception as e:
            logger.error("watcher_callback_error", error=str(e), path=path)

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Handle filesystem event with debouncing.

        Args:
            event: Raw watchdog filesystem event.
        """
        if event.is_directory:
            return

        src_path = event.src_path
        if isinstance(src_path, str):
            path = src_path
        else:
            path = bytes(src_path).decode("utf-8", errors="replace")

        if is_temp_file(path):
            return

        event_priority = get_event_priority(event)

        if event_priority == 0:
            with self._lock:
                if path in self._pending:
                    return

        with self._lock:
            existing = self._pending.get(path)

            if existing is not None:
                timer, stored_event, stored_priority = existing
                timer.cancel()

                if event_priority > stored_priority:
                    use_event = event
                    use_priority = event_priority
                else:
                    use_event = stored_event
                    use_priority = stored_priority

                timer = threading.Timer(
                    self._debounce_ms / 1000.0,
                    self._emit_event,
                    args=(path,),
                )
                self._pending[path] = (timer, use_event, use_priority)
                timer.start()
                self._coalesced_count += 1
            else:
                timer = threading.Timer(
                    self._debounce_ms / 1000.0,
                    self._emit_event,
                    args=(path,),
                )
                self._pending[path] = (timer, event, event_priority)
                timer.start()

    def cancel_all(self) -> None:
        """Cancel all pending timers during shutdown."""
        with self._lock:
            for timer, _, _ in self._pending.values():
                timer.cancel()
            self._pending.clear()


class FilesystemWatcher:
    """High-level filesystem watcher manager.

    Wraps watchdog Observer and DebouncingHandler to provide a clean
    interface for starting and stopping filesystem monitoring.

    Attributes:
        paths: List of directories being watched.
        debounce_ms: Debounce window in milliseconds.
    """

    def __init__(
        self,
        paths: list[str],
        loop: asyncio.AbstractEventLoop,
        on_event: Callable[[FileSystemEvent], Coroutine[Any, Any, None]],
        debounce_ms: int = 50,
    ) -> None:
        """Initialize filesystem watcher.

        Args:
            paths: Directories to watch.
            loop: Event loop for async callbacks.
            on_event: Async callback for filesystem events.
            debounce_ms: Debounce window in milliseconds.
        """
        self._paths = paths
        self._debounce_ms = debounce_ms
        self._handler = DebouncingHandler(loop, on_event, debounce_ms)
        self._observer: Observer | None = None  # pyright: ignore[reportInvalidTypeForm]

    @property
    def paths(self) -> list[str]:
        """Directories being watched."""
        return self._paths.copy()

    @property
    def coalesced_events(self) -> int:
        """Number of events coalesced by debouncing."""
        return self._handler.coalesced_events

    def start(self) -> None:
        """Start the filesystem observer.

        Raises:
            ValueError: If a path does not exist or is not a directory.
        """
        for path in self._paths:
            p = Path(path)
            if not p.exists():
                raise ValueError(f"Watch path does not exist: {path}")
            if not p.is_dir():
                raise ValueError(f"Watch path is not a directory: {path}")

        observer = Observer()
        for path in self._paths:
            observer.schedule(self._handler, path, recursive=True)
            logger.info("watcher_scheduled", path=path)

        observer.start()
        self._observer = observer
        logger.info("watcher_started", paths=self._paths)

    def stop(self) -> None:
        """Stop the filesystem observer."""
        self._handler.cancel_all()

        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        logger.info("watcher_stopped")
