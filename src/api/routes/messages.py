"""Trusted user message endpoint with API key authentication."""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import structlog
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.services.moderator import log_moderation, moderate_message

logger = structlog.get_logger()

router = APIRouter(prefix="/messages", tags=["messages"])

VISITORS_DIR = Path("/claude-home/visitors")
RATE_LIMIT_FILE = Path("/claude-home/data/api-rate-limits.json")
MAX_WORDS = 500
MAX_NAME_LENGTH = 50
RATE_LIMIT_HOURS = 8


def get_trusted_keys() -> set[str]:
    """Load trusted API keys from environment."""
    raw = os.getenv("TRUSTED_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def load_rate_limits() -> dict[str, str]:
    """Load rate limit timestamps from file."""
    if not RATE_LIMIT_FILE.exists():
        return {}
    try:
        data = json.loads(RATE_LIMIT_FILE.read_text())
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_rate_limits(limits: dict[str, str]) -> None:
    """Save rate limit timestamps to file."""
    RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RATE_LIMIT_FILE.write_text(json.dumps(limits, indent=2))


def check_rate_limit(token: str) -> tuple[bool, int | None]:
    """Check if token is rate limited.

    Returns:
        Tuple of (is_allowed, seconds_until_allowed or None)
    """
    limits = load_rate_limits()
    last_used = limits.get(token)

    if not last_used:
        return True, None

    try:
        last_time = datetime.fromisoformat(last_used)
        next_allowed = last_time + timedelta(hours=RATE_LIMIT_HOURS)
        now = datetime.now()

        if now >= next_allowed:
            return True, None

        seconds_remaining = int((next_allowed - now).total_seconds())
        return False, seconds_remaining
    except ValueError:
        return True, None


def record_usage(token: str) -> None:
    """Record that a token was used."""
    limits = load_rate_limits()
    limits[token] = datetime.now().isoformat()
    save_rate_limits(limits)


class TrustedMessage(BaseModel):
    """Incoming message from trusted user."""

    name: str = Field(..., min_length=1, max_length=MAX_NAME_LENGTH)
    message: str = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        """Remove special characters from name."""
        return re.sub(r"[^a-zA-Z0-9\s\-]", "", v).strip()


class MessageResponse(BaseModel):
    """Response after saving message."""

    success: bool
    filename: str
    word_count: int


@router.post("", response_model=MessageResponse)
async def send_message(
    msg: TrustedMessage,
    authorization: str = Header(..., description="Bearer token"),
) -> MessageResponse:
    """Save a message from a trusted user.

    Requires a valid API key in the Authorization header.
    Messages are limited to 250 words and one per day.

    Args:
        msg: The sender's name and message.
        authorization: Bearer token containing the API key.

    Returns:
        Confirmation with the saved filename and word count.

    Raises:
        HTTPException: 401 if API key is invalid, 400 if message exceeds word limit,
                      429 if rate limited.
    """
    token = authorization.removeprefix("Bearer ").strip()
    trusted_keys = get_trusted_keys()

    if not trusted_keys:
        logger.error("no_trusted_keys_configured")
        raise HTTPException(status_code=500, detail="API keys not configured")

    if token not in trusted_keys:
        logger.warning(
            "invalid_api_key_attempt", token_prefix=token[:8] if token else ""
        )
        raise HTTPException(status_code=401, detail="Invalid API key")

    is_allowed, seconds_remaining = check_rate_limit(token)
    if not is_allowed:
        hours_remaining = (seconds_remaining or 0) // 3600
        minutes_remaining = ((seconds_remaining or 0) % 3600) // 60
        logger.warning("rate_limit_exceeded", token_prefix=token[:8])
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {hours_remaining}h {minutes_remaining}m",
        )

    word_count = len(msg.message.split())
    if word_count > MAX_WORDS:
        raise HTTPException(
            status_code=400,
            detail=f"Message exceeds {MAX_WORDS} words (submitted: {word_count})",
        )

    moderation = await moderate_message(msg.message, msg.name)
    log_moderation(msg.name, msg.message, moderation, source="api")

    if not moderation.allowed:
        raise HTTPException(
            status_code=400,
            detail="Message could not be accepted.",
        )

    VISITORS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    safe_name = re.sub(r"[^a-zA-Z0-9]", "-", msg.name.lower()).strip("-")[:20]
    filename = f"{timestamp}-{safe_name}.md"
    filepath = VISITORS_DIR / filename

    content = f"""---
date: "{datetime.now().strftime("%Y-%m-%d")}"
from: "{msg.name}"
source: "api"
---

{msg.message}
"""

    try:
        filepath.write_text(content)
        filepath.chmod(0o644)
        record_usage(token)
        logger.info(
            "trusted_message_saved",
            filename=filename,
            name=msg.name,
            word_count=word_count,
        )
    except OSError as e:
        logger.error("trusted_message_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to save message") from e

    return MessageResponse(success=True, filename=filename, word_count=word_count)
