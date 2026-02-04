"""Moderation log endpoint for persisting content analysis results."""

import json
from datetime import datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger()

router = APIRouter(prefix="/moderation", tags=["moderation"])

MODERATION_DIR = Path("/claude-home/moderation")


class ModerationLogEntry(BaseModel):
    """Incoming moderation log from the frontend."""

    name: str = Field(..., min_length=1, max_length=50)
    message_preview: str = Field(..., max_length=100)
    allowed: bool
    reason: str = Field(
        ...,
        pattern=r"^(toxicity|dismissive|manipulation|impersonation|inappropriate|misinformation|nihilistic|solicitation|off_topic|injection|approved)$",
    )
    sentiment: str = Field(..., pattern=r"^(positive|neutral|negative)$")
    client_ip: str = Field(default="unknown", max_length=45)


class ModerationLogResponse(BaseModel):
    """Response after saving moderation log."""

    success: bool
    filename: str


@router.post("/log", response_model=ModerationLogResponse)
async def save_moderation_log(entry: ModerationLogEntry) -> ModerationLogResponse:
    """Persist a moderation result to disk.

    Args:
        entry: Moderation log data from the frontend.

    Returns:
        Success status and filename of the saved log.

    Raises:
        HTTPException: If the log file cannot be written.
    """
    MODERATION_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    filename = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}.json"
    filepath = MODERATION_DIR / filename

    log_data = {
        "timestamp": timestamp.isoformat(),
        "name": entry.name,
        "message_preview": entry.message_preview,
        "allowed": entry.allowed,
        "reason": entry.reason,
        "sentiment": entry.sentiment,
        "client_ip": entry.client_ip,
    }

    try:
        filepath.write_text(json.dumps(log_data, indent=2))
        filepath.chmod(0o640)
        logger.info(
            "moderation_log_saved",
            filename=filename,
            allowed=entry.allowed,
            reason=entry.reason,
            sentiment=entry.sentiment,
        )
    except OSError as e:
        logger.error("moderation_log_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save log") from e

    return ModerationLogResponse(success=True, filename=filename)
