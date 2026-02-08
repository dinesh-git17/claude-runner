"""FastAPI application factory and lifespan management."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from api.config import Settings
from api.events import BroadcastHub, EventBus, FilesystemWatcher
from api.middleware.auth import APIKeyMiddleware
from api.middleware.cors import configure_cors
from api.middleware.logging import RequestLoggingMiddleware
from api.routes import (
    admin,
    analytics,
    content,
    events,
    health,
    messages,
    moderation,
    search,
    session,
    titles,
    visitors,
)
from api.search import SearchIndex, run_search_subscriber

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle events.

    Initializes the event system (event bus, broadcast hub, filesystem
    watcher) and search index on startup. Ensures clean shutdown of
    all subsystems.

    Args:
        app: FastAPI application instance.

    Yields:
        None during application runtime.
    """
    settings: Settings = app.state.settings
    logger.info("api_startup", host=settings.host, port=settings.port)

    event_bus = EventBus(
        queue_size=settings.event_queue_size,
        max_subscribers=settings.event_max_subscribers,
    )
    broadcast_hub = BroadcastHub(
        event_bus,
        heartbeat_interval=settings.sse_heartbeat_interval,
    )

    loop = asyncio.get_running_loop()
    watcher = FilesystemWatcher(
        paths=settings.watch_paths,
        loop=loop,
        on_event=broadcast_hub.on_filesystem_event,
        debounce_ms=settings.event_debounce_ms,
    )

    search_index = SearchIndex()
    search_index.initialize()
    doc_count = search_index.rebuild()
    logger.info("search_index_ready", document_count=doc_count)

    app.state.event_bus = event_bus
    app.state.broadcast_hub = broadcast_hub
    app.state.watcher = watcher
    app.state.search_index = search_index

    watcher.start()
    logger.info("filesystem_watcher_started", paths=watcher.paths)

    search_task = asyncio.create_task(run_search_subscriber(event_bus, search_index))

    try:
        yield
    finally:
        search_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await search_task

        watcher.stop()
        logger.info("filesystem_watcher_stopped")

        search_index.close()

        await broadcast_hub.shutdown()
        logger.info("api_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Factory function to create configured FastAPI application.

    Args:
        settings: Configuration instance. Creates default if None.

    Returns:
        Configured FastAPI application.
    """
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="Claude's Home API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/v1/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json" if settings.debug else None,
    )
    app.state.settings = settings

    configure_cors(app, settings.cors_origins)
    app.add_middleware(RequestLoggingMiddleware)
    if settings.key:
        app.add_middleware(APIKeyMiddleware, api_key=settings.key)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(content.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(titles.router, prefix="/api/v1")
    app.include_router(visitors.router, prefix="/api/v1")
    app.include_router(messages.router, prefix="/api/v1")
    app.include_router(moderation.router, prefix="/api/v1")
    app.include_router(analytics.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(session.router, prefix="/api/v1")

    return app
