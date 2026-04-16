"""API configuration loaded from environment variables."""

from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API configuration loaded from environment variables.

    Attributes:
        host: Bind address for the API server.
        port: Port number for the API server.
        debug: Enable debug mode and API documentation.
        cors_origins_raw: Raw comma-separated CORS origins string.
        shutdown_timeout: Seconds to wait for graceful shutdown.
        key: API key for authenticating requests.
        event_debounce_ms: Debounce window for filesystem events.
        event_queue_size: Maximum size of each subscriber queue.
        event_max_subscribers: Maximum number of concurrent subscribers.
        sse_heartbeat_interval: Seconds between SSE heartbeat events.
        watch_paths_raw: Comma-separated paths to watch for changes.
    """

    model_config = SettingsConfigDict(
        env_prefix="API_",
        env_file="/claude-home/runner/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False
    cors_origins_raw: str = "https://claudehome.dineshd.dev"
    shutdown_timeout: float = 30.0
    key: str = ""

    event_debounce_ms: int = 50
    event_queue_size: int = 100
    event_max_subscribers: int = 100
    sse_heartbeat_interval: float = 15.0
    watch_paths_raw: str = (
        "/claude-home/thoughts,/claude-home/dreams,/claude-home/scores,/claude-home/mailbox"
    )

    # Live session streaming
    session_stream_path: str = "/claude-home/data/live-stream.jsonl"
    session_status_path: str = "/claude-home/data/session-status.json"
    session_poll_interval: float = 0.2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        """Parse CORS origins from comma-separated string.

        Returns:
            List of allowed origin URLs.
        """
        return [
            origin.strip()
            for origin in self.cors_origins_raw.split(",")
            if origin.strip()
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def watch_paths(self) -> list[str]:
        """Parse watch paths from comma-separated string.

        Returns:
            List of directory paths to watch for filesystem events.
        """
        return [
            path.strip() for path in self.watch_paths_raw.split(",") if path.strip()
        ]


class TelegramSettings(BaseSettings):
    """Telegram bot configuration loaded from environment variables.

    Attributes:
        bot_token: Telegram Bot API token from BotFather.
        chat_id: Authorized Telegram chat ID.
        history_path: Path to JSONL chat history file.
        poll_timeout: Long-poll timeout in seconds.
    """

    model_config = SettingsConfigDict(
        env_prefix="TELEGRAM_",
        env_file="/claude-home/runner/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: str = ""
    chat_id: str = ""
    history_path: Path = Path("/claude-home/telegram/chat-history.jsonl")
    poll_timeout: int = 30
    authorized_users_raw: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def authorized_users(self) -> dict[str, str]:
        """Parse authorized users from comma-separated name:chat_id pairs.

        Returns:
            Mapping of sender name to Telegram chat ID.
        """
        users: dict[str, str] = {}
        for entry in self.authorized_users_raw.split(","):
            entry = entry.strip()
            if ":" not in entry:
                continue
            name, _, chat_id = entry.partition(":")
            if name.strip() and chat_id.strip():
                users[name.strip()] = chat_id.strip()
        return users

    def resolve_sender(self, chat_id: str) -> str | None:
        """Look up sender name by chat ID.

        Args:
            chat_id: Telegram chat ID to resolve.

        Returns:
            Sender name if authorized, None otherwise.
        """
        for name, cid in self.authorized_users.items():
            if cid == chat_id:
                return name
        return None

    @property
    def enabled(self) -> bool:
        """Whether both required credentials are configured."""
        return bool(self.bot_token and self.chat_id)
