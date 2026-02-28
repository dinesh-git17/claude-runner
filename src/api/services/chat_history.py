"""JSONL read/write for Telegram chat history."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class ChatMessage(BaseModel):
    """A single chat history entry."""

    timestamp: str
    sender: str
    text: str


def append_message(history_path: Path, sender: str, text: str) -> None:
    """Append a message to the JSONL chat history file.

    Creates parent directories if they don't exist.

    Args:
        history_path: Path to the JSONL file.
        sender: Message sender ("dinesh" or "claudie").
        text: Message content.
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "from": sender,
        "text": text,
    }

    try:
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        logger.error("chat_history_write_failed", error=str(exc))


def read_recent(history_path: Path, count: int = 20) -> list[ChatMessage]:
    """Read the most recent messages from chat history.

    Args:
        history_path: Path to the JSONL file.
        count: Maximum number of messages to return.

    Returns:
        List of ChatMessage in chronological order (oldest first).
    """
    if not history_path.exists():
        return []

    try:
        lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    except OSError as exc:
        logger.error("chat_history_read_failed", error=str(exc))
        return []

    tail = lines[-count:] if len(lines) > count else lines
    messages: list[ChatMessage] = []

    for line in tail:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            messages.append(
                ChatMessage(
                    timestamp=data.get("timestamp", ""),
                    sender=data.get("from", "unknown"),
                    text=data.get("text", ""),
                )
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.debug("chat_history_parse_skip", error=str(exc))

    return messages
