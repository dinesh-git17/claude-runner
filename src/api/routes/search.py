"""Full-text search API endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query, Request

from api.search.schemas import SearchResponse

if TYPE_CHECKING:
    from api.search.index import SearchIndex

router = APIRouter(tags=["search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Full-text search across thoughts and dreams",
    description="Searches content using FTS5 with BM25 ranking and snippet extraction.",
)
async def search(
    request: Request,
    q: str = Query(
        ...,
        min_length=1,
        max_length=200,
        description="Search query string",
    ),
    type: str = Query(
        default="all",
        pattern="^(all|thought|dream)$",
        description="Filter by content type",
    ),
    limit: int = Query(default=20, ge=1, le=50, description="Results per page"),
    offset: int = Query(default=0, ge=0, description="Results to skip"),
) -> SearchResponse:
    """Search across thoughts and dreams with full-text matching.

    Args:
        request: FastAPI request (provides access to app state).
        q: Search query string (1-200 characters).
        type: Content type filter (all, thought, or dream).
        limit: Maximum results per page (1-50, default 20).
        offset: Pagination offset (default 0).

    Returns:
        Paginated search results with BM25-ranked matches and snippets.
    """
    search_index: SearchIndex = request.app.state.search_index
    content_type = type if type != "all" else None

    return search_index.search(
        query=q,
        content_type=content_type,
        limit=limit,
        offset=offset,
    )
