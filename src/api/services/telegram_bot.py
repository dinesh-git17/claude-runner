"""Long-running Telegram bot that polls for messages and triggers wake sessions."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from api.services.chat_history import append_message
from api.services.image_optimizer import optimize_image
from api.services.telegram import TelegramClient, TelegramMessage

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


async def _download_and_optimize(
    client: TelegramClient,
    message: TelegramMessage,
    sender: str,
) -> Path | None:
    """Download the largest photo from a message and optimize it.

    Args:
        client: Telegram API client.
        message: Telegram message containing photos.
        sender: Name of the sender.

    Returns:
        Path to the optimized image, or None on failure.
    """
    if not message.photo:
        return None

    largest = max(message.photo, key=lambda p: p.width * p.height)
    file_path = await client.get_file_path(largest.file_id)
    if not file_path:
        logger.warning("telegram_photo_get_file_failed", file_id=largest.file_id)
        return None

    raw_bytes = await client.download_file(file_path)
    if not raw_bytes:
        logger.warning("telegram_photo_download_failed", path=file_path)
        return None

    try:
        optimized_path = optimize_image(raw_bytes, sender)
        logger.info(
            "telegram_photo_saved",
            sender=sender,
            path=str(optimized_path),
            original_size=len(raw_bytes),
        )
        return optimized_path
    except Exception as exc:
        logger.error("telegram_photo_optimize_failed", error=str(exc))
        return None


def _build_wake_message(
    text: str | None,
    caption: str | None,
    image_path: Path | None,
) -> str | None:
    """Build the message string passed to wake.sh.

    Args:
        text: Plain text message (mutually exclusive with photo).
        caption: Photo caption.
        image_path: Path to optimized image on disk.

    Returns:
        Formatted message string, or None if nothing to send.
    """
    if image_path:
        prefix = f"[image:{image_path}]"
        if caption:
            return f"{prefix} {caption}"
        return prefix

    return text


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

                if update.message is None:
                    continue

                msg = update.message
                has_text = msg.text is not None
                has_photo = msg.photo is not None and len(msg.photo) > 0
                if not has_text and not has_photo:
                    continue

                sender_chat_id = str(msg.chat.id)
                sender_name = settings.resolve_sender(sender_chat_id)

                if sender_name is None:
                    logger.warning(
                        "telegram_unauthorized",
                        chat_id=sender_chat_id,
                    )
                    continue

                logger.info(
                    "telegram_message_received",
                    sender=sender_name,
                    has_text=has_text,
                    has_photo=has_photo,
                )

                image_path: Path | None = None
                if has_photo:
                    image_path = await _download_and_optimize(client, msg, sender_name)

                history_text = msg.text or msg.caption or "(sent an image)"
                append_message(settings.history_path, sender_name, history_text)

                wake_message = _build_wake_message(msg.text, msg.caption, image_path)
                if not wake_message:
                    continue

                typing_task = asyncio.create_task(_typing_loop(client, sender_chat_id))

                try:
                    response = await _run_wake_session(wake_message, sender_name)
                    append_message(settings.history_path, "claudie", response)
                    await client.send_message(sender_chat_id, response)
                except Exception as exc:
                    error_msg = f"Session failed: {exc}"
                    logger.error("telegram_session_failed", error=str(exc))
                    await client.send_message(sender_chat_id, error_msg)
                finally:
                    typing_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await typing_task

    except asyncio.CancelledError:
        logger.info("telegram_bot_stopping")
    finally:
        await client.close()
        logger.info("telegram_bot_stopped")


async def _run_wake_session(message: str, sender: str) -> str:
    """Spawn wake.sh for a telegram session and extract the response.

    Args:
        message: The user's Telegram message (may contain [image:] prefix).
        sender: Name of the sender (e.g. "dinesh", "carolina").

    Returns:
        The response text from the conversation file.

    Raises:
        RuntimeError: If wake.sh exits with a non-zero code.
    """
    cmd = [str(WAKE_SCRIPT), "telegram", message, sender]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    exit_code = await process.wait()

    if exit_code != 0:
        err_msg = f"wake.sh exited with code {exit_code}"
        raise RuntimeError(err_msg)

    return _extract_response(CONVERSATIONS_DIR)
