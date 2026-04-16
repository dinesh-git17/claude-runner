"""Letters content repository."""
from pathlib import Path

import structlog

from api.content.loader import (
    ContentValidationError,
    FileSystemError,
    read_content,
)
from api.content.paths import ALLOWED_ROOTS, resolve_path
from api.content.schemas import LetterDetail, LetterListItem, LetterMeta

logger = structlog.get_logger()


def get_all_letters() -> list[LetterListItem]:
    """Retrieve all letter entries sorted by date descending, then mtime descending.

    Skips files with invalid frontmatter, logging errors but continuing
    to process remaining files.

    Returns:
        List of letter entries, newest first. Same-day entries ordered by
        file modification time (most recent first).
    """
    dir_path = Path(ALLOWED_ROOTS["letters"])

    try:
        files = list(dir_path.iterdir())
    except FileNotFoundError:
        logger.warning("letters_directory_not_found", path=str(dir_path))
        return []
    except OSError as e:
        logger.error("letters_directory_error", path=str(dir_path), error=str(e))
        return []

    md_files = [f for f in files if f.suffix == ".md" and f.is_file()]
    entries_with_mtime: list[tuple[LetterListItem, float]] = []

    for file in md_files:
        try:
            result = read_content(file, LetterMeta)
            slug = file.stem
            mtime = file.stat().st_mtime
            entries_with_mtime.append(
                (
                    LetterListItem(
                        slug=slug,
                        date=result.meta.date,
                        title=result.meta.title,
                    ),
                    mtime,
                )
            )
        except ContentValidationError as e:
            logger.warning(
                "letter_validation_error",
                file=str(file),
                error=str(e.validation_error),
            )
        except FileSystemError as e:
            logger.warning(
                "letter_filesystem_error",
                file=str(file),
                error=str(e),
                code=e.code,
            )
        except Exception as e:
            logger.error(
                "letter_unknown_error",
                file=str(file),
                error=str(e),
            )

    entries_with_mtime.sort(key=lambda x: (x[0].date, x[1]), reverse=True)
    return [entry for entry, _ in entries_with_mtime]


def get_letter_by_slug(slug: str) -> LetterDetail | None:
    """Retrieve a single letter by its slug.

    Args:
        slug: The letter identifier (filename without extension).

    Returns:
        LetterDetail if found, None otherwise.

    Raises:
        SecurityError: If slug contains path traversal attempts.
    """
    filepath = resolve_path("letters", f"{slug}.md")

    try:
        result = read_content(filepath, LetterMeta)
        return LetterDetail(
            slug=slug,
            meta=result.meta,
            content=result.content,
        )
    except FileSystemError as e:
        if e.code == "ENOENT":
            return None
        raise
