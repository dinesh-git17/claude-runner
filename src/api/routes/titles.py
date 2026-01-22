"""Title registry API endpoints."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from api.content.repositories import titles as titles_repo
from api.content.schemas import TitleCreateRequest, TitleEntry

router = APIRouter(prefix="/titles", tags=["titles"])


@router.get(
    "/{content_hash}",
    response_model=TitleEntry,
    responses={404: {"description": "Title not found"}},
)
async def get_title(content_hash: str) -> TitleEntry:
    """Retrieve cached title by content hash.

    Args:
        content_hash: SHA-256 hash of the content.

    Returns:
        TitleEntry if found.

    Raises:
        HTTPException: 404 if not found.
    """
    entry = titles_repo.get_by_hash(content_hash)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Title not found",
        )
    return entry


@router.post(
    "",
    response_model=TitleEntry,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "Title already exists"}},
)
async def store_title(request: TitleCreateRequest) -> JSONResponse:
    """Store a newly generated title.

    Args:
        request: Title creation request with hash, title, model, original_path.

    Returns:
        TitleEntry with 201 Created, or 409 Conflict if exists.
    """
    entry, created = titles_repo.store(
        content_hash=request.hash,
        title=request.title,
        model=request.model,
        original_path=request.original_path,
    )

    if not created:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=entry.model_dump(mode="json"),
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=entry.model_dump(mode="json"),
    )
