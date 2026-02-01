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
    return None


def determine_event_type(
    raw_event: FileSystemEvent,
    topic: Topic,
) -> EventType | None:
    """Determine domain event type from raw filesystem event.

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
        (FileCreatedEvent, "dreams"): EventType.DREAM_CREATED,
        (FileModifiedEvent, "dreams"): EventType.DREAM_MODIFIED,
        (FileDeletedEvent, "dreams"): EventType.DREAM_DELETED,
    }

    return type_map.get((type(raw_event), topic))


def normalize_event(raw_event: FileSystemEvent) -> DomainEvent | None:
    """Transform raw filesystem event into typed domain event.

    Performs validation, extracts metadata, and creates a strongly typed
    domain event suitable for the event bus.

    Args:
        raw_event: Raw watchdog filesystem event.

    Returns:
        Normalized domain event if valid, None if event should be dropped.
    """
    src_path = raw_event.src_path
    if isinstance(src_path, str):
        path_str = src_path
    else:
        path_str = bytes(src_path).decode("utf-8", errors="replace")
    path = Path(path_str)
    topic = determine_topic(str(path))

    if topic is None:
        logger.warning("event_unknown_topic", path=str(path))
        return None

    event_type = determine_event_type(raw_event, topic)
    if event_type is None:
        return None

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
