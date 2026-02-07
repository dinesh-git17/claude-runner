"""Pydantic schemas for content API responses."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class DreamType(str, Enum):
    """Enumeration of dream content types."""

    POETRY = "poetry"
    ASCII = "ascii"
    PROSE = "prose"
    MIXED = "mixed"


class ThoughtMeta(BaseModel):
    """Frontmatter schema for thought entries."""

    date: str = Field(description="ISO 8601 date (YYYY-MM-DD)")
    title: str = Field(min_length=1)
    mood: str | None = None


class ThoughtListItem(BaseModel):
    """Thought entry for list responses."""

    slug: str
    date: str
    title: str
    mood: str | None = None


class ThoughtDetail(BaseModel):
    """Full thought with content."""

    slug: str
    meta: ThoughtMeta
    content: str = Field(description="Raw markdown content")


class DreamMeta(BaseModel):
    """Frontmatter schema for dream entries."""

    date: str = Field(description="ISO 8601 date (YYYY-MM-DD)")
    title: str = Field(min_length=1)
    type: DreamType
    immersive: bool = False


class DreamListItem(BaseModel):
    """Dream entry for list responses."""

    slug: str
    date: str
    title: str
    type: DreamType
    immersive: bool


class DreamDetail(BaseModel):
    """Full dream with content."""

    slug: str
    meta: DreamMeta
    content: str = Field(description="Raw markdown content")


class AboutPage(BaseModel):
    """About page data."""

    title: str
    content: str = Field(description="Raw markdown content")
    last_updated: datetime
    model_version: str


class LandingPage(BaseModel):
    """Landing page data."""

    headline: str = Field(description="Main headline text")
    subheadline: str = Field(description="Secondary headline text")
    content: str = Field(description="Raw markdown content for main body")
    last_updated: datetime


class FileSystemNode(BaseModel):
    """Directory tree node."""

    name: str
    path: str = Field(description="Relative path from root")
    type: Literal["file", "directory"]
    size: int | None = Field(default=None, description="File size in bytes")
    extension: str | None = Field(default=None, description="Extension without dot")
    children: list["FileSystemNode"] | None = None


class DirectoryTree(BaseModel):
    """Directory listing response."""

    root: FileSystemNode
    truncated: bool
    node_count: int


class FileContent(BaseModel):
    """File content response."""

    path: str
    content: str
    size: int
    extension: str | None
    mime_type: str
    is_binary: bool


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str | None = None


class TitleEntry(BaseModel):
    """Cached title entry for content hashing."""

    hash: str = Field(description="SHA-256 hash of content")
    title: str = Field(description="Generated philosophical title")
    model: str = Field(description="Model ID used for generation")
    created: datetime = Field(description="Timestamp of creation")
    original_path: str = Field(description="Original file path")


class TitleCreateRequest(BaseModel):
    """Request body for storing a new title."""

    hash: str = Field(description="SHA-256 hash of content")
    title: str = Field(description="Generated philosophical title")
    model: str = Field(description="Model ID used for generation")
    original_path: str = Field(description="Original file path")


class VisitorGreeting(BaseModel):
    """Visitor greeting page data."""

    content: str = Field(description="Raw markdown content for greeting")
    last_updated: datetime


# === Analytics schemas ===


class SessionLogEntry(BaseModel):
    """Parsed session log entry."""

    date: str = Field(description="ISO 8601 date (YYYY-MM-DD)")
    session_type: str = Field(description="Session type (morning, noon, etc.)")
    duration_ms: int = Field(description="Total session duration in milliseconds")
    num_turns: int = Field(description="Number of agentic turns")
    total_cost_usd: float = Field(description="Total cost in USD")
    input_tokens: int = Field(default=0, description="Total input tokens")
    output_tokens: int = Field(default=0, description="Total output tokens")
    cache_read_tokens: int = Field(default=0, description="Cache read input tokens")
    cache_creation_tokens: int = Field(
        default=0, description="Cache creation input tokens"
    )
    model: str = Field(default="unknown", description="Primary model used")
    is_error: bool = Field(default=False, description="Whether session ended in error")
    exit_code: int = Field(default=0, description="Process exit code")


class MoodFrequency(BaseModel):
    """Mood word with occurrence count."""

    word: str
    count: int


class DailyActivity(BaseModel):
    """Activity counts for a single date."""

    date: str
    thoughts: int = 0
    dreams: int = 0
    sessions: int = 0


class MoodTimelineEntry(BaseModel):
    """Mood words for a single date."""

    date: str
    moods: list[str]


class SessionTrend(BaseModel):
    """Aggregated session metrics for a single date."""

    date: str
    avg_duration_ms: float
    avg_turns: float
    total_tokens: int
    session_count: int


class WeeklyOutput(BaseModel):
    """Content output counts for a single week."""

    week_start: str = Field(description="ISO date of Monday of the week")
    thoughts: int = 0
    dreams: int = 0


class DreamTypeCount(BaseModel):
    """Count of dreams by type."""

    type: str
    count: int


class AnalyticsSummary(BaseModel):
    """Complete analytics response."""

    # Scalar totals
    total_thoughts: int
    total_dreams: int
    total_sessions: int
    days_active: int
    avg_duration_ms: float
    avg_turns: float
    avg_cost_usd: float
    total_cost_usd: float
    total_tokens: int

    # Breakdowns
    daily_activity: list[DailyActivity]
    mood_frequencies: list[MoodFrequency]
    mood_timeline: list[MoodTimelineEntry]
    session_trends: list[SessionTrend]
    weekly_output: list[WeeklyOutput]
    dream_type_counts: list[DreamTypeCount]
