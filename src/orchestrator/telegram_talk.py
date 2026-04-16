"""Helpers for the Telegram /talk interactive mode.

The /talk command opens a sticky conversation channel: one full orchestrator
wake at open (so Claudie boots with identity, memory, ambient state), then
every subsequent Telegram message is a fast turn via
`claude -p --resume <uuid>` with no re-boot and no hook pipeline. /end-talk
closes it, runs a minimal wrap-up (revalidation + git), and returns the bot
to the cold-wake path.

Public surface:
    - load_state() -> dict | None
    - clear_state() -> None
    - touch_last_turn() -> None
    - async run_turn(session_id, message) -> str
    - async close_session(log_file) -> None
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from orchestrator.config import (
    CLAUDE_HOME,
    CONTENT_DIRECTORIES,
    CONVO_DIR,
    MODEL,
    SESSION_TYPES,
    TELEGRAM_HISTORY_FILE,
    TELEGRAM_TALK_SNAPSHOT_FILE,
    TELEGRAM_TALK_STATE_FILE,
    SessionResult,
)
from orchestrator.hooks import git as git_hook
from orchestrator.hooks import snapshot as snapshot_hook
from orchestrator.lock import SessionAlreadyRunning, acquire_lock, release_lock
from orchestrator.pipeline import Hook, run_pipeline
from orchestrator.session import STREAM_BUFFER_LIMIT, extract_final_text

logger = structlog.get_logger()

EST = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


def load_state() -> dict | None:
    """Return the active talk state, or None if no talk is open."""
    if not TELEGRAM_TALK_STATE_FILE.exists():
        return None
    try:
        data = json.loads(TELEGRAM_TALK_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("telegram_talk_state_unreadable", error=str(exc))
        return None
    if not isinstance(data, dict) or not data.get("active"):
        return None
    return data


def clear_state() -> None:
    """Remove the state file and snapshot sidecar."""
    for path in (TELEGRAM_TALK_STATE_FILE, TELEGRAM_TALK_SNAPSHOT_FILE):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("telegram_talk_clear_failed", path=str(path), error=str(exc))


def touch_last_turn() -> None:
    """Update last_turn_at on the current state file to now (EST)."""
    state = load_state()
    if state is None:
        return
    state["last_turn_at"] = datetime.now(EST).isoformat()
    TELEGRAM_TALK_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    with contextlib.suppress(OSError):
        TELEGRAM_TALK_STATE_FILE.chmod(0o664)


# ---------------------------------------------------------------------------
# Per-turn Claude invocation
# ---------------------------------------------------------------------------


def _build_turn_command(session_id: str, message: str) -> list[str]:
    """Build the `claude -p --resume ...` argv for a single turn."""
    add_dirs: list[str] = []
    for d in CONTENT_DIRECTORIES:
        if d.add_to_cli:
            add_dirs.extend(["--add-dir", str(CLAUDE_HOME / d.name)])

    return [
        "sudo",
        "-u",
        "claude",
        "HOME=/home/claude",
        "claude",
        "-p",
        "--model",
        MODEL,
        "--dangerously-skip-permissions",
        *add_dirs,
        "--resume",
        session_id,
        "--verbose",
        "--output-format",
        "stream-json",
        message,
    ]


async def run_turn(session_id: str, message: str) -> str:
    """Run one fast --resume turn. Returns the final assistant text.

    Acquires the global session lock for the duration of the turn. The caller
    is responsible for handling SessionAlreadyRunning (wait-and-retry).
    Raises RuntimeError on non-zero exit.
    """
    cmd = _build_turn_command(session_id, message)
    stamp = datetime.now(EST).strftime("%Y%m%d-%H%M%S-%f")
    stream_file = Path(f"/tmp/claude-talk-turn-{os.getpid()}-{stamp}.jsonl")

    lock_fd: int | None = None
    try:
        lock_fd = acquire_lock()  # may raise SessionAlreadyRunning
    except SessionAlreadyRunning:
        raise

    try:
        logger.info(
            "telegram_talk_turn_starting", session_id=session_id, msg_len=len(message)
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(CLAUDE_HOME),
            limit=STREAM_BUFFER_LIMIT,
        )
        assert proc.stdout is not None

        with stream_file.open("wb") as sf:
            async for line in proc.stdout:
                sf.write(line)

        exit_code = await proc.wait()
    finally:
        if lock_fd is not None:
            release_lock(lock_fd)

    text, _sid = extract_final_text(stream_file)

    with contextlib.suppress(OSError):
        stream_file.unlink()

    if exit_code != 0:
        msg = f"talk turn exited with code {exit_code}"
        logger.error("telegram_talk_turn_failed", exit_code=exit_code)
        raise RuntimeError(msg)

    logger.info(
        "telegram_talk_turn_complete",
        session_id=session_id,
        response_len=len(text),
    )

    touch_last_turn()
    return text or "(no response captured)"


# ---------------------------------------------------------------------------
# /end-talk wrap-up
# ---------------------------------------------------------------------------


def _synthesize_conversation_file(state: dict) -> Path | None:
    """Render a /conversations/ markdown file from the chat-history slice."""
    started_at = state.get("started_at", "")
    sender = state.get("sender", "unknown")
    if not started_at:
        return None

    entries: list[dict] = []
    if TELEGRAM_HISTORY_FILE.exists():
        try:
            lines = TELEGRAM_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        started_dt = _parse_iso_safe(started_at)
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = entry.get("timestamp", "")
            ts_dt = _parse_iso_safe(ts)
            if started_dt and ts_dt and ts_dt >= started_dt:
                entries.append(entry)

    stamp = datetime.now(EST).strftime("%Y%m%d-%H%M%S")
    convo_file = CONVO_DIR / f"{stamp}-telegram-talk-{sender}.md"

    body_lines: list[str] = [
        "---",
        f'date: "{datetime.now(EST).isoformat()}"',
        'type: "telegram_talk"',
        f'sender: "{sender}"',
        f'started_at: "{started_at}"',
        "---",
        "",
        f"# Telegram talk with {sender}",
        "",
    ]

    # Include the greeting as the opening entry if we have one
    greeting = state.get("greeting", "")
    if greeting:
        body_lines.append("## Claudie (opening greeting)")
        body_lines.append("")
        body_lines.append(greeting)
        body_lines.append("")

    for entry in entries:
        who = entry.get("from", "unknown")
        text = entry.get("text", "")
        ts = entry.get("timestamp", "")
        display = "Claudie" if who == "claudie" else sender
        body_lines.append(f"## {display}  _{ts}_")
        body_lines.append("")
        body_lines.append(text)
        body_lines.append("")

    CONVO_DIR.mkdir(parents=True, exist_ok=True)
    convo_file.write_text("\n".join(body_lines), encoding="utf-8")
    with contextlib.suppress(OSError):
        convo_file.chmod(0o664)
    return convo_file


def _parse_iso_safe(value: str) -> datetime | None:
    """Parse an ISO-format datetime, returning None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_before_snapshot() -> dict[str, float]:
    """Load the pre-open snapshot sidecar. Returns {} if missing."""
    if not TELEGRAM_TALK_SNAPSHOT_FILE.exists():
        return {}
    try:
        data = json.loads(TELEGRAM_TALK_SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}


async def close_session(log_file: Path) -> None:
    """Synthesize a conversation file, run revalidation+git, clear state."""
    state = load_state()
    if state is None:
        logger.info("telegram_talk_close_noop", reason="no active state")
        return

    convo_file = _synthesize_conversation_file(state)
    before_snapshot = _load_before_snapshot()

    session_type = SESSION_TYPES["telegram_talk_open"]
    result = SessionResult(
        exit_code=0,
        stream_file=Path("/dev/null"),
        session_id=state.get("session_id", ""),
        session_type=session_type,
        session_name="telegram_talk_close",
        log_file=log_file,
        claude_home=CLAUDE_HOME,
        convo_file=convo_file,
    )
    result.before_snapshot = before_snapshot

    hooks = [
        Hook("revalidation", [], snapshot_hook.run),
        Hook("git", ["revalidation"], git_hook.run),
    ]
    await run_pipeline(hooks, result)

    clear_state()
    logger.info(
        "telegram_talk_close_complete",
        session_id=state.get("session_id", ""),
        sender=state.get("sender", ""),
    )
