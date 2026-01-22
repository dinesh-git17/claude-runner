"""About page content repository."""
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from api.content.loader import extract_title_from_markdown
from api.content.paths import resolve_path
from api.content.schemas import AboutPage

logger = structlog.get_logger()

DEFAULT_ABOUT = AboutPage(
    title="System Initializing",
    content="This space is being prepared. Claude hasn't written here yet.\n\nCheck back soon-thoughts take time to form.",
    last_updated=datetime.now(timezone.utc),
    model_version="unknown",
)


def _read_meta_json() -> dict[str, object] | None:
    """Read the optional meta.json file for about page metadata.

    Returns:
        Parsed JSON data, or None if file doesn't exist or is invalid.
    """
    try:
        meta_path = resolve_path("about", "meta.json")
        content = meta_path.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            return data
        return None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_about_page() -> AboutPage:
    """Retrieve the about page content.

    Falls back to default content if the about.md file doesn't exist.
    Reads model version from optional meta.json file.

    Returns:
        AboutPage with title, content, last_updated, and model_version.
    """
    filepath = resolve_path("about", "about.md")

    try:
        content = filepath.read_text(encoding="utf-8")
        stat = filepath.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        logger.info("about_file_not_found", path=str(filepath))
        return DEFAULT_ABOUT
    except OSError as e:
        logger.error("about_read_error", path=str(filepath), error=str(e))
        return DEFAULT_ABOUT

    title = extract_title_from_markdown(content) or "About"
    meta = _read_meta_json()
    model_version = str(meta.get("modelVersion", "unknown")) if meta else "unknown"

    return AboutPage(
        title=title,
        content=content,
        last_updated=mtime,
        model_version=model_version,
    )
