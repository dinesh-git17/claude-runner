"""In-memory event bus with topic-based pub/sub."""
import asyncio
import uuid
from collections.abc import AsyncIterator

import structlog

from api.events.types import DomainEvent

logger = structlog.get_logger()


class EventBus:
    """Async event bus with topic-based fan-out and backpressure.

    Manages subscriber queues and distributes events to all interested
    subscribers based on topic. Implements drop-oldest strategy when
    subscriber queues overflow.

    Attributes:
        queue_size: Maximum size of each subscriber queue.
        max_subscribers: Maximum number of concurrent subscribers.
    """

    def __init__(
        self,
        queue_size: int = 100,
        max_subscribers: int = 100,
    ) -> None:
        """Initialize event bus.

        Args:
            queue_size: Maximum items per subscriber queue.
            max_subscribers: Maximum concurrent subscribers allowed.
        """
        self._subscribers: dict[str, dict[str, asyncio.Queue[DomainEvent]]] = {
            "thoughts": {},
            "dreams": {},
            "system": {},
            "*": {},
        }
        self._queue_size = queue_size
        self._max_subscribers = max_subscribers
        self._dropped_count = 0
        self._lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        """Total number of active subscribers across all topics."""
        return sum(len(subs) for subs in self._subscribers.values())

    @property
    def dropped_events(self) -> int:
        """Total number of events dropped due to queue overflow."""
        return self._dropped_count

    async def publish(self, event: DomainEvent) -> int:
        """Publish event to all subscribers of the topic and wildcard.

        Distributes event to subscribers of the specific topic and all
        wildcard subscribers. Uses drop-oldest strategy if queues are full.

        Args:
            event: Domain event to publish.

        Returns:
            Number of subscribers that received the event.
        """
        delivered = 0
        topics_to_notify = [event.topic, "*"]

        for topic in topics_to_notify:
            subscribers = self._subscribers.get(topic, {})
            for subscriber_id, queue in list(subscribers.items()):
                try:
                    queue.put_nowait(event)
                    delivered += 1
                except asyncio.QueueFull:
                    try:
                        queue.get_nowait()
                        queue.put_nowait(event)
                        delivered += 1
                        self._dropped_count += 1
                    except asyncio.QueueEmpty:
                        pass

        return delivered

    async def subscribe(
        self,
        topic: str = "*",
    ) -> tuple[str, AsyncIterator[DomainEvent]]:
        """Subscribe to events on a topic.

        Creates a new subscriber queue and returns an async iterator
        for receiving events.

        Args:
            topic: Topic to subscribe to. Use "*" for all events.

        Returns:
            Tuple of (subscriber_id, event_iterator).

        Raises:
            ValueError: If maximum subscribers reached.
        """
        async with self._lock:
            if self.subscriber_count >= self._max_subscribers:
                raise ValueError("Maximum subscribers reached")

            subscriber_id = str(uuid.uuid4())
            queue: asyncio.Queue[DomainEvent] = asyncio.Queue(
                maxsize=self._queue_size,
            )

            if topic not in self._subscribers:
                topic = "*"

            self._subscribers[topic][subscriber_id] = queue

        async def event_iterator() -> AsyncIterator[DomainEvent]:
            try:
                while True:
                    event = await queue.get()
                    yield event
            except asyncio.CancelledError:
                pass
            finally:
                await self.unsubscribe(topic, subscriber_id)

        return subscriber_id, event_iterator()

    async def unsubscribe(self, topic: str, subscriber_id: str) -> None:
        """Remove a subscriber from the bus.

        Args:
            topic: Topic the subscriber was subscribed to.
            subscriber_id: ID of the subscriber to remove.
        """
        async with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic].pop(subscriber_id, None)
                logger.debug(
                    "subscriber_removed",
                    subscriber_id=subscriber_id,
                    topic=topic,
                )
