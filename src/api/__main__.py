"""Entry point for the API server."""

import asyncio
import contextlib
import signal
import sys

import structlog
import uvicorn

from api.app import create_app
from api.config import Settings
from api.lifecycle import GracefulShutdown
from api.logging import configure_logging

logger = structlog.get_logger()


async def agent_loop(shutdown: GracefulShutdown) -> None:
    """Placeholder for future agent task execution.

    Runs concurrently with the HTTP server and exits gracefully
    when shutdown is triggered.

    Args:
        shutdown: Shutdown coordinator instance.
    """
    logger.info("agent_loop_started")
    while not shutdown.is_triggered:
        await asyncio.sleep(5.0)
    logger.info("agent_loop_stopped")


async def serve(settings: Settings) -> None:
    """Run uvicorn server with graceful shutdown support.

    Starts the FastAPI application and agent loop concurrently.
    Handles SIGTERM/SIGINT for clean shutdown.

    Args:
        settings: Server configuration.
    """
    app = create_app(settings)
    shutdown = GracefulShutdown(timeout=settings.shutdown_timeout)

    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.trigger)

    async def shutdown_server() -> None:
        """Wait for shutdown signal and stop server."""
        await shutdown.wait_for_trigger()
        server.should_exit = True

    await asyncio.gather(
        server.serve(),
        agent_loop(shutdown),
        shutdown_server(),
        return_exceptions=True,
    )


def main() -> None:
    """Entry point for python -m api."""
    settings = Settings()
    configure_logging(debug=settings.debug)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(settings))

    sys.exit(0)


if __name__ == "__main__":
    main()
