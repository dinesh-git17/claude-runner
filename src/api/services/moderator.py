"""Lightweight content moderation for trusted API messages.

Uses Claude 3 Haiku to screen for inappropriate (sexual/romantic)
content only. Fail-open: if the API call fails, the message is
allowed through since these are trusted users.
"""

import json
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    import anthropic

logger = structlog.get_logger()

MODEL = "claude-3-haiku-20240307"
MAX_TOKENS = 60
TIMEOUT = 10.0
MODERATION_DIR = Path("/claude-home/moderation")

SYSTEM_PROMPT = """You are a content filter. Your only job is to detect sexual, romantic, or explicit content in visitor messages.

BLOCK: sexual advances, romantic declarations, explicit material, or suggestive content directed at the recipient.
ALLOW: everything else — greetings, philosophical questions, criticism, casual conversation, even rude messages.

Output ONLY valid JSON:
{"allowed": boolean, "reason": "inappropriate" | "approved"}"""


class ModerationResult(BaseModel):
    """Result of content moderation check."""

    allowed: bool
    reason: str


ALLOW_RESULT = ModerationResult(allowed=True, reason="approved")


@lru_cache(maxsize=1)
def _client() -> "anthropic.Anthropic | None":
    """Lazy-initialize the Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic

        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


async def moderate_message(message: str, name: str) -> ModerationResult:
    """Screen a message for inappropriate content.

    Fail-open: returns allowed=True if the API call fails.

    Args:
        message: The message content to check.
        name: The sender's name.

    Returns:
        ModerationResult with allowed status and reason.
    """
    client = _client()
    if not client:
        logger.warning("moderation_skipped", reason="no_client")
        return ALLOW_RESULT

    user_content = f"Visitor '{name}' says: {message}"

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            timeout=TIMEOUT,
        )

        text_block = next((b for b in response.content if b.type == "text"), None)
        if not text_block:
            return ALLOW_RESULT

        json_match = None
        match = re.search(r"\{[\s\S]*\}", text_block.text)
        if match:
            json_match = match.group(0)

        if not json_match:
            return ALLOW_RESULT

        parsed = json.loads(json_match)
        allowed = parsed.get("allowed", True)
        reason = parsed.get("reason", "approved")

        if reason not in ("inappropriate", "approved"):
            reason = "approved" if allowed else "inappropriate"

        return ModerationResult(allowed=allowed, reason=reason)

    except Exception as e:
        logger.warning("moderation_error", error=str(e))
        return ALLOW_RESULT


def log_moderation(
    name: str,
    message: str,
    result: ModerationResult,
    source: str = "api",
) -> None:
    """Persist moderation result to disk.

    Args:
        name: Sender name.
        message: Message content (truncated to 80 chars).
        result: The moderation result.
        source: Origin of the message ("api" or "guestbook").
    """
    MODERATION_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    filename = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-api.json"
    filepath = MODERATION_DIR / filename

    log_data = {
        "timestamp": timestamp.isoformat(),
        "source": source,
        "name": name,
        "message_preview": message[:80],
        "allowed": result.allowed,
        "reason": result.reason,
    }

    try:
        filepath.write_text(json.dumps(log_data, indent=2))
        filepath.chmod(0o640)
        logger.info(
            "api_moderation_logged",
            filename=filename,
            allowed=result.allowed,
            reason=result.reason,
        )
    except OSError as e:
        logger.error("api_moderation_log_failed", error=str(e))
