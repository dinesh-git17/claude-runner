"""SSE streaming endpoint for filesystem events."""

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

if TYPE_CHECKING:
    from api.events.hub import BroadcastHub

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/stream")
async def event_stream(
    request: Request,
    topic: Literal["thoughts", "dreams", "system", "*"] = Query(
        default="*",
        description="Event topic filter",
    ),
) -> EventSourceResponse:
    """Stream filesystem events via Server-Sent Events.

    Establishes a persistent SSE connection for real-time filesystem
    event notifications. Includes periodic heartbeat events.

    Args:
        request: FastAPI request object.
        topic: Event topic filter. Use "*" for all events.

    Returns:
        SSE response stream with filesystem events and heartbeats.
    """
    hub: BroadcastHub = request.app.state.broadcast_hub

    return EventSourceResponse(
        hub.create_sse_generator(topic),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
