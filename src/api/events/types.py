"""Domain event types for filesystem monitoring."""
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Domain event types for filesystem changes."""

    THOUGHT_CREATED = "thought.created"
    THOUGHT_MODIFIED = "thought.modified"
    THOUGHT_DELETED = "thought.deleted"
    DREAM_CREATED = "dream.created"
    DREAM_MODIFIED = "dream.modified"
    DREAM_DELETED = "dream.deleted"
    HEARTBEAT = "heartbeat"
    SYSTEM_OVERLOAD = "system.overload"


Topic = Literal["thoughts", "dreams", "system"]


TEMP_FILE_PATTERNS: tuple[str, ...] = (
    ".swp",
    ".swo",
    ".swn",
    ".tmp",
    ".temp",
    "~",
    ".DS_Store",
    ".git",
    ".4913",
)


WATCHED_DIRECTORIES: tuple[str, ...] = (
    "/claude-home/thoughts",
    "/claude-home/dreams",
)


class DomainEvent(BaseModel):
    """Typed domain event for filesystem changes.

    Attributes:
        id: Unique event identifier (UUID).
        type: Event type indicating the action and content type.
        timestamp: Event timestamp in UTC.
        topic: Event topic for routing to subscribers.
        path: Relative file path within the content directory.
        slug: Extracted slug from the filename.
    """

    id: str = Field(description="Unique event identifier (UUID)")
    type: EventType = Field(description="Event type")
    timestamp: datetime = Field(description="Event timestamp (UTC)")
    topic: Topic = Field(description="Event topic for routing")
    path: str | None = Field(default=None, description="Relative file path")
    slug: str | None = Field(default=None, description="Extracted slug from filename")
