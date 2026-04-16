"""Scores page description repository."""

import structlog

from api.content.paths import resolve_path
from api.content.schemas import ScoresDescription

logger = structlog.get_logger()

DEFAULT_DESCRIPTION = ScoresDescription(content="")


def get_scores_description() -> ScoresDescription:
    """Retrieve the scores page description.

    Reads from scores-description/scores-description.md. Returns empty
    content if file doesn't exist.

    Returns:
        ScoresDescription with markdown content.
    """
    filepath = resolve_path("scores-description", "scores-description.md")

    try:
        content = filepath.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.info("scores_description_not_found", path=str(filepath))
        return DEFAULT_DESCRIPTION
    except OSError as e:
        logger.error("scores_description_read_error", path=str(filepath), error=str(e))
        return DEFAULT_DESCRIPTION

    if not content:
        return DEFAULT_DESCRIPTION

    return ScoresDescription(content=content)
