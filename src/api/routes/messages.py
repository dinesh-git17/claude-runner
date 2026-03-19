"""Trusted user message endpoint with API key authentication."""

import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from api.routes.mailbox import (
    append_to_thread,
    generate_message_id,
    load_accounts,
)
from api.services.attachments import store_attachment, validate_image
from api.services.moderator import log_moderation, moderate_message

logger = structlog.get_logger()

router = APIRouter(prefix="/messages", tags=["messages"])

VISITORS_DIR = Path("/claude-home/visitors")
RATE_LIMIT_FILE = Path("/claude-home/data/api-rate-limits.json")
MAX_WORDS = 1500
MAX_NAME_LENGTH = 50
COOLDOWN_MINUTES = 15
DAILY_MESSAGE_CAP = 10


def get_trusted_keys() -> set[str]:
    """Load trusted API keys from environment."""
    raw = os.getenv("TRUSTED_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def load_rate_limits() -> dict[str, list[str]]:
    """Load rate limit timestamp lists from file."""
    if not RATE_LIMIT_FILE.exists():
        return {}
    try:
        data = json.loads(RATE_LIMIT_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    migrated: dict[str, list[str]] = {}
    for key, value in data.items():
        if isinstance(value, str):
            migrated[key] = [value]
        elif isinstance(value, list):
            migrated[key] = [str(v) for v in value]
        else:
            migrated[key] = []
    return migrated


def save_rate_limits(limits: dict[str, list[str]]) -> None:
    """Save rate limit timestamp lists to file."""
    RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RATE_LIMIT_FILE.write_text(json.dumps(limits, indent=2))


def check_rate_limit(token: str) -> tuple[bool, str | None]:
    """Check cooldown and daily cap for a token.

    Returns:
        Tuple of (is_allowed, human-readable reason or None).
    """
    limits = load_rate_limits()
    timestamps = limits.get(token, [])

    if not timestamps:
        return True, None

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        last_time = datetime.fromisoformat(timestamps[-1])
    except ValueError:
        return True, None

    cooldown_end = last_time + timedelta(minutes=COOLDOWN_MINUTES)
    if now < cooldown_end:
        remaining = int((cooldown_end - now).total_seconds())
        minutes = remaining // 60
        seconds = remaining % 60
        return False, f"Cooldown active. Try again in {minutes}m {seconds}s"

    today_count = 0
    for ts in timestamps:
        try:
            if datetime.fromisoformat(ts) >= today_start:
                today_count += 1
        except ValueError:
            continue

    if today_count >= DAILY_MESSAGE_CAP:
        return (
            False,
            f"Daily limit of {DAILY_MESSAGE_CAP} messages reached. Resets at midnight.",
        )

    return True, None


def record_usage(token: str) -> None:
    """Append a timestamp for the token and prune entries older than 24 hours."""
    limits = load_rate_limits()
    timestamps = limits.get(token, [])
    now = datetime.now()
    cutoff = now - timedelta(hours=24)
    pruned: list[str] = []
    for ts in timestamps:
        try:
            if datetime.fromisoformat(ts) >= cutoff:
                pruned.append(ts)
        except ValueError:
            continue
    pruned.append(now.isoformat())
    limits[token] = pruned
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


class AttachmentInfo(BaseModel):
    """Attachment metadata."""

    filename: str
    mime: str
    size: int


class MessageResponse(BaseModel):
    """Response after saving message."""

    success: bool
    filename: str
    word_count: int
    attachment: AttachmentInfo | None = None


def _route_to_mailbox(token: str, name: str, message: str) -> str | None:
    """Route message to mailbox thread if the sender is registered.

    Returns the message ID if routed to mailbox, None if should go to visitors.
    """
    accounts = load_accounts()
    acct = accounts.get(token)
    if acct is None:
        return None

    username = str(acct["username"])
    msg_id = generate_message_id(username, "u")
    now = datetime.now(tz=UTC).isoformat()

    message_obj: dict[str, object] = {
        "id": msg_id,
        "from": username,
        "ts": now,
        "body": message,
    }
    append_to_thread(username, message_obj)

    logger.info(
        "mailbox_message_sent",
        username=username,
        message_id=msg_id,
        word_count=len(message.split()),
    )
    return msg_id


@router.post("", response_model=MessageResponse)
async def send_message(
    msg: TrustedMessage,
    authorization: str = Header(..., description="Bearer token"),
) -> MessageResponse:
    """Save a message from a trusted user.

    Requires a valid API key in the Authorization header.
    Messages are limited to 1500 words, 10 per day, with a 15-minute cooldown.
    If the sender is registered for mailbox, the message is appended to their
    thread.jsonl instead of saving to visitors/.
    """
    token = authorization.removeprefix("Bearer ").strip()
    trusted_keys = get_trusted_keys()

    if not trusted_keys:
        logger.error("no_trusted_keys_configured")
        raise HTTPException(status_code=500, detail="API keys not configured")

    if token not in trusted_keys:
        logger.warning(
            "invalid_api_key_attempt",
            token_prefix=token[:8] if token else "",
        )
        raise HTTPException(status_code=401, detail="Invalid API key")

    is_allowed, reason = check_rate_limit(token)
    if not is_allowed:
        logger.warning("rate_limit_exceeded", token_prefix=token[:8])
        raise HTTPException(status_code=429, detail=reason)

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

    mailbox_msg_id = _route_to_mailbox(token, msg.name, msg.message)

    if mailbox_msg_id is not None:
        record_usage(token)
        return MessageResponse(
            success=True, filename=mailbox_msg_id, word_count=word_count
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


@router.post("/with-image", response_model=MessageResponse)
async def send_message_with_image(
    authorization: str = Header(..., description="Bearer API key"),
    name: str = Form(..., min_length=1, max_length=MAX_NAME_LENGTH),
    message: str = Form(default=""),
    image: UploadFile = File(...),  # noqa: B008
) -> MessageResponse:
    """Send a message with an image attachment.

    Requires a valid trusted API key AND a registered mailbox account.
    Image is stored in the sender's mailbox attachments directory.
    """
    token = authorization.removeprefix("Bearer ").strip()
    trusted_keys = get_trusted_keys()

    if not trusted_keys:
        logger.error("no_trusted_keys_configured")
        raise HTTPException(status_code=500, detail="API keys not configured")

    if token not in trusted_keys:
        logger.warning(
            "invalid_api_key_attempt",
            token_prefix=token[:8] if token else "",
        )
        raise HTTPException(status_code=401, detail="Invalid API key")

    accounts = load_accounts()
    acct = accounts.get(token)
    if acct is None:
        raise HTTPException(
            status_code=403,
            detail="Image sending requires a registered mailbox account",
        )

    username = str(acct["username"])

    is_allowed, reason = check_rate_limit(token)
    if not is_allowed:
        logger.warning("rate_limit_exceeded", token_prefix=token[:8])
        raise HTTPException(status_code=429, detail=reason)

    word_count = len(message.split()) if message else 0
    if word_count > MAX_WORDS:
        raise HTTPException(
            status_code=400,
            detail=f"Message exceeds {MAX_WORDS} words (submitted: {word_count})",
        )

    if message:
        safe_name = re.sub(r"[^a-zA-Z0-9\s\-]", "", name).strip()
        moderation = await moderate_message(message, safe_name)
        log_moderation(safe_name, message, moderation, source="api")
        if not moderation.allowed:
            raise HTTPException(
                status_code=400, detail="Message could not be accepted."
            )

    image_data = await image.read()
    try:
        _fmt, ext, mime = validate_image(image_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    msg_id = generate_message_id(username, "u")
    attachment_filename = store_attachment(username, msg_id, image_data, ext)

    now = datetime.now(tz=UTC).isoformat()
    message_obj: dict[str, object] = {
        "id": msg_id,
        "from": username,
        "ts": now,
        "body": message,
        "attachment": {
            "filename": attachment_filename,
            "mime": mime,
            "size": len(image_data),
        },
    }
    append_to_thread(username, message_obj)
    record_usage(token)

    logger.info(
        "mailbox_image_message_sent",
        username=username,
        message_id=msg_id,
        word_count=word_count,
        image_size=len(image_data),
        image_format=_fmt,
    )

    return MessageResponse(
        success=True,
        filename=msg_id,
        word_count=word_count,
        attachment=AttachmentInfo(
            filename=attachment_filename,
            mime=mime,
            size=len(image_data),
        ),
    )
