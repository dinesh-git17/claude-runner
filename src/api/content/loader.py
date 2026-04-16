"""Frontmatter parsing and content loading utilities."""
import re
from pathlib import Path
from typing import Generic, TypeVar

import structlog
import yaml
from pydantic import BaseModel, ValidationError

logger = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)

FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)$",
    re.DOTALL,
)


class ContentResult(Generic[T]):
    """Result of parsing a content file with frontmatter.

    Attributes:
        meta: Validated frontmatter data.
        content: Raw markdown content after frontmatter.
    """

    def __init__(self, meta: T, content: str) -> None:
        """Initialize content result.

        Args:
            meta: Validated frontmatter data.
            content: Raw markdown content.
        """
        self.meta = meta
        self.content = content


class FileSystemError(Exception):
    """Raised when file operations fail."""

    def __init__(self, message: str, path: str, code: str | None = None) -> None:
        """Initialize filesystem error.

        Args:
            message: Error description.
            path: Path that caused the error.
            code: Optional error code (e.g., ENOENT).
        """
        super().__init__(message)
        self.path = path
        self.code = code


class ContentValidationError(Exception):
    """Raised when frontmatter validation fails."""

    def __init__(
        self, message: str, path: str, validation_error: ValidationError
    ) -> None:
        """Initialize validation error.

        Args:
            message: Error description.
            path: Path of the invalid file.
            validation_error: Pydantic validation error details.
        """
        super().__init__(message)
        self.path = path
        self.validation_error = validation_error


def parse_frontmatter(content: str) -> tuple[dict[str, object], str]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: Raw file content with optional frontmatter.

    Returns:
        Tuple of (frontmatter dict, remaining content).
        Returns empty dict if no frontmatter found.
    """
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}, content

    yaml_content = match.group(1)
    body = match.group(2)

    try:
        data = yaml.safe_load(yaml_content)
        if not isinstance(data, dict):
            return {}, content
        return data, body
    except yaml.YAMLError:
        return {}, content


def read_content(filepath: Path, schema: type[T]) -> ContentResult[T]:
    """Read and parse a content file with frontmatter validation.

    Args:
        filepath: Absolute path to the markdown file.
        schema: Pydantic model class for frontmatter validation.

    Returns:
        ContentResult containing validated meta and raw content.

    Raises:
        FileSystemError: If the file cannot be read.
        ContentValidationError: If frontmatter validation fails.
    """
    try:
        raw = filepath.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise FileSystemError(
            f"File not found: {filepath}",
            str(filepath),
            "ENOENT",
        ) from e
    except PermissionError as e:
        raise FileSystemError(
            f"Permission denied: {filepath}",
            str(filepath),
            "EACCES",
        ) from e
    except OSError as e:
        raise FileSystemError(
            f"Failed to read file: {e}",
            str(filepath),
            getattr(e, "errno", None),
        ) from e

    frontmatter, content = parse_frontmatter(raw)

    try:
        meta = schema.model_validate(frontmatter)
    except ValidationError as e:
        raise ContentValidationError(
            f"Invalid frontmatter in {filepath}",
            str(filepath),
            e,
        ) from e

    return ContentResult(meta=meta, content=content)


def extract_title_from_markdown(content: str) -> str | None:
    """Extract the first H1 heading from markdown content.

    Args:
        content: Raw markdown content.

    Returns:
        The title text, or None if no H1 found.
    """
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None
