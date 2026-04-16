"""Graceful shutdown coordinator for async tasks."""
import asyncio

import structlog

logger = structlog.get_logger()


class GracefulShutdown:
    """Coordinates graceful shutdown across async tasks.

    This class provides a mechanism for signaling shutdown to multiple
    concurrent tasks and waiting for them to complete within a timeout.

    Attributes:
        is_triggered: Whether shutdown has been triggered.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        """Initialize shutdown coordinator.

        Args:
            timeout: Default seconds to wait for shutdown completion.
        """
        self._triggered = False
        self._event = asyncio.Event()
        self._timeout = timeout

    @property
    def is_triggered(self) -> bool:
        """Check if shutdown has been triggered.

        Returns:
            True if shutdown signal received.
        """
        return self._triggered

    def trigger(self) -> None:
        """Signal all waiting tasks to begin shutdown.

        Idempotent - calling multiple times has no additional effect.
        """
        if self._triggered:
            return
        logger.info("shutdown_triggered")
        self._triggered = True
        self._event.set()

    async def wait_for_trigger(self) -> None:
        """Wait indefinitely for shutdown signal.

        Blocks until trigger() is called from another task or signal handler.
        """
        await self._event.wait()

    async def wait(self, timeout: float | None = None) -> bool:
        """Wait for shutdown completion with optional timeout.

        Use after shutdown is triggered to allow in-flight work to complete.

        Args:
            timeout: Seconds to wait, uses default if None.

        Returns:
            True if completed within timeout, False if timeout exceeded.
        """
        t = timeout if timeout is not None else self._timeout
        try:
            await asyncio.wait_for(self._event.wait(), timeout=t)
            return True
        except asyncio.TimeoutError:
            logger.warning("shutdown_timeout", timeout_seconds=t)
            return False
