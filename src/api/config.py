"""API configuration loaded from environment variables."""
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
    watch_paths_raw: str = "/claude-home/thoughts,/claude-home/dreams"

    @computed_field
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

    @computed_field
    @property
    def watch_paths(self) -> list[str]:
        """Parse watch paths from comma-separated string.

        Returns:
            List of directory paths to watch for filesystem events.
        """
        return [
            path.strip()
            for path in self.watch_paths_raw.split(",")
            if path.strip()
        ]
