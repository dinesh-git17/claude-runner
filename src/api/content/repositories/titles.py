"""Title registry repository for persistent storage."""

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from api.content.schemas import TitleEntry

REGISTRY_PATH = Path("/claude-home/data/memory-registry.json")

_lock = threading.Lock()


class RegistryMemory(TypedDict):
    """Memory entry structure in registry."""

    title: str
    model: str
    created: str
    originalPath: str


class RegistryData(TypedDict):
    """Registry file structure."""

    registryVersion: int
    memories: dict[str, RegistryMemory]


def _load_registry() -> RegistryData:
    """Load registry from disk, creating if necessary."""
    if not REGISTRY_PATH.exists():
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        initial: RegistryData = {"registryVersion": 1, "memories": {}}
        _save_registry(initial)
        return initial

    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_registry(data: RegistryData) -> None:
    """Atomically save registry to disk."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        dir=REGISTRY_PATH.parent,
        prefix=".memory-registry-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, REGISTRY_PATH)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def get_by_hash(content_hash: str) -> TitleEntry | None:
    """Retrieve a title entry by content hash.

    Args:
        content_hash: SHA-256 hash of the content.

    Returns:
        TitleEntry if found, None otherwise.
    """
    with _lock:
        registry = _load_registry()

    memory = registry["memories"].get(content_hash)
    if memory is None:
        return None

    return TitleEntry(
        hash=content_hash,
        title=memory["title"],
        model=memory["model"],
        created=datetime.fromisoformat(memory["created"]),
        original_path=memory["originalPath"],
    )


def store(
    content_hash: str,
    title: str,
    model: str,
    original_path: str,
) -> tuple[TitleEntry, bool]:
    """Store a new title entry.

    Args:
        content_hash: SHA-256 hash of the content.
        title: Generated title.
        model: Model ID used for generation.
        original_path: Original file path.

    Returns:
        Tuple of (TitleEntry, created) where created is True if new entry.
    """
    now = datetime.now(timezone.utc)

    with _lock:
        registry = _load_registry()

        if content_hash in registry["memories"]:
            existing = registry["memories"][content_hash]
            return (
                TitleEntry(
                    hash=content_hash,
                    title=existing["title"],
                    model=existing["model"],
                    created=datetime.fromisoformat(existing["created"]),
                    original_path=existing["originalPath"],
                ),
                False,
            )

        memory: RegistryMemory = {
            "title": title,
            "model": model,
            "created": now.isoformat(),
            "originalPath": original_path,
        }
        registry["memories"][content_hash] = memory
        _save_registry(registry)

    return (
        TitleEntry(
            hash=content_hash,
            title=title,
            model=model,
            created=now,
            original_path=original_path,
        ),
        True,
    )
