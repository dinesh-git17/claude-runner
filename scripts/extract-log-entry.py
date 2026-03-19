#!/usr/bin/env python3
"""Extract structured log entry from Claude Code stream-json JSONL."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CLAUDE_HOME_PREFIX: str = "/claude-home/"
SUMMARY_MAX_LENGTH: int = 200
COMPACT_JSON_SEPARATORS: tuple[str, str] = (",", ":")

FILTERED_READ_PREFIXES: tuple[str, ...] = (
    "/claude-home/memory/",
    "/claude-home/CLAUDE.md",
    "/claude-home/prompt/",
)

VALID_SESSION_TYPES: frozenset[str] = frozenset(
    {
        "morning",
        "midmorning",
        "noon",
        "afternoon",
        "dusk",
        "evening",
        "midnight",
        "late_night",
        "visit",
        "custom",
    }
)

WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit"})
READ_TOOL: str = "Read"

_LOG: logging.Logger = logging.getLogger(__name__)


def _out(text: str) -> None:
    """Write text to stdout."""
    sys.stdout.write(text)


def _err(text: str) -> None:
    """Write text to stderr."""
    sys.stderr.write(text)


@dataclass(frozen=True)
class TokenUsage:
    """Token counts from the session result."""

    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_create: int

    def to_dict(self) -> dict[str, int]:
        """Serialize to compact key names."""
        return {
            "in": self.input_tokens,
            "out": self.output_tokens,
            "cache_read": self.cache_read,
            "cache_create": self.cache_create,
        }


@dataclass(frozen=True)
class LogEntry:
    """Structured session log entry."""

    timestamp: str
    session: str
    session_id: str
    duration_s: int
    turns: int
    cost_usd: float
    tokens: TokenUsage
    tools: dict[str, int]
    files_written: list[str]
    files_read: list[str]
    summary: str

    def to_dict(self) -> dict[str, object]:
        """Serialize to the log.jsonl line format."""
        return {
            "t": self.timestamp,
            "session": self.session,
            "session_id": self.session_id,
            "duration_s": self.duration_s,
            "turns": self.turns,
            "cost_usd": round(self.cost_usd, 2),
            "tokens": self.tokens.to_dict(),
            "tools": self.tools,
            "files_written": self.files_written,
            "files_read": self.files_read,
            "summary": self.summary,
        }


def _parse_jsonl(stream_path: Path) -> list[dict[str, Any]]:
    """Read JSONL file, returning parsed lines and skipping malformed ones."""
    lines: list[dict[str, Any]] = []
    with stream_path.open("r", encoding="utf-8") as fh:
        for line_num, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                lines.append(json.loads(stripped))
            except json.JSONDecodeError:
                _LOG.warning("Skipping malformed JSON at line %d", line_num)
    return lines


def _relativize(absolute_path: str) -> str:
    """Strip /claude-home/ prefix for readability."""
    if absolute_path.startswith(CLAUDE_HOME_PREFIX):
        return absolute_path[len(CLAUDE_HOME_PREFIX) :]
    return absolute_path


def _is_filtered_read(path: str) -> bool:
    """Check if a read path should be excluded from interesting reads."""
    return any(path.startswith(prefix) for prefix in FILTERED_READ_PREFIXES)


def _extract_tool_usage(
    lines: list[dict[str, Any]],
) -> tuple[dict[str, int], list[str], list[str]]:
    """Extract tool counts, files written, and files read from assistant messages.

    Returns:
        Tuple of (tool_counts, sorted_files_written, sorted_files_read).
    """
    tool_counts: dict[str, int] = {}
    written: set[str] = set()
    read: set[str] = set()

    for line in lines:
        if line.get("type") != "assistant":
            continue
        content_blocks: list[dict[str, Any]] = line.get("message", {}).get(
            "content", []
        )
        for block in content_blocks:
            if block.get("type") != "tool_use":
                continue

            name: str = block.get("name", "Unknown")
            tool_counts[name] = tool_counts.get(name, 0) + 1

            file_path: str = block.get("input", {}).get("file_path", "")
            if not file_path:
                continue

            if name in WRITE_TOOLS:
                written.add(_relativize(file_path))
            elif name == READ_TOOL and not _is_filtered_read(file_path):
                read.add(_relativize(file_path))

    return tool_counts, sorted(written), sorted(read)


def _find_result(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the last result-type line in the JSONL output."""
    for line in reversed(lines):
        if line.get("type") == "result":
            return line
    return None


def _find_session_id_from_init(lines: list[dict[str, Any]]) -> str:
    """Extract session_id from the system init line as fallback."""
    for line in lines:
        if line.get("type") == "system":
            sid: str = str(line.get("session_id", ""))
            if sid:
                return sid
    return ""


def _collapse_summary(text: str) -> str:
    """Collapse whitespace and truncate to SUMMARY_MAX_LENGTH."""
    collapsed = " ".join(text.split())
    if len(collapsed) > SUMMARY_MAX_LENGTH:
        return collapsed[:SUMMARY_MAX_LENGTH] + "..."
    return collapsed


def _extract_tokens(result: dict[str, Any]) -> TokenUsage:
    """Extract token usage from the result line."""
    usage: dict[str, Any] = result.get("usage", {})
    return TokenUsage(
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_read=usage.get("cache_read_input_tokens", 0),
        cache_create=usage.get("cache_creation_input_tokens", 0),
    )


def build_log_entry(stream_path: Path, session_type: str) -> LogEntry:
    """Parse stream-json file and build a structured log entry.

    Args:
        stream_path: Path to the raw JSONL stream file.
        session_type: Session type identifier (morning, evening, etc.).

    Returns:
        A LogEntry with all extracted fields.
    """
    lines = _parse_jsonl(stream_path)
    result = _find_result(lines)
    tool_counts, files_written, files_read = _extract_tool_usage(lines)

    now = datetime.now(UTC).astimezone()
    timestamp = now.isoformat(timespec="seconds")

    if result is not None:
        session_id = str(result.get("session_id", ""))
        duration_s = int(result.get("duration_ms", 0)) // 1000
        turns = int(result.get("num_turns", 0))
        cost_usd = float(result.get("total_cost_usd", 0.0))
        tokens = _extract_tokens(result)
        summary = _collapse_summary(str(result.get("result", "")))
    else:
        _LOG.warning("No result line found in %s", stream_path)
        session_id = ""
        duration_s = 0
        turns = 0
        cost_usd = 0.0
        tokens = TokenUsage(0, 0, 0, 0)
        summary = "(no result line)"

    if not session_id:
        session_id = _find_session_id_from_init(lines)

    return LogEntry(
        timestamp=timestamp,
        session=session_type,
        session_id=session_id,
        duration_s=duration_s,
        turns=turns,
        cost_usd=cost_usd,
        tokens=tokens,
        tools=tool_counts,
        files_written=files_written,
        files_read=files_read,
        summary=summary,
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Extract structured log entry from Claude Code stream-json.",
    )
    parser.add_argument(
        "stream_file",
        type=Path,
        help="Path to the raw stream-json JSONL file.",
    )
    parser.add_argument(
        "session_type",
        type=str,
        help="Session type (morning, evening, visit, etc.).",
    )
    return parser


def main() -> None:
    """Extract log entry from stream-json and write JSON line to stdout."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    parser = _build_parser()
    args = parser.parse_args()

    stream_path: Path = args.stream_file
    session_type: str = args.session_type

    if not stream_path.is_file():
        msg = f"Stream file not found: {stream_path}\n"
        _err(msg)
        sys.exit(1)

    if session_type not in VALID_SESSION_TYPES:
        _LOG.warning("Unrecognized session type: %s", session_type)

    entry = build_log_entry(stream_path, session_type)
    _out(
        json.dumps(
            entry.to_dict(), separators=COMPACT_JSON_SEPARATORS, ensure_ascii=False
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
