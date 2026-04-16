"""Event normalization pipeline for transforming raw filesystem events."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
)

from api.events.types import DomainEvent, EventType, Topic

logger = structlog.get_logger()

VALID_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def extract_slug(filename: str) -> str | None:
    """Extract slug from filename.

    Validates that the filename follows the expected pattern and extracts
    the slug portion (filename without extension).

    Args:
        filename: Name of the file (with extension).

    Returns:
        Extracted slug if valid, None otherwise.
    """
    if not filename.endswith(".md"):
        return None

    slug = filename[:-3]

    if not slug or not VALID_SLUG_PATTERN.match(slug):
        return None

    return slug


def determine_topic(path: str) -> Topic | None:
    """Determine event topic from file path.

    Args:
        path: Absolute path to the file.

    Returns:
        Topic string if path is within watched directories, None otherwise.
    """
    if "/thoughts" in path:
        return "thoughts"
    if "/dreams" in path:
        return "dreams"
    if "/mailbox" in path:
        return "mailbox"
    return None


def determine_event_type(
    raw_event: FileSystemEvent,
    topic: Topic,
) -> EventType | None:
    """Determine domain event type from raw filesystem event.

    Moved events are treated as creations since Claude Code CLI uses
    atomic writes (write to temp file, then rename to final path).

    Args:
        raw_event: Watchdog filesystem event.
        topic: Determined topic for the event.

    Returns:
        Domain event type if mappable, None otherwise.
    """
    type_map: dict[tuple[type[FileSystemEvent], Topic], EventType] = {
        (FileCreatedEvent, "thoughts"): EventType.THOUGHT_CREATED,
        (FileModifiedEvent, "thoughts"): EventType.THOUGHT_MODIFIED,
        (FileDeletedEvent, "thoughts"): EventType.THOUGHT_DELETED,
        (FileMovedEvent, "thoughts"): EventType.THOUGHT_CREATED,
        (FileCreatedEvent, "dreams"): EventType.DREAM_CREATED,
        (FileModifiedEvent, "dreams"): EventType.DREAM_MODIFIED,
        (FileDeletedEvent, "dreams"): EventType.DREAM_DELETED,
        (FileMovedEvent, "dreams"): EventType.DREAM_CREATED,
        (FileCreatedEvent, "mailbox"): EventType.MAILBOX_NEW_MESSAGE,
        (FileModifiedEvent, "mailbox"): EventType.MAILBOX_NEW_MESSAGE,
        (FileMovedEvent, "mailbox"): EventType.MAILBOX_NEW_MESSAGE,
    }

    return type_map.get((type(raw_event), topic))


def normalize_event(raw_event: FileSystemEvent) -> DomainEvent | None:
    """Transform raw filesystem event into typed domain event.

    Performs validation, extracts metadata, and creates a strongly typed
    domain event suitable for the event bus. For move/rename events
    (atomic writes), uses the destination path.

    Args:
        raw_event: Raw watchdog filesystem event.

    Returns:
        Normalized domain event if valid, None if event should be dropped.
    """
    if isinstance(raw_event, FileMovedEvent):
        path = Path(raw_event.dest_path)
    else:
        path = Path(raw_event.src_path)

    topic = determine_topic(str(path))

    if topic is None:
        logger.warning("event_unknown_topic", path=str(path))
        return None

    event_type = determine_event_type(raw_event, topic)
    if event_type is None:
        return None

    # Mailbox events: use the username directory as slug
    if topic == "mailbox":
        parts = path.parts
        try:
            mailbox_idx = parts.index("mailbox")
            username = parts[mailbox_idx + 1] if mailbox_idx + 1 < len(parts) else None
        except (ValueError, IndexError):
            username = None

        if username is None:
            return None

        return DomainEvent(
            id=str(uuid.uuid4()),
            type=event_type,
            timestamp=datetime.now(UTC),
            topic=topic,
            path=path.name,
            slug=username,
        )

    slug = extract_slug(path.name)
    if slug is None:
        logger.warning("event_invalid_slug", filename=path.name, path=str(path))
        return None

    return DomainEvent(
        id=str(uuid.uuid4()),
        type=event_type,
        timestamp=datetime.now(UTC),
        topic=topic,
        path=path.name,
        slug=slug,
    )
