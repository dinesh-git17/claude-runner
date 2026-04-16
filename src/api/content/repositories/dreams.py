"""Dreams content repository."""
from pathlib import Path

import structlog

from api.content.loader import (
    ContentValidationError,
    FileSystemError,
    read_content,
)
from api.content.paths import ALLOWED_ROOTS, resolve_path
from api.content.schemas import DreamDetail, DreamListItem, DreamMeta

logger = structlog.get_logger()


def get_all_dreams() -> list[DreamListItem]:
    """Retrieve all dream entries sorted by date descending, then mtime descending.

    Skips files with invalid frontmatter, logging errors but continuing
    to process remaining files.

    Returns:
        List of dream entries, newest first. Same-day entries ordered by
        file modification time (most recent first).
    """
    dir_path = Path(ALLOWED_ROOTS["dreams"])

    try:
        files = list(dir_path.iterdir())
    except FileNotFoundError:
        logger.warning("dreams_directory_not_found", path=str(dir_path))
        return []
    except OSError as e:
        logger.error("dreams_directory_error", path=str(dir_path), error=str(e))
        return []

    md_files = [f for f in files if f.suffix == ".md" and f.is_file()]
    entries_with_mtime: list[tuple[DreamListItem, float]] = []

    for file in md_files:
        try:
            result = read_content(file, DreamMeta)
            slug = file.stem
            mtime = file.stat().st_mtime
            entries_with_mtime.append(
                (
                    DreamListItem(
                        slug=slug,
                        date=result.meta.date,
                        title=result.meta.title,
                        type=result.meta.type,
                        immersive=result.meta.immersive,
                    ),
                    mtime,
                )
            )
        except ContentValidationError as e:
            logger.warning(
                "dream_validation_error",
                file=str(file),
                error=str(e.validation_error),
            )
        except FileSystemError as e:
            logger.warning(
                "dream_filesystem_error",
                file=str(file),
                error=str(e),
                code=e.code,
            )
        except Exception as e:
            logger.error(
                "dream_unknown_error",
                file=str(file),
                error=str(e),
            )

    # Sort by date descending, then mtime descending for same-day entries
    entries_with_mtime.sort(key=lambda x: (x[0].date, x[1]), reverse=True)
    return [entry for entry, _ in entries_with_mtime]


def get_dream_by_slug(slug: str) -> DreamDetail | None:
    """Retrieve a single dream by its slug.

    Args:
        slug: The dream identifier (filename without extension).

    Returns:
        DreamDetail if found, None otherwise.

    Raises:
        SecurityError: If slug contains path traversal attempts.
    """
    filepath = resolve_path("dreams", f"{slug}.md")

    try:
        result = read_content(filepath, DreamMeta)
        return DreamDetail(
            slug=slug,
            meta=result.meta,
            content=result.content,
        )
    except FileSystemError as e:
        if e.code == "ENOENT":
            return None
        raise
