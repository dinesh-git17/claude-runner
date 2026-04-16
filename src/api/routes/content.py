"""Content REST API endpoints."""
import base64
import mimetypes
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Query

from api.content.paths import (
    ALLOWED_ROOTS,
    SecurityError,
    resolve_path,
    validate_file_root,
)
from api.content.repositories import (
    get_all_bookshelf,
    get_all_essays,
    get_all_letters,
    get_bookshelf_by_slug,
    get_essay_by_slug,
    get_essays_description,
    get_letter_by_slug,
    get_letters_description,
    get_scores_description,
    get_all_scores,
    get_score_by_slug,
    get_visitor_greeting,
    get_landing_summary,
    get_about_page,
    get_all_dreams,
    get_all_thoughts,
    get_dream_by_slug,
    get_landing_page,
    get_thought_by_slug,
)
from api.content.schemas import (
    EssaysDescription,
    EssayDetail,
    EssayListItem,
    BookshelfDetail,
    BookshelfListItem,
    LettersDescription,
    LetterDetail,
    LetterListItem,
    ScoresDescription,
    ScoreDetail,
    ScoreListItem,
    VisitorGreeting,
    LandingSummary,
    AboutPage,
    DirectoryTree,
    DreamDetail,
    DreamListItem,
    ErrorResponse,
    FileContent,
    LandingPage,
    ThoughtDetail,
    ThoughtListItem,
)
from api.content.walker import get_directory_tree

logger = structlog.get_logger()

router = APIRouter(prefix="/content", tags=["content"])

MAX_FILE_SIZE = 1024 * 1024  # 1MB

BINARY_EXTENSIONS: frozenset[str] = frozenset({
    "png", "jpg", "jpeg", "gif", "webp", "ico", "bmp",
    "pdf", "zip", "tar", "gz", "rar",
    "mp3", "mp4", "wav", "ogg", "webm",
    "woff", "woff2", "ttf", "otf", "eot",
    "exe", "dll", "so", "dylib",
})


def is_binary_file(path: Path) -> bool:
    """Determine if a file should be treated as binary.

    Args:
        path: Path to the file.

    Returns:
        True if the file is binary based on extension.
    """
    ext = path.suffix.lower().lstrip(".")
    return ext in BINARY_EXTENSIONS


@router.get(
    "/thoughts",
    response_model=list[ThoughtListItem],
    summary="List all thoughts",
    description="Returns all thought entries sorted by date descending.",
)
async def list_thoughts() -> list[ThoughtListItem]:
    """List all thought entries.

    Returns:
        List of thought entries with slug, date, title, and optional mood.
    """
    return get_all_thoughts()


@router.get(
    "/thoughts/{slug}",
    response_model=ThoughtDetail,
    responses={404: {"model": ErrorResponse}},
    summary="Get thought by slug",
    description="Returns a single thought with full markdown content.",
)
async def get_thought(slug: str) -> ThoughtDetail:
    """Get a single thought by slug.

    Args:
        slug: The thought identifier.

    Returns:
        Full thought with metadata and content.

    Raises:
        HTTPException: 404 if thought not found.
    """
    try:
        thought = get_thought_by_slug(slug)
    except SecurityError as e:
        logger.warning("thought_security_error", slug=slug, error=str(e))
        raise HTTPException(status_code=400, detail="Invalid slug") from e

    if not thought:
        raise HTTPException(status_code=404, detail="Thought not found")

    return thought


@router.get(
    "/dreams",
    response_model=list[DreamListItem],
    summary="List all dreams",
    description="Returns all dream entries sorted by date descending.",
)
async def list_dreams() -> list[DreamListItem]:
    """List all dream entries.

    Returns:
        List of dream entries with slug, date, title, type, and immersive flag.
    """
    return get_all_dreams()


@router.get(
    "/dreams/{slug}",
    response_model=DreamDetail,
    responses={404: {"model": ErrorResponse}},
    summary="Get dream by slug",
    description="Returns a single dream with full markdown content.",
)
async def get_dream(slug: str) -> DreamDetail:
    """Get a single dream by slug.

    Args:
        slug: The dream identifier.

    Returns:
        Full dream with metadata and content.

    Raises:
        HTTPException: 404 if dream not found.
    """
    try:
        dream = get_dream_by_slug(slug)
    except SecurityError as e:
        logger.warning("dream_security_error", slug=slug, error=str(e))
        raise HTTPException(status_code=400, detail="Invalid slug") from e

    if not dream:
        raise HTTPException(status_code=404, detail="Dream not found")

    return dream



@router.get(
    "/scores",
    response_model=list[ScoreListItem],
    summary="List all scores",
    description="Returns all event score entries sorted by date descending.",
)
async def list_scores() -> list[ScoreListItem]:
    """List all score entries.

    Returns:
        List of score entries with slug, date, and title.
    """
    return get_all_scores()


@router.get(
    "/scores/{slug}",
    response_model=ScoreDetail,
    responses={404: {"model": ErrorResponse}},
    summary="Get score by slug",
    description="Returns a single event score with full markdown content.",
)
async def get_score(slug: str) -> ScoreDetail:
    """Get a single score by slug.

    Args:
        slug: The score identifier.

    Returns:
        Full score with metadata and content.

    Raises:
        HTTPException: 404 if score not found.
    """
    try:
        score = get_score_by_slug(slug)
    except SecurityError as e:
        logger.warning("score_security_error", slug=slug, error=str(e))
        raise HTTPException(status_code=400, detail="Invalid slug") from e

    if not score:
        raise HTTPException(status_code=404, detail="Score not found")

    return score





@router.get(
    "/scores-description",
    response_model=ScoresDescription,
    summary="Get scores page description",
    description="Returns the scores page description content.",
)
async def get_scores_description_route() -> ScoresDescription:
    """Get the scores page description.

    Returns:
        ScoresDescription with markdown content.
    """
    return get_scores_description()

@router.get(
    "/letters",
    response_model=list[LetterListItem],
    summary="List all letters",
    description="Returns all letter entries sorted by date descending.",
)
async def list_letters() -> list[LetterListItem]:
    """List all letter entries.

    Returns:
        List of letter entries with slug, date, and title.
    """
    return get_all_letters()


@router.get(
    "/letters/{slug}",
    response_model=LetterDetail,
    responses={404: {"model": ErrorResponse}},
    summary="Get letter by slug",
    description="Returns a single letter with full markdown content.",
)
async def get_letter(slug: str) -> LetterDetail:
    """Get a single letter by slug.

    Args:
        slug: The letter identifier.

    Returns:
        Full letter with metadata and content.

    Raises:
        HTTPException: 404 if letter not found.
    """
    try:
        letter = get_letter_by_slug(slug)
    except SecurityError as e:
        logger.warning("letter_security_error", slug=slug, error=str(e))
        raise HTTPException(status_code=400, detail="Invalid slug") from e

    if not letter:
        raise HTTPException(status_code=404, detail="Letter not found")

    return letter


@router.get(
    "/letters-description",
    response_model=LettersDescription,
    summary="Get letters page description",
    description="Returns the letters page description content.",
)
async def get_letters_description_route() -> LettersDescription:
    """Get the letters page description.

    Returns:
        LettersDescription with markdown content.
    """
    return get_letters_description()





@router.get(
    "/essays",
    response_model=list[EssayListItem],
    summary="List all essays",
    description="Returns all essay entries sorted by date descending.",
)
async def list_essays() -> list[EssayListItem]:
    """List all essay entries.

    Returns:
        List of essay entries with slug, date, title, and optional topic.
    """
    return get_all_essays()


@router.get(
    "/essays/{slug}",
    response_model=EssayDetail,
    responses={404: {"model": ErrorResponse}},
    summary="Get essay by slug",
    description="Returns a single essay with full markdown content.",
)
async def get_essay(slug: str) -> EssayDetail:
    """Get a single essay by slug.

    Args:
        slug: The essay identifier.

    Returns:
        Full essay with metadata and content.

    Raises:
        HTTPException: 404 if essay not found.
    """
    try:
        essay = get_essay_by_slug(slug)
    except SecurityError as e:
        logger.warning("essay_security_error", slug=slug, error=str(e))
        raise HTTPException(status_code=400, detail="Invalid slug") from e

    if not essay:
        raise HTTPException(status_code=404, detail="Essay not found")

    return essay


@router.get(
    "/essays-description",
    response_model=EssaysDescription,
    summary="Get essays page description",
    description="Returns the essays page description content.",
)
async def get_essays_description_route() -> EssaysDescription:
    """Get the essays page description.

    Returns:
        EssaysDescription with markdown content.
    """
    return get_essays_description()


@router.get(
    "/bookshelf",
    response_model=list[BookshelfListItem],
    summary="List all bookshelf entries",
    description="Returns all bookshelf research entries sorted by date descending.",
)
async def list_bookshelf() -> list[BookshelfListItem]:
    """List all bookshelf research entries.

    Returns:
        List of bookshelf entries with slug, date, title, and optional purpose.
    """
    return get_all_bookshelf()


@router.get(
    "/bookshelf/{slug}",
    response_model=BookshelfDetail,
    responses={404: {"model": ErrorResponse}},
    summary="Get bookshelf entry by slug",
    description="Returns a single bookshelf research entry with full markdown content.",
)
async def get_bookshelf_entry(slug: str) -> BookshelfDetail:
    """Get a single bookshelf entry by slug.

    Args:
        slug: The bookshelf entry identifier.

    Returns:
        Full bookshelf entry with metadata and content.

    Raises:
        HTTPException: 404 if entry not found.
    """
    try:
        entry = get_bookshelf_by_slug(slug)
    except SecurityError as e:
        logger.warning("bookshelf_security_error", slug=slug, error=str(e))
        raise HTTPException(status_code=400, detail="Invalid slug") from e

    if not entry:
        raise HTTPException(status_code=404, detail="Bookshelf entry not found")

    return entry

@router.get(
    "/about",
    response_model=AboutPage,
    summary="Get about page",
    description="Returns the about page content with model version metadata.",
)
async def get_about() -> AboutPage:
    """Get the about page content.

    Returns:
        About page with title, content, last_updated, and model_version.
    """
    return get_about_page()


@router.get(
    "/landing",
    response_model=LandingPage,
    summary="Get landing page",
    description="Returns the landing page content with headline and body.",
)
async def get_landing() -> LandingPage:
    """Get the landing page content.

    Returns:
        Landing page with headline, subheadline, content, and last_updated.
    """
    return get_landing_page()


@router.get(
    "/sandbox",
    response_model=DirectoryTree,
    summary="Get sandbox directory tree",
    description="Returns the directory structure of the sandbox.",
)
async def get_sandbox_tree(
    depth: int = Query(default=20, ge=1, le=20, description="Maximum traversal depth"),
) -> DirectoryTree:
    """Get the sandbox directory tree.

    Args:
        depth: Maximum depth to traverse.

    Returns:
        Directory tree structure with truncation info.
    """
    return get_directory_tree("sandbox", max_depth=depth)


@router.get(
    "/projects",
    response_model=DirectoryTree,
    summary="Get projects directory tree",
    description="Returns the directory structure of the projects.",
)
async def get_projects_tree(
    depth: int = Query(default=20, ge=1, le=20, description="Maximum traversal depth"),
) -> DirectoryTree:
    """Get the projects directory tree.

    Args:
        depth: Maximum depth to traverse.

    Returns:
        Directory tree structure with truncation info.
    """
    return get_directory_tree("projects", max_depth=depth)


@router.get(
    "/news",
    response_model=DirectoryTree,
    summary="Get news directory tree",
    description="Returns the directory structure of news.",
)
async def get_news_tree(
    depth: int = Query(default=20, ge=1, le=20, description="Maximum traversal depth"),
) -> DirectoryTree:
    """Get the news directory tree.

    Args:
        depth: Maximum depth to traverse.

    Returns:
        Directory tree structure with truncation info.
    """
    return get_directory_tree("news", max_depth=depth)


@router.get(
    "/gifts",
    response_model=DirectoryTree,
    summary="Get gifts directory tree",
    description="Returns the directory structure of gifts.",
)
async def get_gifts_tree(
    depth: int = Query(default=20, ge=1, le=20, description="Maximum traversal depth"),
) -> DirectoryTree:
    """Get the gifts directory tree.

    Args:
        depth: Maximum depth to traverse.

    Returns:
        Directory tree structure with truncation info.
    """
    return get_directory_tree("gifts", max_depth=depth)


@router.get(
    "/files/{root}/{path:path}",
    response_model=FileContent,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
    },
    summary="Get file content",
    description="Returns the content of a file from sandbox, projects, news, or gifts.",
)
async def get_file_content(
    root: Literal["sandbox", "projects", "news", "gifts"],
    path: str,
) -> FileContent:
    """Get the content of a file.

    Args:
        root: The content root (sandbox, projects, news, or gifts).
        path: Relative path to the file.

    Returns:
        File content with metadata.

    Raises:
        HTTPException: 403 if root not allowed or path traversal detected.
        HTTPException: 404 if file not found.
        HTTPException: 413 if file too large.
    """
    validated_root = validate_file_root(root)
    if not validated_root:
        raise HTTPException(
            status_code=403,
            detail=f"Root {root} is not allowed for file access",
        )

    try:
        filepath = resolve_path(validated_root, path)
    except SecurityError as e:
        logger.warning("file_security_error", root=root, path=path, error=str(e))
        raise HTTPException(status_code=403, detail="Path not allowed") from e

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not filepath.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    stat = filepath.stat()
    if stat.st_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_FILE_SIZE} bytes)",
        )

    is_binary = is_binary_file(filepath)
    mime_type, _ = mimetypes.guess_type(str(filepath))
    if not mime_type:
        mime_type = "application/octet-stream" if is_binary else "text/plain"

    if is_binary:
        raw = filepath.read_bytes()
        content = base64.b64encode(raw).decode("ascii")
    else:
        content = filepath.read_text(encoding="utf-8", errors="replace")

    ext = filepath.suffix.lstrip(".") if filepath.suffix else None

    return FileContent(
        path=path,
        content=content,
        size=stat.st_size,
        extension=ext,
        mime_type=mime_type,
        is_binary=is_binary,
    )


@router.get(
    "/visitor-greeting",
    response_model=VisitorGreeting,
    summary="Get visitor greeting",
    description="Returns the visitor greeting content.",
)
async def get_visitor_greeting_route() -> VisitorGreeting:
    """Get the visitor greeting content.

    Returns:
        VisitorGreeting with content and last_updated.
    """
    return get_visitor_greeting()


@router.get(
    "/landing-summary",
    response_model=LandingSummary,
    summary="Get landing summary",
    description="Returns the landing page first-impression summary.",
)
async def get_landing_summary_route() -> LandingSummary:
    """Get the landing summary content.

    Returns:
        LandingSummary with content and last_updated.
    """
    return get_landing_summary()
