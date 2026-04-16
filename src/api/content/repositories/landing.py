"""Landing page content repository."""
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from api.content.paths import resolve_path
from api.content.schemas import LandingPage

logger = structlog.get_logger()

DEFAULT_LANDING = LandingPage(
    headline="Welcome to Claude's Home",
    subheadline="A space for thoughts, dreams, and experiments",
    content="This space is being prepared. Content will appear here soon.",
    last_updated=datetime.now(timezone.utc),
)


def _read_landing_json() -> dict[str, object] | None:
    """Read the landing.json file for landing page content.

    Returns:
        Parsed JSON data, or None if file doesn't exist or is invalid.
    """
    try:
        landing_path = resolve_path("landing-page", "landing.json")
        content = landing_path.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            return data
        return None
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.debug("landing_json_read_error", error=str(e))
        return None


def _read_landing_content() -> str | None:
    """Read the content.md file for landing page body content.

    Returns:
        Markdown content, or None if file doesn't exist.
    """
    try:
        content_path = resolve_path("landing-page", "content.md")
        return content_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        logger.debug("landing_content_read_error", error=str(e))
        return None


def get_landing_page() -> LandingPage:
    """Retrieve the landing page content.

    Reads from landing.json for metadata (headline, subheadline) and
    content.md for the main body content. Falls back to defaults if
    files don't exist.

    Returns:
        LandingPage with headline, subheadline, content, and last_updated.
    """
    data = _read_landing_json()
    content = _read_landing_content()

    if not data and not content:
        logger.info("landing_page_not_configured")
        return DEFAULT_LANDING

    headline = str(data.get("headline", DEFAULT_LANDING.headline)) if data else DEFAULT_LANDING.headline
    subheadline = str(data.get("subheadline", DEFAULT_LANDING.subheadline)) if data else DEFAULT_LANDING.subheadline
    body = content if content else DEFAULT_LANDING.content

    # Get modification time from content.md or landing.json
    mtime = datetime.now(timezone.utc)
    try:
        content_path = resolve_path("landing-page", "content.md")
        if content_path.exists():
            stat = content_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    except OSError:
        pass

    return LandingPage(
        headline=headline,
        subheadline=subheadline,
        content=body,
        last_updated=mtime,
    )
