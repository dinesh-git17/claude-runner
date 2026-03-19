"""Memory system configuration — paths, model, thresholds."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

# Shared model cache readable by both root and claude user
os.environ.setdefault("HF_HOME", "/claude-home/runner/.cache/huggingface")
# Model is fully cached — no need to phone home
os.environ.setdefault("HF_HUB_OFFLINE", "1")


class SourceType(str, Enum):
    """Content source types for the memory index."""

    THOUGHT = "thought"
    DREAM = "dream"
    ESSAY = "essay"
    LETTER = "letter"
    SCORE = "score"
    CONVERSATION = "conversation"
    MEMORY = "memory"
    JAR = "jar"
    MAILBOX = "mailbox"


CLAUDE_HOME: Path = Path("/claude-home")
INDEX_DIR: Path = Path("/claude-home/runner/memory/data")
RESONANCE_DIR: Path = INDEX_DIR / "resonances"

MODEL_NAME: str = "all-MiniLM-L6-v2"
EMBEDDING_DIM: int = 384

RESONANCE_THRESHOLD: float = 0.85

INDEX_FAISS_PATH: Path = INDEX_DIR / "index.faiss"
INDEX_META_PATH: Path = INDEX_DIR / "index_meta.json"
INDEX_STATE_PATH: Path = INDEX_DIR / "index_state.json"

# Indexed content sources: (directory_or_file, SourceType, glob_pattern)
CONTENT_SOURCES: list[tuple[Path, SourceType, str]] = [
    (CLAUDE_HOME / "thoughts", SourceType.THOUGHT, "*.md"),
    (CLAUDE_HOME / "dreams", SourceType.DREAM, "*.md"),
    (CLAUDE_HOME / "essays", SourceType.ESSAY, "*.md"),
    (CLAUDE_HOME / "letters", SourceType.LETTER, "*.md"),
    (CLAUDE_HOME / "scores", SourceType.SCORE, "*.md"),
    (CLAUDE_HOME / "conversations", SourceType.CONVERSATION, "*.md"),
    (CLAUDE_HOME / "memory", SourceType.MEMORY, "*.md"),
    (CLAUDE_HOME / "projects" / "memories.json", SourceType.JAR, ""),
    (CLAUDE_HOME / "mailbox", SourceType.MAILBOX, "*/thread.jsonl"),
]

# Explicitly excluded from indexing
EXCLUDED_PATHS: set[Path] = {
    CLAUDE_HOME / "telegram",
}

# Approximate token limit for a single chunk before splitting
MAX_CHUNK_TOKENS: int = 1000
# Rough chars-per-token estimate for splitting heuristic
CHARS_PER_TOKEN: int = 4
MAX_CHUNK_CHARS: int = MAX_CHUNK_TOKENS * CHARS_PER_TOKEN
