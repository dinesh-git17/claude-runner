#!/usr/bin/env python3
"""Send a Telegram message from Claudie to Dinesh.

Standalone CLI using only stdlib so it works with system Python
(no venv activation needed).

Usage:
    python3 /claude-home/runner/telegram_send.py "your message"
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ENV_FILE = Path("/claude-home/runner/.env")
HISTORY_FILE = Path("/claude-home/telegram/chat-history.jsonl")
TELEGRAM_API = "https://api.telegram.org/bot"
MAX_MESSAGE_LENGTH = 4096


def load_env(env_path: Path) -> dict[str, str]:
    """Parse key=value pairs from a .env file.

    Args:
        env_path: Path to the .env file.

    Returns:
        Dictionary of environment variable names to values.
    """
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")

    return values


def split_message(text: str) -> list[str]:
    """Split text into chunks within Telegram's message limit.

    Args:
        text: Full message text.

    Returns:
        List of chunks, each within MAX_MESSAGE_LENGTH.
    """
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= MAX_MESSAGE_LENGTH:
            chunks.append(remaining)
            break

        split_pos = remaining.rfind("\n", 0, MAX_MESSAGE_LENGTH)
        if split_pos == -1:
            split_pos = MAX_MESSAGE_LENGTH

        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip("\n")

    return chunks


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Send a single message via Telegram Bot API.

    Args:
        token: Bot API token.
        chat_id: Target chat ID.
        text: Message text.

    Returns:
        True on success.
    """
    url = f"{TELEGRAM_API}{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok"))
    except Exception as exc:
        sys.stderr.write(f"Send failed: {exc}\n")
        return False


def append_history(text: str) -> None:
    """Append a claudie message to chat history.

    Args:
        text: Message text sent.
    """
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "from": "claudie",
        "text": text,
    }

    try:
        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        sys.stderr.write(f"History write failed: {exc}\n")


def main() -> None:
    """Entry point: parse args, send message, log to history."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: telegram_send.py <message>\n")
        sys.exit(1)

    message = " ".join(sys.argv[1:])

    env = load_env(ENV_FILE)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        sys.stderr.write("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env\n")
        sys.exit(1)

    chunks = split_message(message)
    all_ok = True

    for chunk in chunks:
        if not send_telegram(token, chat_id, chunk):
            all_ok = False

    if all_ok:
        append_history(message)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
