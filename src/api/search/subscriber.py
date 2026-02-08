"""Event bus subscriber for keeping the search index in sync."""

import asyncio
from pathlib import Path

import structlog

from api.content.paths import ALLOWED_ROOTS
from api.events.bus import EventBus
from api.events.types import EventType
from api.search.index import SearchIndex

logger = structlog.get_logger()

_UPSERT_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.THOUGHT_CREATED,
        EventType.THOUGHT_MODIFIED,
        EventType.DREAM_CREATED,
        EventType.DREAM_MODIFIED,
    }
)

_DELETE_EVENTS: frozenset[EventType] = frozenset(
    {
        EventType.THOUGHT_DELETED,
        EventType.DREAM_DELETED,
    }
)

_TOPIC_TO_ROOT: dict[str, str] = {
    "thoughts": ALLOWED_ROOTS["thoughts"],
    "dreams": ALLOWED_ROOTS["dreams"],
}


async def run_search_subscriber(
    event_bus: EventBus,
    search_index: SearchIndex,
) -> None:
    """Subscribe to filesystem events and update the search index.

    Runs as a long-lived asyncio task. Dispatches create/modify events
    to upsert_document and delete events to delete_document.

    Args:
        event_bus: Application event bus instance.
        search_index: Active search index to update.
    """
    subscriber_id, events = await event_bus.subscribe(topic="*")
    logger.info("search_subscriber_started", subscriber_id=subscriber_id)

    try:
        async for event in events:
            if event.type in _UPSERT_EVENTS:
                root_dir = _TOPIC_TO_ROOT.get(event.topic)
                if root_dir and event.slug:
                    filepath = Path(root_dir) / f"{event.slug}.md"
                    if filepath.exists():
                        await asyncio.to_thread(search_index.upsert_document, filepath)

            elif event.type in _DELETE_EVENTS:
                if event.slug:
                    content_type = "thought" if event.topic == "thoughts" else "dream"
                    await asyncio.to_thread(
                        search_index.delete_document, event.slug, content_type
                    )
    except asyncio.CancelledError:
        logger.info("search_subscriber_stopped", subscriber_id=subscriber_id)
        raise
