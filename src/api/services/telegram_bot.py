"""Long-running Telegram bot that polls for messages and triggers wake sessions."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from api.services.chat_history import append_message
from api.services.telegram import TelegramClient

if TYPE_CHECKING:
    from api.config import TelegramSettings

logger = structlog.get_logger()

WAKE_SCRIPT = Path("/claude-home/runner/wake.sh")
CONVERSATIONS_DIR = Path("/claude-home/conversations")
TYPING_INTERVAL_SECONDS = 4.0


async def _typing_loop(client: TelegramClient, chat_id: str) -> None:
    """Send typing indicators every few seconds until cancelled.

    Args:
        client: Telegram API client.
        chat_id: Target chat ID.
    """
    while True:
        await client.send_typing(chat_id)
        await asyncio.sleep(TYPING_INTERVAL_SECONDS)


def _extract_response(conversations_dir: Path) -> str:
    """Extract the response from the most recently modified conversation file.

    Scans for the ``## Response`` section in the newest .md file.

    Args:
        conversations_dir: Path to the conversations directory.

    Returns:
        Extracted response text, or a fallback message.
    """
    if not conversations_dir.exists():
        return "(No conversation file found)"

    md_files = sorted(
        conversations_dir.glob("*.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not md_files:
        return "(No conversation file found)"

    try:
        content = md_files[0].read_text(encoding="utf-8")
    except OSError:
        return "(Could not read conversation file)"

    in_response = False
    response_lines: list[str] = []

    for line in content.split("\n"):
        if line.strip() == "## Response":
            in_response = True
            continue
        if in_response:
            response_lines.append(line)

    response = "\n".join(response_lines).strip()
    return response if response else "(Session completed but no response captured)"


async def run_telegram_bot(settings: TelegramSettings) -> None:
    """Main polling loop for the Telegram bot.

    Processes messages sequentially — one at a time. Queued messages
    wait in Telegram's server until the current one finishes.

    Args:
        settings: Telegram configuration with credentials and paths.
    """
    if not settings.enabled:
        return

    client = TelegramClient(settings.bot_token)
    offset: int | None = None

    logger.info("telegram_bot_started")

    try:
        while True:
            updates = await client.get_updates(
                offset=offset,
                timeout=settings.poll_timeout,
            )

            for update in updates:
                offset = update.update_id + 1

                if update.message is None or update.message.text is None:
                    continue

                sender_chat_id = str(update.message.chat.id)

                if sender_chat_id != settings.chat_id:
                    logger.warning(
                        "telegram_unauthorized",
                        chat_id=sender_chat_id,
                    )
                    continue

                text = update.message.text
                logger.info("telegram_message_received", length=len(text))

                append_message(settings.history_path, "dinesh", text)

                typing_task = asyncio.create_task(
                    _typing_loop(client, settings.chat_id)
                )

                try:
                    response = await _run_wake_session(text)
                    append_message(settings.history_path, "claudie", response)
                    await client.send_message(settings.chat_id, response)
                except Exception as exc:
                    error_msg = f"Session failed: {exc}"
                    logger.error("telegram_session_failed", error=str(exc))
                    await client.send_message(settings.chat_id, error_msg)
                finally:
                    typing_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await typing_task

    except asyncio.CancelledError:
        logger.info("telegram_bot_stopping")
    finally:
        await client.close()
        logger.info("telegram_bot_stopped")


async def _run_wake_session(message: str) -> str:
    """Spawn wake.sh for a telegram session and extract the response.

    Args:
        message: The user's Telegram message.

    Returns:
        The response text from the conversation file.

    Raises:
        RuntimeError: If wake.sh exits with a non-zero code.
    """
    cmd = [str(WAKE_SCRIPT), "telegram", message]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    exit_code = await process.wait()

    if exit_code != 0:
        msg = f"wake.sh exited with code {exit_code}"
        raise RuntimeError(msg)

    return _extract_response(CONVERSATIONS_DIR)
