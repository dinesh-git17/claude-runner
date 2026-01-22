"""Security-first path resolution for content access."""
from pathlib import Path
from typing import Literal

ContentRoot = Literal["about", "thoughts", "dreams", "sandbox", "projects", "landing-page", "visitor-greeting", "news", "gifts"]

ALLOWED_ROOTS: dict[ContentRoot, str] = {
    "about": "/claude-home/about",
    "thoughts": "/claude-home/thoughts",
    "dreams": "/claude-home/dreams",
    "sandbox": "/claude-home/sandbox",
    "projects": "/claude-home/projects",
    "landing-page": "/claude-home/landing-page",
    "visitor-greeting": "/claude-home/visitor-greeting",
    "news": "/claude-home/news",
    "gifts": "/claude-home/gifts",
}

EXCLUDED_PATTERNS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    ".DS_Store",
    "__pycache__",
    ".env",
})

SECRET_EXTENSIONS: frozenset[str] = frozenset({
    ".key",
    ".pem",
    ".env",
})


class SecurityError(Exception):
    """Raised when a path operation violates security constraints."""

    def __init__(self, message: str, path: str) -> None:
        """Initialize security error.

        Args:
            message: Error description.
            path: The offending path value.
        """
        super().__init__(message)
        self.path = path


def resolve_path(root: ContentRoot, slug: str) -> Path:
    """Resolve a slug to an absolute path within an allowed root.

    Performs security validation to prevent directory traversal attacks.

    Args:
        root: The content root category.
        slug: Relative path or filename within the root.

    Returns:
        Absolute Path object for the resolved location.

    Raises:
        SecurityError: If the path contains null bytes, traversal sequences,
            or resolves outside the allowed root.
    """
    if "\0" in slug:
        raise SecurityError("Path contains null byte", slug)

    if ".." in slug:
        raise SecurityError("Path contains directory traversal sequence", slug)

    root_path = Path(ALLOWED_ROOTS[root])
    resolved = (root_path / slug).resolve()

    if not str(resolved).startswith(str(root_path)):
        raise SecurityError(f"Path resolves outside allowed root: {root_path}", slug)

    return resolved


def is_excluded(name: str) -> bool:
    """Check if a filename should be excluded from directory listings.

    Args:
        name: Filename to check.

    Returns:
        True if the file should be excluded.
    """
    if name in EXCLUDED_PATTERNS:
        return True

    if name.startswith("."):
        return True

    suffix = Path(name).suffix.lower()
    if suffix in SECRET_EXTENSIONS:
        return True

    return False


def validate_file_root(root: str) -> ContentRoot | None:
    """Validate that a root string is allowed for file access.

    Only sandbox, projects, news, and gifts are allowed for raw file content access.

    Args:
        root: The root string to validate.

    Returns:
        The validated ContentRoot, or None if invalid.
    """
    if root in ("sandbox", "projects", "news", "gifts"):
        return root  # type: ignore[return-value]
    return None
