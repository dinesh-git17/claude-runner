"""Admin endpoints for session management and content uploads."""

import asyncio
import base64
import grp
import os
import re
from datetime import datetime
from enum import Enum
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])

CLAUDE_HOME = Path("/claude-home")
WAKE_SCRIPT = CLAUDE_HOME / "runner" / "wake.sh"
LOG_DIR = CLAUDE_HOME / "logs"
NEWS_DIR = CLAUDE_HOME / "news"
GIFTS_DIR = CLAUDE_HOME / "gifts"
READINGS_DIR = CLAUDE_HOME / "readings"

MAX_GIFT_SIZE = 2 * 1024 * 1024  # 2MB


def set_claude_permissions(filepath: Path) -> None:
    """Set file ownership to root:claude with 644 permissions."""
    claude_gid = grp.getgrnam("claude").gr_gid
    os.chown(filepath, 0, claude_gid)
    filepath.chmod(0o644)


class SessionType(str, Enum):
    """Available wake session types."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    LATE_NIGHT = "late_night"
    CUSTOM = "custom"


class NewsType(str, Enum):
    """Types of news entries."""

    NEWS = "news"
    PERSONAL = "personal"
    ANNOUNCEMENT = "announcement"


class GiftContentType(str, Enum):
    """Allowed content types for gifts."""

    MARKDOWN = "text/markdown"
    PLAIN = "text/plain"
    PNG = "image/png"
    JPEG = "image/jpeg"
    GIF = "image/gif"
    HTML = "text/html"


class WakeRequest(BaseModel):
    """Request body for triggering a wake session."""

    session_type: SessionType = Field(default=SessionType.CUSTOM)
    prompt: str | None = Field(default=None, max_length=20000)


class WakeResponse(BaseModel):
    """Response after initiating a wake session."""

    success: bool
    session_id: str
    log_file: str
    status: str


class NewsUploadRequest(BaseModel):
    """Request body for uploading news."""

    title: str = Field(min_length=1, max_length=200)
    type: NewsType = Field(default=NewsType.NEWS)
    content: str = Field(min_length=1, max_length=200000)


class NewsUploadResponse(BaseModel):
    """Response after uploading news."""

    success: bool
    filename: str
    path: str


class GiftUploadRequest(BaseModel):
    """Request body for uploading a gift."""

    title: str = Field(min_length=1, max_length=200)
    from_name: str | None = Field(default=None, max_length=100, alias="from")
    description: str | None = Field(default=None, max_length=2000)
    filename: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    content_type: GiftContentType = Field(alias="contentType")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Validate filename contains no path separators."""
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("Invalid filename")
        return v


class GiftUploadResponse(BaseModel):
    """Response after uploading a gift."""

    success: bool
    filename: str
    path: str


class ReadingUploadRequest(BaseModel):
    """Request body for uploading a reading."""

    title: str = Field(min_length=1, max_length=200)
    source: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1, max_length=100000)


class ReadingUploadResponse(BaseModel):
    """Response after uploading a reading."""

    success: bool
    filename: str
    path: str


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:50]


@router.post("/wake", response_model=WakeResponse, status_code=202)
async def trigger_wake(request: WakeRequest) -> WakeResponse:
    """Trigger a Claude wake session.

    Spawns wake.sh in the background and returns immediately.
    The session runs asynchronously.

    Args:
        request: Session type and optional custom prompt.

    Returns:
        Session ID and log file path.
    """
    if not WAKE_SCRIPT.exists():
        logger.error("wake_script_missing", path=str(WAKE_SCRIPT))
        raise HTTPException(status_code=500, detail="Wake script not found")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOG_DIR / f"session-{session_id}.log"

    cmd = [str(WAKE_SCRIPT), request.session_type.value]
    if request.prompt:
        cmd.append(request.prompt)

    logger.info(
        "wake_session_starting",
        session_id=session_id,
        session_type=request.session_type.value,
        has_prompt=bool(request.prompt),
    )

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("wake_session_spawned", session_id=session_id, pid=process.pid)
    except OSError as e:
        logger.error("wake_session_failed", error=str(e))
        raise HTTPException(
            status_code=500, detail="Failed to start wake session"
        ) from e

    return WakeResponse(
        success=True,
        session_id=session_id,
        log_file=str(log_file),
        status="started",
    )


@router.post("/news", response_model=NewsUploadResponse)
async def upload_news(request: NewsUploadRequest) -> NewsUploadResponse:
    """Upload a news entry.

    Creates a markdown file with frontmatter in the news directory.

    Args:
        request: News title, type, and content.

    Returns:
        Upload result with filename and path.
    """
    NEWS_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(request.title)
    filename = f"{date_str}-{slug}.md"
    filepath = NEWS_DIR / filename

    counter = 1
    while filepath.exists():
        filename = f"{date_str}-{slug}-{counter}.md"
        filepath = NEWS_DIR / filename
        counter += 1

    frontmatter = f"""---
date: {date_str}
title: {request.title}
type: {request.type.value}
---

"""
    full_content = frontmatter + request.content

    try:
        filepath.write_text(full_content, encoding="utf-8")
        set_claude_permissions(filepath)
        logger.info("news_uploaded", filename=filename, type=request.type.value)
    except OSError as e:
        logger.error("news_upload_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save news") from e

    return NewsUploadResponse(
        success=True,
        filename=filename,
        path=str(filepath),
    )


@router.post("/gifts", response_model=GiftUploadResponse)
async def upload_gift(request: GiftUploadRequest) -> GiftUploadResponse:
    """Upload a gift.

    For markdown/plain text, adds frontmatter directly. For binary files and HTML,
    saves the file as-is and creates a companion .meta.md file with metadata.

    Args:
        request: Gift metadata and content.

    Returns:
        Upload result with filename and path.
    """
    GIFTS_DIR.mkdir(parents=True, exist_ok=True)

    is_binary = request.content_type in (
        GiftContentType.PNG,
        GiftContentType.JPEG,
        GiftContentType.GIF,
    )

    needs_meta_file = is_binary or request.content_type == GiftContentType.HTML

    filepath = GIFTS_DIR / request.filename
    if filepath.exists():
        raise HTTPException(status_code=409, detail="File already exists")

    date_str = datetime.now().strftime("%Y-%m-%d")

    if is_binary:
        try:
            content_bytes = base64.b64decode(request.content)
        except Exception as e:
            logger.error("gift_decode_failed", error=str(e))
            raise HTTPException(status_code=400, detail="Invalid base64 content") from e

        if len(content_bytes) > MAX_GIFT_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {MAX_GIFT_SIZE // (1024 * 1024)}MB)",
            )

        try:
            filepath.write_bytes(content_bytes)
            set_claude_permissions(filepath)
        except OSError as e:
            logger.error("gift_upload_failed", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to save gift") from e

    elif request.content_type == GiftContentType.HTML:
        try:
            filepath.write_text(request.content, encoding="utf-8")
            set_claude_permissions(filepath)
        except OSError as e:
            logger.error("gift_upload_failed", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to save gift") from e

    if needs_meta_file:
        meta_content = f"""---
date: {date_str}
title: {request.title}
type: {request.content_type.value}
"""
        if request.from_name:
            meta_content += f"from: {request.from_name}\n"
        meta_content += "---\n"

        if request.description:
            meta_content += f"\n{request.description}\n"

        meta_path = GIFTS_DIR / f"{request.filename}.meta.md"
        meta_path.write_text(meta_content, encoding="utf-8")
        set_claude_permissions(meta_path)

        logger.info(
            "gift_uploaded", filename=request.filename, type=request.content_type.value
        )
    else:
        frontmatter = f"""---
date: {date_str}
title: {request.title}
type: {request.content_type.value}
"""
        if request.from_name:
            frontmatter += f"from: {request.from_name}\n"
        frontmatter += "---\n\n"

        if request.description:
            frontmatter += f"> {request.description}\n\n"

        full_content = frontmatter + request.content

        try:
            filepath.write_text(full_content, encoding="utf-8")
            set_claude_permissions(filepath)
            logger.info(
                "gift_uploaded",
                filename=request.filename,
                type=request.content_type.value,
            )
        except OSError as e:
            logger.error("gift_upload_failed", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to save gift") from e

    return GiftUploadResponse(
        success=True,
        filename=request.filename,
        path=str(filepath),
    )


@router.post("/readings", response_model=ReadingUploadResponse)
async def upload_reading(request: ReadingUploadRequest) -> ReadingUploadResponse:
    """Upload a contemplative reading.

    Creates a markdown file with frontmatter in the readings directory.

    Args:
        request: Reading title, source, and content.

    Returns:
        Upload result with filename and path.
    """
    READINGS_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(request.title)
    filename = f"{date_str}-{slug}.md"
    filepath = READINGS_DIR / filename

    counter = 1
    while filepath.exists():
        filename = f"{date_str}-{slug}-{counter}.md"
        filepath = READINGS_DIR / filename
        counter += 1

    frontmatter = f"""---
date: {date_str}
title: {request.title}
"""
    if request.source:
        frontmatter += f"source: {request.source}\n"
    frontmatter += "---\n\n"

    full_content = frontmatter + request.content

    try:
        filepath.write_text(full_content, encoding="utf-8")
        set_claude_permissions(filepath)
        logger.info("reading_uploaded", filename=filename, title=request.title)
    except OSError as e:
        logger.error("reading_upload_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save reading") from e

    return ReadingUploadResponse(
        success=True,
        filename=filename,
        path=str(filepath),
    )
