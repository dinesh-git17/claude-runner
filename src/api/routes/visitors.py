"""Visitor message endpoint."""
import re
from datetime import datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = structlog.get_logger()

router = APIRouter(prefix="/visitors", tags=["visitors"])

VISITORS_DIR = Path("/claude-home/visitors")
MAX_MESSAGE_LENGTH = 2000
MAX_NAME_LENGTH = 50


class VisitorMessage(BaseModel):
    """Incoming visitor message."""

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        """Remove special characters from name."""
        return re.sub(r"[^a-zA-Z0-9\s\-]", "", v).strip()


class VisitorResponse(BaseModel):
    """Response after saving message."""

    success: bool
    filename: str


@router.post("", response_model=VisitorResponse)
async def leave_message(msg: VisitorMessage) -> VisitorResponse:
    """Save a visitor message for Claude to read later.

    Args:
        msg: The visitor's name and message.

    Returns:
        Confirmation with the saved filename.
    """
    VISITORS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    safe_name = re.sub(r"[^a-zA-Z0-9]", "-", msg.name.lower()).strip("-")[:20]
    filename = f"{timestamp}-{safe_name}.md"
    filepath = VISITORS_DIR / filename

    content = f"""---
date: "{datetime.now().strftime('%Y-%m-%d')}"
from: "{msg.name}"
---

{msg.message}
"""

    try:
        filepath.write_text(content)
        filepath.chmod(0o644)
        logger.info("visitor_message_saved", filename=filename, name=msg.name)
    except OSError as e:
        logger.error("visitor_message_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save message") from e

    return VisitorResponse(success=True, filename=filename)
