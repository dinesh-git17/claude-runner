"""Pydantic schemas for full-text search API responses."""

from enum import Enum

from pydantic import BaseModel, Field


class SearchResultType(str, Enum):
    """Content type discriminator for search results."""

    THOUGHT = "thought"
    DREAM = "dream"


class SearchResult(BaseModel):
    """Individual search result with matched snippet.

    Attributes:
        slug: URL-safe identifier for the content.
        title: Content title, possibly with highlight markers.
        result_type: Whether this result is a thought or dream.
        date: ISO 8601 date string (YYYY-MM-DD).
        snippet: Body excerpt with <mark> highlight tags.
        score: BM25 relevance score (lower is better).
        mood: Thought mood tag, if applicable.
        dream_type: Dream content type, if applicable.
    """

    slug: str
    title: str
    result_type: SearchResultType
    date: str
    snippet: str = Field(description="Body excerpt with <mark> highlight tags")
    score: float
    mood: str | None = None
    dream_type: str | None = None


class SearchResponse(BaseModel):
    """Paginated search response envelope.

    Attributes:
        query: The original search query string.
        results: List of matched content results.
        total: Total number of matching documents.
        limit: Maximum results per page.
        offset: Number of results skipped.
    """

    query: str
    results: list[SearchResult]
    total: int
    limit: int
    offset: int
