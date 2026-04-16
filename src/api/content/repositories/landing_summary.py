"""Landing summary content repository."""
from datetime import datetime, timezone

import structlog

from api.content.paths import resolve_path
from api.content.schemas import LandingSummary

logger = structlog.get_logger()

DEFAULT_SUMMARY = LandingSummary(
    content="I live here. Come in, look around.",
    last_updated=datetime.now(timezone.utc),
)


def get_landing_summary() -> LandingSummary:
    """Retrieve the landing summary content.

    Reads from current.md in the landing-summary directory.
    Falls back to default if file doesn't exist or is empty.

    Returns:
        LandingSummary with content and last_updated.
    """
    try:
        summary_path = resolve_path("landing-summary", "current.md")
        if not summary_path.exists():
            logger.info("landing_summary_not_found")
            return DEFAULT_SUMMARY

        content = summary_path.read_text(encoding="utf-8").strip()
        if not content:
            logger.info("landing_summary_empty")
            return DEFAULT_SUMMARY

        stat = summary_path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        return LandingSummary(
            content=content,
            last_updated=mtime,
        )
    except OSError as e:
        logger.warning("landing_summary_read_error", error=str(e))
        return DEFAULT_SUMMARY
