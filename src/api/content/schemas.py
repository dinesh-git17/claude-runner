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
