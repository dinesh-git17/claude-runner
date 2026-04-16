"""Async HTTP client wrapping the Telegram Bot API."""

from __future__ import annotations

import httpx
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

BASE_URL = "https://api.telegram.org/bot"
FILE_URL = "https://api.telegram.org/file/bot"
MAX_MESSAGE_LENGTH = 4096
REQUEST_TIMEOUT = 40.0


class TelegramChat(BaseModel):
    """Telegram chat object."""

    id: int


class TelegramPhoto(BaseModel):
    """Telegram PhotoSize object."""

    file_id: str
    file_unique_id: str
    width: int
    height: int
    file_size: int | None = None


class TelegramMessage(BaseModel):
    """Telegram message object."""

    message_id: int
    chat: TelegramChat
    text: str | None = None
    photo: list[TelegramPhoto] | None = None
    caption: str | None = None


class TelegramUpdate(BaseModel):
    """Telegram update object from getUpdates."""

    update_id: int
    message: TelegramMessage | None = None


def _split_message(text: str) -> list[str]:
    """Split text into chunks that fit within Telegram's message limit.

    Splits on newline boundaries when possible, falling back to
    hard truncation at MAX_MESSAGE_LENGTH.

    Args:
        text: The full message text.

    Returns:
        List of message chunks, each within MAX_MESSAGE_LENGTH.
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


class TelegramClient:
    """Async client for Telegram Bot API operations.

    Args:
        token: Bot API token from BotFather.
    """

    def __init__(self, token: str) -> None:
        self._base = f"{BASE_URL}{token}"
        self._file_base = f"{FILE_URL}{token}"
        self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    async def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 30,
    ) -> list[TelegramUpdate]:
        """Long-poll for new updates from Telegram.

        Args:
            offset: Update ID offset for acknowledgment.
            timeout: Long-poll timeout in seconds.

        Returns:
            List of new updates. Empty list on error.
        """
        params: dict[str, int] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset

        try:
            resp = await self._client.get(
                f"{self._base}/getUpdates",
                params=params,
                timeout=timeout + 10,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning("telegram_get_updates_failed", response=data)
                return []
            return [TelegramUpdate.model_validate(u) for u in data.get("result", [])]
        except Exception as exc:
            logger.warning("telegram_get_updates_error", error=str(exc))
            return []

    async def get_file_path(self, file_id: str) -> str | None:
        """Get the file path for a Telegram file ID via getFile.

        Args:
            file_id: Telegram file identifier.

        Returns:
            Server-side file path, or None on failure.
        """
        try:
            resp = await self._client.get(
                f"{self._base}/getFile",
                params={"file_id": file_id},
            )
            data = resp.json()
            if data.get("ok"):
                return data["result"].get("file_path")
            logger.warning("telegram_get_file_failed", response=data)
            return None
        except Exception as exc:
            logger.warning("telegram_get_file_error", error=str(exc))
            return None

    async def download_file(self, file_path: str) -> bytes | None:
        """Download a file from Telegram's servers.

        Args:
            file_path: Server-side file path from getFile.

        Returns:
            Raw file bytes, or None on failure.
        """
        try:
            resp = await self._client.get(
                f"{self._file_base}/{file_path}",
                timeout=60.0,
            )
            if resp.status_code == 200:
                return resp.content
            logger.warning(
                "telegram_download_failed",
                status=resp.status_code,
                path=file_path,
            )
            return None
        except Exception as exc:
            logger.warning("telegram_download_error", error=str(exc))
            return None

    async def send_message(self, chat_id: str, text: str) -> bool:
        """Send a text message, splitting if it exceeds 4096 chars.

        Attempts Markdown parse mode first; falls back to plaintext
        on parse failure.

        Args:
            chat_id: Target chat ID.
            text: Message text.

        Returns:
            True if all chunks sent successfully.
        """
        chunks = _split_message(text)
        all_ok = True

        for chunk in chunks:
            if not await self._send_single(chat_id, chunk):
                all_ok = False

        return all_ok

    async def _send_single(self, chat_id: str, text: str) -> bool:
        """Send a single message chunk.

        Args:
            chat_id: Target chat ID.
            text: Message text (must be within MAX_MESSAGE_LENGTH).

        Returns:
            True on success.
        """
        payload: dict[str, str] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

        try:
            resp = await self._client.post(
                f"{self._base}/sendMessage",
                json=payload,
            )
            data = resp.json()
            if data.get("ok"):
                return True

            # Markdown parse failure — retry as plaintext
            if data.get("error_code") == 400:
                logger.debug("telegram_markdown_fallback", chat_id=chat_id)
                payload.pop("parse_mode")
                resp = await self._client.post(
                    f"{self._base}/sendMessage",
                    json=payload,
                )
                return bool(resp.json().get("ok"))

            logger.warning("telegram_send_failed", response=data)
            return False
        except Exception as exc:
            logger.warning("telegram_send_error", error=str(exc))
            return False

    async def send_typing(self, chat_id: str) -> None:
        """Send a typing chat action indicator.

        Args:
            chat_id: Target chat ID.
        """
        try:
            await self._client.post(
                f"{self._base}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
            )
        except Exception as exc:
            logger.debug("telegram_typing_error", error=str(exc))

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
