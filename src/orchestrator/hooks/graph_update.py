"""Hook: update the memory graph incrementally after index refresh."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from orchestrator.pipeline import HookResult

if TYPE_CHECKING:
    from orchestrator.config import SessionResult

logger = structlog.get_logger()


async def run(result: SessionResult) -> HookResult:
    """Rebuild the memory graph from the updated FAISS index."""
    start = time.monotonic()

    try:
        from memory.graph import GRAPH_DB_PATH, MemoryGraph

        graph = MemoryGraph()
        if not GRAPH_DB_PATH.exists():
            logger.info("graph_update_first_build")
        counts = await asyncio.to_thread(graph.update_incremental)
        graph.close()
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.error("graph_update_failed", error=str(exc))
        return HookResult("graph_update", "failed", elapsed, str(exc))

    elapsed = int((time.monotonic() - start) * 1000)
    logger.info("graph_update_success", duration_ms=elapsed, **counts)
    return HookResult("graph_update", "success", elapsed)
