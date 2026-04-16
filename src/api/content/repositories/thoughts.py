"""Thoughts content repository."""
from pathlib import Path

import structlog

from api.content.loader import (
    ContentValidationError,
    FileSystemError,
    read_content,
)
from api.content.paths import ALLOWED_ROOTS, resolve_path
from api.content.schemas import ThoughtDetail, ThoughtListItem, ThoughtMeta

logger = structlog.get_logger()


def get_all_thoughts() -> list[ThoughtListItem]:
    """Retrieve all thought entries sorted by date descending, then mtime descending.

    Skips files with invalid frontmatter, logging errors but continuing
    to process remaining files.

    Returns:
        List of thought entries, newest first. Same-day entries ordered by
        file modification time (most recent first).
    """
    dir_path = Path(ALLOWED_ROOTS["thoughts"])

    try:
        files = list(dir_path.iterdir())
    except FileNotFoundError:
        logger.warning("thoughts_directory_not_found", path=str(dir_path))
        return []
    except OSError as e:
        logger.error("thoughts_directory_error", path=str(dir_path), error=str(e))
        return []

    md_files = [f for f in files if f.suffix == ".md" and f.is_file()]
    entries_with_mtime: list[tuple[ThoughtListItem, float]] = []

    for file in md_files:
        try:
            result = read_content(file, ThoughtMeta)
            slug = file.stem
            mtime = file.stat().st_mtime
            entries_with_mtime.append(
                (
                    ThoughtListItem(
                        slug=slug,
                        date=result.meta.date,
                        title=result.meta.title,
                        mood=result.meta.mood,
                    ),
                    mtime,
                )
            )
        except ContentValidationError as e:
            logger.warning(
                "thought_validation_error",
                file=str(file),
                error=str(e.validation_error),
            )
        except FileSystemError as e:
            logger.warning(
                "thought_filesystem_error",
                file=str(file),
                error=str(e),
                code=e.code,
            )
        except Exception as e:
            logger.error(
                "thought_unknown_error",
                file=str(file),
                error=str(e),
            )

    # Sort by date descending, then mtime descending for same-day entries
    entries_with_mtime.sort(key=lambda x: (x[0].date, x[1]), reverse=True)
    return [entry for entry, _ in entries_with_mtime]


def get_thought_by_slug(slug: str) -> ThoughtDetail | None:
    """Retrieve a single thought by its slug.

    Args:
        slug: The thought identifier (filename without extension).

    Returns:
        ThoughtDetail if found, None otherwise.

    Raises:
        SecurityError: If slug contains path traversal attempts.
    """
    filepath = resolve_path("thoughts", f"{slug}.md")

    try:
        result = read_content(filepath, ThoughtMeta)
        return ThoughtDetail(
            slug=slug,
            meta=result.meta,
            content=result.content,
        )
    except FileSystemError as e:
        if e.code == "ENOENT":
            return None
        raise
