"""SSE broadcast hub for streaming events to clients."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
from sse_starlette import ServerSentEvent
from watchdog.events import FileSystemEvent

from api.events.bus import EventBus
from api.events.normalizer import normalize_event
from api.events.types import DomainEvent, EventType

logger = structlog.get_logger()


class BroadcastHub:
    """SSE broadcast hub managing event distribution to clients.

    Bridges filesystem events to SSE clients through the event bus,
    handling event normalization and heartbeat generation.

    Attributes:
        heartbeat_interval: Seconds between heartbeat events.
    """

    def __init__(
        self,
        event_bus: EventBus,
        heartbeat_interval: float = 15.0,
    ) -> None:
        """Initialize broadcast hub.

        Args:
            event_bus: Event bus for pub/sub.
            heartbeat_interval: Seconds between heartbeats.
        """
        self._bus = event_bus
        self._heartbeat_interval = heartbeat_interval
        self._active_connections = 0
        self._lock = asyncio.Lock()

    @property
    def active_connections(self) -> int:
        """Number of active SSE connections."""
        return self._active_connections

    async def on_filesystem_event(self, raw_event: FileSystemEvent) -> None:
        """Handle raw filesystem event from watcher.

        Normalizes the event and publishes to the event bus.

        Args:
            raw_event: Raw watchdog filesystem event.
        """
        event = normalize_event(raw_event)
        if event is None:
            return

        delivered = await self._bus.publish(event)
        logger.debug(
            "event_published",
            event_type=event.type.value,
            topic=event.topic,
            path=event.path,
            delivered_to=delivered,
        )

    async def create_sse_generator(
        self,
        topic: str = "*",
    ) -> AsyncIterator[ServerSentEvent]:
        """Create SSE event generator for a client connection.

        Generates a stream of SSE events including filesystem events
        and periodic heartbeats.

        Args:
            topic: Topic filter for events.

        Yields:
            Server-sent events for the client.
        """
        subscriber_id, event_iter = await self._bus.subscribe(topic)

        async with self._lock:
            self._active_connections += 1

        logger.info(
            "sse_client_connected",
            subscriber_id=subscriber_id,
            topic=topic,
            active_connections=self._active_connections,
        )

        queue: asyncio.Queue[DomainEvent] = asyncio.Queue(maxsize=10)

        async def pump_events() -> None:
            async for event in event_iter:
                await queue.put(event)

        pump_task = asyncio.create_task(pump_events())

        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=self._heartbeat_interval,
                    )
                    yield ServerSentEvent(
                        event=event.type.value,
                        data=event.model_dump_json(),
                    )
                except TimeoutError:
                    heartbeat = DomainEvent(
                        id=str(uuid.uuid4()),
                        type=EventType.HEARTBEAT,
                        timestamp=datetime.now(UTC),
                        topic="system",
                    )
                    yield ServerSentEvent(
                        event=heartbeat.type.value,
                        data=heartbeat.model_dump_json(),
                    )
        except asyncio.CancelledError:
            pass
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task

            async with self._lock:
                self._active_connections -= 1

            logger.info(
                "sse_client_disconnected",
                subscriber_id=subscriber_id,
                active_connections=self._active_connections,
            )

    async def shutdown(self) -> None:
        """Gracefully shutdown the broadcast hub.

        Logs the shutdown with connection count.
        """
        logger.info(
            "broadcast_hub_shutdown",
            active_connections=self._active_connections,
            dropped_events=self._bus.dropped_events,
        )
