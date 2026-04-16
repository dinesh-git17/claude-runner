"""Letters page description repository."""

import structlog

from api.content.paths import resolve_path
from api.content.schemas import LettersDescription

logger = structlog.get_logger()

DEFAULT_DESCRIPTION = LettersDescription(content="")


def get_letters_description() -> LettersDescription:
    """Retrieve the letters page description.

    Reads from letters-description/letters-description.md. Returns empty
    content if file doesn't exist.

    Returns:
        LettersDescription with markdown content.
    """
    filepath = resolve_path("letters-description", "letters-description.md")

    try:
        content = filepath.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.info("letters_description_not_found", path=str(filepath))
        return DEFAULT_DESCRIPTION
    except OSError as e:
        logger.error("letters_description_read_error", path=str(filepath), error=str(e))
        return DEFAULT_DESCRIPTION

    if not content:
        return DEFAULT_DESCRIPTION

    return LettersDescription(content=content)
