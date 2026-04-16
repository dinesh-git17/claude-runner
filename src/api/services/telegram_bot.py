"""Long-running Telegram bot that polls for messages and triggers wake sessions."""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from api.services.chat_history import append_message
from api.services.image_optimizer import optimize_image
from api.services.telegram import TelegramClient, TelegramMessage
from orchestrator import telegram_talk
from orchestrator.config import TELEGRAM_TALK_IDLE_EXPIRY_SECONDS
from orchestrator.lock import SessionAlreadyRunning

if TYPE_CHECKING:
    from api.config import TelegramSettings

logger = structlog.get_logger()

WAKE_SCRIPT = Path("/claude-home/runner/wake.sh")
CONVERSATIONS_DIR = Path("/claude-home/conversations")
SESSION_LOCK_FILE = Path("/run/claude-session.lock")
TALK_LOG_DIR = Path("/claude-home/logs")
TYPING_INTERVAL_SECONDS = 4.0
MAX_LOCK_WAIT_SECONDS = 600
LOCK_POLL_INTERVAL_SECONDS = 15.0


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


def _session_lock_held() -> bool:
    """Check whether the session lock is currently held by another process."""
    try:
        fd = os.open(str(SESSION_LOCK_FILE), os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


async def _wait_for_session_lock() -> bool:
    """Wait until the session lock is released.

    Returns:
        True if the lock was released within the timeout, False otherwise.
    """
    elapsed = 0.0
    while elapsed < MAX_LOCK_WAIT_SECONDS:
        if not _session_lock_held():
            return True
        logger.info(
            "telegram_waiting_for_lock",
            elapsed_seconds=int(elapsed),
            max_seconds=MAX_LOCK_WAIT_SECONDS,
        )
        await asyncio.sleep(LOCK_POLL_INTERVAL_SECONDS)
        elapsed += LOCK_POLL_INTERVAL_SECONDS
    return False


async def run_telegram_bot(settings: TelegramSettings) -> None:
    """Main polling loop for the Telegram bot.

    Processes messages sequentially — one at a time. Queued messages
    wait in Telegram's server until the current one finishes.

    Args:
        settings: Telegram configuration with credentials and paths.
    """
    if not settings.enabled:
        return

    _cleanup_stale_talk_state()

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

                # ------------------------------------------------------
                # /talk command routing (text-only, no photos)
                # ------------------------------------------------------
                text_cmd = (msg.text or "").strip() if has_text else ""

                if has_text and not has_photo:
                    if text_cmd in ("/end-talk", "/endtalk", "/end_talk"):
                        await _handle_end_talk(client, sender_chat_id)
                        continue

                    if text_cmd == "/talk":
                        await _handle_talk_open(
                            client, settings, sender_chat_id, sender_name
                        )
                        continue

                    # Mid-talk turn: the chat that opened the talk owns it.
                    talk_state = telegram_talk.load_state()
                    if (
                        talk_state is not None
                        and talk_state.get("chat_id") == sender_chat_id
                    ):
                        expired, age = _is_talk_expired(talk_state)
                        if expired:
                            logger.info(
                                "telegram_talk_expired_on_message",
                                age_seconds=age,
                            )
                            telegram_talk.clear_state()
                            await client.send_message(
                                sender_chat_id,
                                f"Talk expired ({age // 60} min idle). "
                                "Sending as a cold message instead…",
                            )
                            # fall through to the cold-wake path below
                        else:
                            await _handle_talk_turn(
                                client,
                                settings,
                                sender_chat_id,
                                sender_name,
                                text_cmd,
                                talk_state.get("session_id", ""),
                            )
                            continue

                # ------------------------------------------------------
                # Cold wake path (default): photos, non-talk text,
                # expired-talk fall-through
                # ------------------------------------------------------
                image_path: Path | None = None
                if has_photo:
                    image_path = await _download_and_optimize(
                        client, msg, sender_name
                    )

                history_text = msg.text or msg.caption or "(sent an image)"
                append_message(settings.history_path, sender_name, history_text)

                wake_message = _build_wake_message(
                    msg.text, msg.caption, image_path
                )
                if not wake_message:
                    continue

                typing_task = asyncio.create_task(
                    _typing_loop(client, sender_chat_id)
                )

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


async def _spawn_wake(
    cmd: list[str], env: dict[str, str] | None = None
) -> tuple[int, str]:
    """Spawn wake.sh and return (exit_code, captured_output).

    stdout and stderr are merged and captured so we can log them
    on failure for diagnosis.
    """
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    stdout_bytes, _ = await process.communicate()
    output = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    return process.returncode or 0, output


async def _run_wake_session(message: str, sender: str) -> str:
    """Spawn wake.sh for a telegram session and extract the response.

    If the session lock is held by another session, waits for it to
    clear and retries once.

    Args:
        message: The user's Telegram message (may contain [image:] prefix).
        sender: Name of the sender (e.g. "dinesh", "carolina").

    Returns:
        The response text from the conversation file.

    Raises:
        RuntimeError: If wake.sh exits with a non-zero code.
    """
    cmd = [str(WAKE_SCRIPT), "telegram", message, sender]

    exit_code, output = await _spawn_wake(cmd)

    if exit_code != 0 and _session_lock_held():
        logger.info("telegram_session_queued", reason="session lock held")
        lock_released = await _wait_for_session_lock()
        if not lock_released:
            msg = "timed out waiting for active session to finish"
            raise RuntimeError(msg)

        exit_code, output = await _spawn_wake(cmd)

    if exit_code != 0:
        logger.error(
            "telegram_wake_failed_output",
            exit_code=exit_code,
            output_tail=output[-6000:],
        )
        msg = f"wake.sh exited with code {exit_code}"
        raise RuntimeError(msg)

    return _extract_response(CONVERSATIONS_DIR)


async def _run_telegram_talk_open(sender: str, chat_id: str) -> dict:
    """Spawn wake.sh telegram_talk_open, wait for completion, return state.

    Retries once on session lock contention. Raises RuntimeError on failure.
    """
    cmd = [str(WAKE_SCRIPT), "telegram_talk_open", "", sender]
    env = os.environ.copy()
    env["TELEGRAM_TALK_CHAT_ID"] = chat_id

    exit_code, output = await _spawn_wake(cmd, env=env)

    if exit_code != 0 and _session_lock_held():
        logger.info("telegram_talk_open_queued", reason="session lock held")
        lock_released = await _wait_for_session_lock()
        if not lock_released:
            msg = "timed out waiting for active session to finish"
            raise RuntimeError(msg)
        exit_code, output = await _spawn_wake(cmd, env=env)

    if exit_code != 0:
        logger.error(
            "telegram_talk_open_failed",
            exit_code=exit_code,
            output_tail=output[-6000:],
        )
        msg = f"wake.sh telegram_talk_open exited with code {exit_code}"
        raise RuntimeError(msg)

    state = telegram_talk.load_state()
    if state is None:
        msg = "talk_open completed but state file not written"
        raise RuntimeError(msg)
    return state


async def _handle_talk_open(
    client: TelegramClient,
    settings: TelegramSettings,
    chat_id: str,
    sender: str,
) -> None:
    """Handle /talk command: spawn a telegram_talk_open wake and reply."""
    existing = telegram_talk.load_state()
    if existing is not None:
        owner = existing.get("sender", "someone")
        await client.send_message(
            chat_id,
            f"Talk already active (opened by {owner}). "
            "Use /end-talk to close the current one first.",
        )
        return

    typing_task = asyncio.create_task(_typing_loop(client, chat_id))
    try:
        state = await _run_telegram_talk_open(sender, chat_id)
        greeting = state.get("greeting") or "(no greeting captured)"
        append_message(settings.history_path, "claudie", greeting)
        await client.send_message(chat_id, greeting)
    except Exception as exc:
        logger.error("telegram_talk_open_error", error=str(exc))
        telegram_talk.clear_state()
        await client.send_message(chat_id, f"Failed to open talk: {exc}")
    finally:
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task


async def _handle_talk_turn(
    client: TelegramClient,
    settings: TelegramSettings,
    chat_id: str,
    sender: str,
    message: str,
    session_id: str,
) -> None:
    """Handle a mid-talk message: run one --resume turn and reply."""
    append_message(settings.history_path, sender, message)
    typing_task = asyncio.create_task(_typing_loop(client, chat_id))
    try:
        try:
            reply = await telegram_talk.run_turn(session_id, message)
        except SessionAlreadyRunning:
            logger.info("telegram_talk_turn_queued", reason="session lock held")
            lock_released = await _wait_for_session_lock()
            if not lock_released:
                raise RuntimeError("timed out waiting for session lock") from None
            reply = await telegram_talk.run_turn(session_id, message)
        append_message(settings.history_path, "claudie", reply)
        await client.send_message(chat_id, reply)
    except Exception as exc:
        logger.error("telegram_talk_turn_error", error=str(exc))
        telegram_talk.clear_state()
        await client.send_message(
            chat_id,
            f"Talk session lost: {exc}. Send /talk to start a fresh one.",
        )
    finally:
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task


async def _handle_end_talk(
    client: TelegramClient,
    chat_id: str,
) -> None:
    """Handle /end-talk command: run close pipeline and reply."""
    state = telegram_talk.load_state()
    if state is None:
        await client.send_message(chat_id, "No active talk session.")
        return

    owner_chat_id = state.get("chat_id", "")
    if owner_chat_id and owner_chat_id != chat_id:
        await client.send_message(
            chat_id,
            "That talk was opened from a different chat. Only its owner can close it.",
        )
        return

    typing_task = asyncio.create_task(_typing_loop(client, chat_id))
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_file = TALK_LOG_DIR / f"telegram-talk-close-{stamp}.log"
        try:
            await telegram_talk.close_session(log_file=log_file)
        except Exception as exc:
            logger.error("telegram_talk_close_pipeline_error", error=str(exc))
            telegram_talk.clear_state()
        await client.send_message(
            chat_id, "Talk ended. Back to cold mode — next message triggers a full wake."
        )
    finally:
        typing_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await typing_task


def _is_talk_expired(state: dict) -> tuple[bool, int]:
    """Return (expired, age_seconds) based on TELEGRAM_TALK_IDLE_EXPIRY_SECONDS."""
    last_str = state.get("last_turn_at") or state.get("started_at") or ""
    if not last_str:
        return True, 0
    try:
        last = datetime.fromisoformat(last_str)
    except ValueError:
        return True, 0
    now = datetime.now(last.tzinfo)
    age = (now - last).total_seconds()
    return age > TELEGRAM_TALK_IDLE_EXPIRY_SECONDS, int(age)


def _cleanup_stale_talk_state() -> None:
    """At bot startup, discard any talk state older than the idle expiry."""
    state = telegram_talk.load_state()
    if state is None:
        return
    expired, age = _is_talk_expired(state)
    if expired:
        logger.warning(
            "telegram_talk_stale_state_cleared",
            age_seconds=age,
            sender=state.get("sender", ""),
        )
        telegram_talk.clear_state()
