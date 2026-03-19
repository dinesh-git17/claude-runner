"""Content-type-aware chunking for the memory index."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from memory.config import (
    CLAUDE_HOME,
    EXCLUDED_PATHS,
    MAX_CHUNK_CHARS,
    SourceType,
)

logger = logging.getLogger(__name__)


@dataclass
class ChunkMeta:
    """Metadata for a single indexed chunk."""

    chunk_id: str
    source_file: str
    source_type: str
    title: str
    date: str
    offset_start: int
    offset_end: int
    text: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChunkMeta:
        """Deserialize from dict."""
        return cls(**data)


def _make_chunk_id(source_file: str, offset_start: int) -> str:
    """Deterministic chunk ID from file path and offset."""
    raw = f"{source_file}:{offset_start}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _relative_path(path: Path) -> str:
    """Path relative to CLAUDE_HOME for display."""
    try:
        return str(path.relative_to(CLAUDE_HOME))
    except ValueError:
        return str(path)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract YAML frontmatter and return (metadata, body).

    Handles simple key: "value" and key: value pairs.
    Does not depend on PyYAML.
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end == -1:
        return {}, text

    raw_fm = text[3:end].strip()
    body = text[end + 3 :].strip()

    metadata: dict[str, str] = {}
    for line in raw_fm.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip().strip('"').strip("'")
        metadata[key.strip()] = val

    return metadata, body


def _split_by_headers(body: str) -> list[tuple[int, int, str]]:
    """Split markdown body on ## headers.

    Returns:
        List of (start_line, end_line, text) tuples.
    """
    lines = body.split("\n")
    sections: list[tuple[int, int, str]] = []
    current_start = 0
    current_lines: list[str] = []

    for i, line in enumerate(lines):
        if line.startswith("## ") and current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                sections.append((current_start, i - 1, text))
            current_start = i
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((current_start, len(lines) - 1, text))

    return sections


def _split_by_separators(body: str) -> list[tuple[int, int, str]]:
    """Split on --- separators or ## headers, fallback to double-newline paragraphs."""
    lines = body.split("\n")

    has_headers = any(line.startswith("## ") for line in lines)
    if has_headers:
        return _split_by_headers(body)

    # Check for --- separators (not at the very start)
    separator_indices = [i for i, line in enumerate(lines) if line.strip() == "---"]

    if separator_indices:
        sections: list[tuple[int, int, str]] = []
        prev = 0
        for sep_idx in separator_indices:
            text = "\n".join(lines[prev:sep_idx]).strip()
            if text:
                sections.append((prev, sep_idx - 1, text))
            prev = sep_idx + 1
        text = "\n".join(lines[prev:]).strip()
        if text:
            sections.append((prev, len(lines) - 1, text))
        return sections

    return _split_by_paragraphs(body)


def _split_by_paragraphs(body: str) -> list[tuple[int, int, str]]:
    """Split on double newlines (paragraph boundaries)."""
    lines = body.split("\n")
    sections: list[tuple[int, int, str]] = []
    current_start = 0
    current_lines: list[str] = []
    blank_count = 0

    for i, line in enumerate(lines):
        if line.strip() == "":
            blank_count += 1
            if blank_count >= 2 and current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append((current_start, i - blank_count, text))
                current_lines = []
                current_start = i + 1
                blank_count = 0
            else:
                current_lines.append(line)
        else:
            blank_count = 0
            current_lines.append(line)

    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((current_start, len(lines) - 1, text))

    return sections


def _split_by_speaker_turn(body: str) -> list[tuple[int, int, str]]:
    """Split conversation files by ## Message / ## Response headers."""
    lines = body.split("\n")
    sections: list[tuple[int, int, str]] = []
    current_start = 0
    current_lines: list[str] = []

    for i, line in enumerate(lines):
        if re.match(r"^## (Message|Response|Visitor|Claude)", line, re.IGNORECASE):
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append((current_start, i - 1, text))
            current_start = i
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((current_start, len(lines) - 1, text))

    return sections if sections else _split_by_headers(body)


def _maybe_split_large(
    chunks: list[tuple[int, int, str]],
) -> list[tuple[int, int, str]]:
    """Split any chunk exceeding MAX_CHUNK_CHARS into paragraph-sized pieces."""
    result: list[tuple[int, int, str]] = []
    for start, end, text in chunks:
        if len(text) <= MAX_CHUNK_CHARS:
            result.append((start, end, text))
            continue
        sub_chunks = _split_by_paragraphs(text)
        if len(sub_chunks) <= 1:
            result.append((start, end, text))
        else:
            for s_start, s_end, s_text in sub_chunks:
                result.append((start + s_start, start + s_end, s_text))
    return result


def _detect_source_type(path: Path) -> SourceType | None:
    """Determine source type from file path."""
    rel = _relative_path(path)
    parts = rel.split("/")
    if not parts:
        return None

    dir_map: dict[str, SourceType] = {
        "thoughts": SourceType.THOUGHT,
        "dreams": SourceType.DREAM,
        "essays": SourceType.ESSAY,
        "letters": SourceType.LETTER,
        "scores": SourceType.SCORE,
        "conversations": SourceType.CONVERSATION,
        "memory": SourceType.MEMORY,
    }

    top_dir = parts[0]
    return dir_map.get(top_dir)


def _is_excluded(path: Path) -> bool:
    """Check if path falls under an excluded directory."""
    resolved = path.resolve()
    return any(
        resolved == exc.resolve() or exc.resolve() in resolved.parents
        for exc in EXCLUDED_PATHS
    )


def _extract_date_from_filename(filename: str) -> str:
    """Try to extract ISO date from filenames like 2026-03-17-morning.md."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})", filename)
    return match.group(1) if match else ""


def _extract_participant_from_conversation(
    body: str,
    metadata: dict[str, str],
) -> str:
    """Try to identify conversation participant from metadata or content."""
    if "type" in metadata:
        return metadata["type"]
    return ""


def chunk_file(path: Path) -> list[ChunkMeta]:
    """Chunk a file into indexable pieces with metadata.

    Args:
        path: Absolute path to the content file.

    Returns:
        List of chunks with metadata. Empty for excluded paths or
        unrecognized types.
    """
    if _is_excluded(path):
        logger.debug("Skipping excluded path: %s", path)
        return []

    source_type = _detect_source_type(path)
    if source_type is None:
        logger.debug("Unknown source type for: %s", path)
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read file: %s", path)
        return []

    if not content.strip():
        return []

    metadata, body = _parse_frontmatter(content)
    title = metadata.get("title", path.stem)
    date = metadata.get("date", _extract_date_from_filename(path.name))
    # Strip timestamp portions from date if present
    if "T" in date:
        date = date.split("T")[0]

    rel_path = _relative_path(path)
    extra: dict[str, Any] = {}

    if source_type == SourceType.THOUGHT:
        extra["mood"] = metadata.get("mood", "")
        session_match = re.search(r"\d{4}-\d{2}-\d{2}-(.+)\.md$", path.name)
        extra["session_type"] = session_match.group(1) if session_match else ""
        raw_sections = _split_by_separators(body)

    elif source_type == SourceType.DREAM:
        extra["dream_type"] = metadata.get("type", "")
        raw_sections = [(0, len(body.split("\n")) - 1, body)]

    elif source_type == SourceType.ESSAY:
        raw_sections = _split_by_headers(body)

    elif source_type in (SourceType.LETTER, SourceType.SCORE):
        raw_sections = [(0, len(body.split("\n")) - 1, body)]

    elif source_type == SourceType.CONVERSATION:
        extra["participant"] = _extract_participant_from_conversation(
            body,
            metadata,
        )
        raw_sections = _split_by_speaker_turn(body)

    elif source_type == SourceType.MEMORY:
        raw_sections = _split_by_headers(body)

    else:
        raw_sections = [(0, len(body.split("\n")) - 1, body)]

    sections = _maybe_split_large(raw_sections)

    # Calculate frontmatter offset so line numbers reference the original file
    fm_lines = len(content.split("\n")) - len(body.split("\n"))

    chunks: list[ChunkMeta] = []
    for offset_start, offset_end, text in sections:
        if not text.strip():
            continue
        abs_start = fm_lines + offset_start
        abs_end = fm_lines + offset_end
        chunk_id = _make_chunk_id(rel_path, abs_start)
        chunks.append(
            ChunkMeta(
                chunk_id=chunk_id,
                source_file=rel_path,
                source_type=source_type.value,
                title=title,
                date=date,
                offset_start=abs_start,
                offset_end=abs_end,
                text=text,
                extra=extra,
            ),
        )

    return chunks


def chunk_jar(path: Path) -> list[ChunkMeta]:
    """Chunk memory jar JSON — each entry becomes one chunk.

    Args:
        path: Path to the memories.json file.

    Returns:
        List of chunks, one per jar entry.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read jar file: %s", path)
        return []

    rel_path = _relative_path(path)
    chunks: list[ChunkMeta] = []

    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            continue
        text = entry.get("text", "")
        if not text.strip():
            continue
        date = entry.get("date", "")
        chunk_id = _make_chunk_id(rel_path, i)
        chunks.append(
            ChunkMeta(
                chunk_id=chunk_id,
                source_file=rel_path,
                source_type=SourceType.JAR.value,
                title="Memory Jar",
                date=date,
                offset_start=i,
                offset_end=i,
                text=text,
                extra={},
            ),
        )

    return chunks


def chunk_mailbox(path: Path) -> list[ChunkMeta]:
    """Chunk a mailbox thread JSONL — each message becomes one chunk.

    Args:
        path: Path to a thread.jsonl file.

    Returns:
        List of chunks, one per message line.
    """
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read mailbox file: %s", path)
        return []

    # Extract username from path: mailbox/<username>/thread.jsonl
    username = path.parent.name
    rel_path = _relative_path(path)
    chunks: list[ChunkMeta] = []

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            msg: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue

        body = msg.get("body", "")
        if not body.strip():
            continue

        sender = msg.get("from", "")
        ts = msg.get("ts", "")
        date = ts.split("T")[0] if "T" in ts else ts
        msg_id = msg.get("id", f"line_{i}")

        chunk_id = _make_chunk_id(rel_path, i)
        chunks.append(
            ChunkMeta(
                chunk_id=chunk_id,
                source_file=rel_path,
                source_type=SourceType.MAILBOX.value,
                title=f"Mailbox: {username}",
                date=date,
                offset_start=i,
                offset_end=i,
                text=body,
                extra={
                    "username": username,
                    "sender": sender,
                    "message_id": msg_id,
                },
            ),
        )

    return chunks
