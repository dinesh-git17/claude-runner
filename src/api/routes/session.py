"""Live session status and streaming endpoints."""

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from datetime import UTC
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

logger = structlog.get_logger()

router = APIRouter(prefix="/session", tags=["session"])

# Patterns to redact from streamed content
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9_-]+"),
    re.compile(r"sk_[a-zA-Z0-9_-]{20,}"),
    re.compile(r"ANTHROPIC_API_KEY=[^\s]+"),
    re.compile(r"API_KEY=[^\s]+"),
    re.compile(r"TRUSTED_API_KEYS=[^\s]+"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_-]{20,}"),
]

# Path prefixes whose Read calls and results are hidden from the live stream
_SUPPRESSED_READ_PREFIXES = (
    "/claude-home/memory/",
    "/claude-home/telegram/",
)


def _redact_secrets(text: str) -> str:
    """Redact API keys and tokens from text."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _check_suppression(raw: dict[str, Any], suppressed_ids: set[str]) -> bool:
    """Check if a raw stream event should be suppressed.

    Tracks tool_use IDs for Read calls targeting private paths,
    then suppresses their corresponding tool_result events.

    Returns True if the event should be hidden from the stream.
    """
    event_type = raw.get("type")
    message = raw.get("message", {})
    content_blocks = message.get("content", [])

    if event_type == "assistant":
        for block in content_blocks:
            if block.get("type") != "tool_use":
                continue
            if block.get("name") not in ("Read", "read"):
                continue
            file_path = block.get("input", {}).get(
                "file_path", block.get("input", {}).get("path", "")
            )
            if file_path.startswith(_SUPPRESSED_READ_PREFIXES):
                suppressed_ids.add(block["id"])
                return True

    if event_type == "user":
        for block in content_blocks:
            if block.get("type") != "tool_result":
                continue
            tool_id = block.get("tool_use_id", "")
            if tool_id in suppressed_ids:
                suppressed_ids.discard(tool_id)
                return True

    return False


def _parse_stream_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a raw stream-json line into a filtered SSE event.

    Returns None if the event should be skipped.
    """
    event_type = raw.get("type")

    if event_type == "system":
        return {
            "event": "session.start",
            "data": {
                "session_id": raw.get("session_id", ""),
                "model": raw.get("model", ""),
                "turn": 0,
            },
        }

    if event_type == "assistant":
        message = raw.get("message", {})
        content_blocks = message.get("content", [])

        for block in content_blocks:
            if block.get("type") == "text":
                return {
                    "event": "session.text",
                    "data": {
                        "text": _redact_secrets(block.get("text", "")),
                    },
                }
            if block.get("type") == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})

                # Build a human-readable summary
                summary = _summarize_tool_call(tool_name, tool_input)

                return {
                    "event": "session.tool",
                    "data": {
                        "tool_name": tool_name,
                        "summary": summary,
                        "input": _redact_secrets(
                            json.dumps(tool_input, ensure_ascii=False)[:500]
                        ),
                    },
                }

    if event_type == "user":
        message = raw.get("message", {})
        content_blocks = message.get("content", [])

        for block in content_blocks:
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    # Extract text from content blocks
                    content = " ".join(
                        c.get("text", "") for c in content if c.get("type") == "text"
                    )
                content_str = str(content)[:2000]

                return {
                    "event": "session.tool_result",
                    "data": {
                        "tool_name": block.get("name", ""),
                        "content": _redact_secrets(content_str),
                        "is_error": block.get("is_error", False),
                    },
                }

    if event_type == "result":
        return {
            "event": "session.end",
            "data": {
                "duration_ms": raw.get("duration_ms", 0),
                "num_turns": raw.get("num_turns", 0),
                "cost_usd": raw.get("cost_usd", 0),
                "result": _redact_secrets(str(raw.get("result", ""))[:500]),
            },
        }

    return None


def _summarize_tool_call(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Create a human-readable summary of a tool call."""
    if tool_name in ("Read", "read"):
        path = tool_input.get("file_path", tool_input.get("path", ""))
        return f"Reading {_short_path(path)}"

    if tool_name in ("Write", "write"):
        path = tool_input.get("file_path", tool_input.get("path", ""))
        return f"Writing {_short_path(path)}"

    if tool_name in ("Edit", "edit"):
        path = tool_input.get("file_path", tool_input.get("path", ""))
        return f"Editing {_short_path(path)}"

    if tool_name in ("Bash", "bash"):
        cmd = tool_input.get("command", "")
        desc = tool_input.get("description", "")
        if desc:
            return str(desc)
        return f"Running: {cmd[:80]}"

    if tool_name in ("Glob", "glob"):
        pattern = tool_input.get("pattern", "")
        return f"Searching for {pattern}"

    if tool_name in ("Grep", "grep"):
        pattern = tool_input.get("pattern", "")
        return f"Searching for '{pattern}'"

    return f"Using {tool_name}"


def _short_path(path: str) -> str:
    """Shorten a path for display by removing /claude-home prefix."""
    return path.replace("/claude-home/", "/")


@router.get("/status")
async def session_status(request: Request) -> JSONResponse:
    """Return current session status."""
    settings = request.app.state.settings
    status_path = Path(settings.session_status_path)

    if not status_path.exists():
        return JSONResponse({"active": False})

    try:
        data = json.loads(status_path.read_text())

        if data.get("active") and data.get("started_at"):
            from datetime import datetime

            try:
                started = datetime.fromisoformat(data["started_at"])
                now = datetime.now(UTC)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                data["duration_seconds"] = int((now - started).total_seconds())
            except (ValueError, TypeError):
                data["duration_seconds"] = 0

        return JSONResponse(data)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("session_status_read_error", error=str(e))
        return JSONResponse({"active": False})


@router.get("/stream")
async def session_stream(request: Request) -> EventSourceResponse:
    """Stream live session events via SSE."""
    settings = request.app.state.settings
    stream_path = Path(settings.session_stream_path)
    poll_interval = settings.session_poll_interval

    async def _generate() -> AsyncGenerator[ServerSentEvent, None]:
        pos = 0
        heartbeat_counter = 0
        suppressed_ids: set[str] = set()

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            try:
                if stream_path.exists() and stream_path.stat().st_size > pos:
                    with stream_path.open() as f:
                        f.seek(pos)
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    raw = json.loads(line)
                                    if _check_suppression(raw, suppressed_ids):
                                        continue
                                    parsed = _parse_stream_event(raw)
                                    if parsed:
                                        yield ServerSentEvent(
                                            event=parsed["event"],
                                            data=json.dumps(
                                                parsed["data"],
                                                ensure_ascii=False,
                                            ),
                                        )
                                except json.JSONDecodeError:
                                    pass
                        pos = f.tell()
            except OSError:
                pass

            await asyncio.sleep(poll_interval)

            # Heartbeat every ~15 seconds (15 / 0.2 = 75 polls)
            heartbeat_counter += 1
            if heartbeat_counter >= 75:
                heartbeat_counter = 0
                yield ServerSentEvent(
                    event="heartbeat",
                    data=json.dumps({"ts": int(time.time())}),
                )

    return EventSourceResponse(
        _generate(),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
