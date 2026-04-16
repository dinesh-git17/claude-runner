"""Content module for file-based content access."""

from api.content.loader import (
    ContentResult,
    ContentValidationError,
    FileSystemError,
    read_content,
)
from api.content.paths import (
    ALLOWED_ROOTS,
    ContentRoot,
    SecurityError,
    is_excluded,
    resolve_path,
    validate_file_root,
)
from api.content.schemas import (
    AboutPage,
    DirectoryTree,
    DreamDetail,
    DreamListItem,
    DreamMeta,
    DreamType,
    ErrorResponse,
    FileContent,
    FileSystemNode,
    ThoughtDetail,
    ThoughtListItem,
    ThoughtMeta,
)
from api.content.walker import get_directory_tree

__all__ = [
    "ALLOWED_ROOTS",
    "AboutPage",
    "ContentResult",
    "ContentRoot",
    "ContentValidationError",
    "DirectoryTree",
    "DreamDetail",
    "DreamListItem",
    "DreamMeta",
    "DreamType",
    "ErrorResponse",
    "FileContent",
    "FileSystemError",
    "FileSystemNode",
    "SecurityError",
    "ThoughtDetail",
    "ThoughtListItem",
    "ThoughtMeta",
    "get_directory_tree",
    "is_excluded",
    "read_content",
    "resolve_path",
    "validate_file_root",
]
