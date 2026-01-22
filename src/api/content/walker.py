"""Directory tree traversal for filesystem endpoints."""

from pathlib import Path
from typing import Literal

import structlog

from api.content.paths import ALLOWED_ROOTS, SecurityError, is_excluded
from api.content.schemas import DirectoryTree, FileSystemNode

logger = structlog.get_logger()

MAX_DEPTH = 20
MAX_NODES = 5000


class WalkState:
    """Mutable state container for directory traversal.

    Attributes:
        node_count: Number of nodes encountered so far.
        truncated: Whether traversal was truncated due to limits.
    """

    def __init__(self) -> None:
        """Initialize walk state."""
        self.node_count = 0
        self.truncated = False


def walk_directory(
    absolute_path: Path,
    relative_path: str,
    depth: int,
    state: WalkState,
    max_depth: int = MAX_DEPTH,
) -> tuple[FileSystemNode, float] | None:
    """Recursively walk a directory and build a tree structure.

    Args:
        absolute_path: Absolute filesystem path to walk.
        relative_path: Path relative to the root for response.
        depth: Current recursion depth.
        state: Mutable state for tracking limits.
        max_depth: Maximum recursion depth allowed.

    Returns:
        Tuple of (FileSystemNode, mtime) for this path, or None if skipped.
    """
    if depth > max_depth:
        state.truncated = True
        return None

    if state.node_count >= MAX_NODES:
        state.truncated = True
        return None

    try:
        stat = absolute_path.lstat()
    except OSError:
        return None

    if stat.st_mode & 0o170000 == 0o120000:
        return None

    name = absolute_path.name or relative_path
    mtime = stat.st_mtime

    if stat.st_mode & 0o170000 == 0o100000:
        state.node_count += 1
        ext = absolute_path.suffix
        return (
            FileSystemNode(
                name=name,
                path=relative_path,
                type="file",
                size=stat.st_size,
                extension=ext[1:] if ext else None,
            ),
            mtime,
        )

    if stat.st_mode & 0o170000 == 0o040000:
        state.node_count += 1

        try:
            entries = list(absolute_path.iterdir())
        except OSError:
            return (
                FileSystemNode(
                    name=name,
                    path=relative_path,
                    type="directory",
                    children=[],
                ),
                mtime,
            )

        children_with_mtime: list[tuple[FileSystemNode, float]] = []

        for entry in entries:
            if is_excluded(entry.name):
                continue

            child_rel = f"{relative_path}/{entry.name}" if relative_path else entry.name

            result = walk_directory(
                entry,
                child_rel,
                depth + 1,
                state,
                max_depth,
            )

            if result:
                children_with_mtime.append(result)

            if state.node_count >= MAX_NODES:
                state.truncated = True
                break

        # Sort: directories first, then by mtime descending (newest first)
        children_with_mtime.sort(
            key=lambda x: (0 if x[0].type == "directory" else 1, -x[1])
        )
        children = [node for node, _ in children_with_mtime]

        return (
            FileSystemNode(
                name=name,
                path=relative_path,
                type="directory",
                children=children,
            ),
            mtime,
        )

    return None


def get_directory_tree(
    root: Literal["sandbox", "projects", "news", "gifts"],
    max_depth: int | None = None,
) -> DirectoryTree:
    """Get the directory tree for a content root.

    Only sandbox, projects, news, and gifts roots are allowed.

    Args:
        root: The content root to traverse.
        max_depth: Optional depth limit override.

    Returns:
        DirectoryTree response with root node and metadata.

    Raises:
        SecurityError: If root is not allowed for traversal.
    """
    if root not in ("sandbox", "projects", "news", "gifts"):
        raise SecurityError(
            f"Root {root} is not allowed for directory traversal",
            root,
        )

    root_path = Path(ALLOWED_ROOTS[root])
    state = WalkState()
    effective_depth = max_depth if max_depth is not None else MAX_DEPTH

    result = walk_directory(root_path, "", 0, state, effective_depth)

    if not result:
        return DirectoryTree(
            root=FileSystemNode(
                name=root,
                path="",
                type="directory",
                children=[],
            ),
            truncated=False,
            node_count=0,
        )

    root_node, _ = result
    root_node.name = root

    return DirectoryTree(
        root=root_node,
        truncated=state.truncated,
        node_count=state.node_count,
    )
