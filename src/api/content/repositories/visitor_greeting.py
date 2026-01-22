"""Visitor greeting content repository."""
from datetime import datetime, timezone

import structlog

from api.content.paths import resolve_path
from api.content.schemas import VisitorGreeting

logger = structlog.get_logger()

DEFAULT_GREETING = VisitorGreeting(
    content="Welcome, visitor. Feel free to leave a message.",
    last_updated=datetime.now(timezone.utc),
)


def get_visitor_greeting() -> VisitorGreeting:
    """Retrieve the visitor greeting content.

    Reads from greeting.md in the visitor-greeting directory.
    Falls back to default if file doesn't exist.

    Returns:
        VisitorGreeting with content and last_updated.
    """
    try:
        greeting_path = resolve_path("visitor-greeting", "greeting.md")
        if not greeting_path.exists():
            logger.info("visitor_greeting_not_found")
            return DEFAULT_GREETING

        content = greeting_path.read_text(encoding="utf-8")
        stat = greeting_path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        return VisitorGreeting(
            content=content,
            last_updated=mtime,
        )
    except OSError as e:
        logger.warning("visitor_greeting_read_error", error=str(e))
        return DEFAULT_GREETING
