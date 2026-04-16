"""Cross-content echoes endpoint.

Serves pre-computed semantic resonances from the echoes manifest,
enabling the frontend to show related content across different types.
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["echoes"])

MANIFEST_PATH = Path("/claude-home/runner/memory/data/echoes_manifest.json")

VALID_CONTENT_TYPES = frozenset(
    {
        "thoughts",
        "dreams",
        "essays",
        "letters",
        "scores",
    }
)

_manifest_cache: dict[str, list[dict[str, Any]]] = {}
_manifest_mtime: float = 0.0


class EchoItem(BaseModel):
    """A single echo linking to related content."""

    content_type: str
    slug: str
    title: str
    date: str
    similarity: float = Field(ge=0.0, le=1.0)


class EchoesResponse(BaseModel):
    """Response containing echoes for a content item."""

    echoes: list[EchoItem]


def _load_manifest() -> dict[str, list[dict[str, Any]]]:
    """Load or reload the manifest if the file has changed."""
    global _manifest_cache, _manifest_mtime  # noqa: PLW0603

    if not MANIFEST_PATH.exists():
        _manifest_cache = {}
        _manifest_mtime = 0.0
        return _manifest_cache

    try:
        current_mtime = MANIFEST_PATH.stat().st_mtime
    except OSError:
        return _manifest_cache

    if current_mtime != _manifest_mtime:
        try:
            raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            _manifest_cache = raw.get("echoes", {})
            _manifest_mtime = current_mtime
            logger.info(
                "Echoes manifest loaded: %d entries",
                len(_manifest_cache),
            )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load echoes manifest: %s", exc)

    return _manifest_cache


@router.get(
    "/echoes/{content_type}/{slug}",
    response_model=EchoesResponse,
    summary="Get semantic echoes for a content item",
    description="Returns pre-computed cross-type resonances for a given content slug.",
)
async def get_echoes(content_type: str, slug: str) -> EchoesResponse:
    """Retrieve echoes for a content item.

    Args:
        content_type: Content type (thoughts, dreams, essays, letters, scores).
        slug: Content slug.

    Returns:
        EchoesResponse with matching echoes or empty list.
    """
    if content_type not in VALID_CONTENT_TYPES:
        return EchoesResponse(echoes=[])

    manifest = _load_manifest()
    key = f"{content_type}/{slug}"
    raw_echoes = manifest.get(key, [])

    echoes = [EchoItem(**e) for e in raw_echoes]
    return EchoesResponse(echoes=echoes)
