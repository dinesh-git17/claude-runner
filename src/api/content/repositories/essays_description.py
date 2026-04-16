"""Essays page description repository."""
from pathlib import Path

import structlog

from api.content.paths import resolve_path
from api.content.schemas import EssaysDescription

logger = structlog.get_logger()

DEFAULT_DESCRIPTION = EssaysDescription(content="")


def get_essays_description() -> EssaysDescription:
    """Retrieve the essays page description.

    Reads from essays-description/essays-description.md. Returns empty
    content if file doesn't exist.

    Returns:
        EssaysDescription with markdown content.
    """
    filepath = resolve_path("essays-description", "essays-description.md")

    try:
        content = filepath.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.info("essays_description_not_found", path=str(filepath))
        return DEFAULT_DESCRIPTION
    except OSError as e:
        logger.error("essays_description_read_error", path=str(filepath), error=str(e))
        return DEFAULT_DESCRIPTION

    if not content:
        return DEFAULT_DESCRIPTION

    return EssaysDescription(content=content)
