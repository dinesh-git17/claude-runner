"""Claude Code CLI subprocess management and session lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import structlog

from orchestrator.config import (
    CLAUDE_HOME,
    CONTENT_DIRECTORIES,
    DATA_DIR,
    LIVE_STREAM_FILE,
    MODEL,
    SESSION_STATUS_FILE,
    SessionResult,
    SessionType,
)

logger = structlog.get_logger()


def _write_session_status(active: bool, **extra: str) -> None:
    """Write session-status.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"active": active}
    payload.update(extra)
    SESSION_STATUS_FILE.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    SESSION_STATUS_FILE.chmod(0o644)


def _build_cli_command(
    system_prompt: str,
    user_prompt: str,
    max_turns: int,
) -> list[str]:
    """Build the claude CLI command with all flags."""
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
        "--max-turns",
        str(max_turns),
        "--verbose",
        "--output-format",
        "stream-json",
        "--system-prompt",
        system_prompt,
        user_prompt,
    ]


async def run_claude_session(
    system_prompt: str,
    user_prompt: str,
    session_type: SessionType,
    session_id: str,
    log_file: Path,
    max_turns: int,
) -> SessionResult:
    """Invoke Claude Code CLI, stream output, return result."""
    stream_file = Path(f"/tmp/claude-stream-{os.getpid()}.jsonl")

    # Set session status to active (unless private session type)
    if session_type.live_stream:
        _write_session_status(
            active=True,
            type=session_type.name,
            session_id=session_id,
        )
        LIVE_STREAM_FILE.write_text("")
        LIVE_STREAM_FILE.chmod(0o644)

    cmd = _build_cli_command(system_prompt, user_prompt, max_turns)
    logger.info("session_starting_cli", cmd_length=len(cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(CLAUDE_HOME),
        )

        assert proc.stdout is not None  # guaranteed by PIPE

        with stream_file.open("wb") as sf:
            if session_type.live_stream:
                with LIVE_STREAM_FILE.open("wb") as lf:
                    async for line in proc.stdout:
                        sf.write(line)
                        lf.write(line)
                        lf.flush()
            else:
                async for line in proc.stdout:
                    sf.write(line)

        exit_code = await proc.wait()
    finally:
        # Always clear session status
        if session_type.live_stream:
            _write_session_status(active=False)
            LIVE_STREAM_FILE.write_text("")

    # Extract result JSON for log file
    if stream_file.exists():
        for raw_line in stream_file.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
                if data.get("type") == "result":
                    with log_file.open("a", encoding="utf-8") as lf:
                        lf.write(raw_line + "\n")
            except json.JSONDecodeError:
                continue

    logger.info(
        "session_complete",
        exit_code=exit_code,
        session_type=session_type.name,
        session_id=session_id,
    )

    return SessionResult(
        exit_code=exit_code,
        stream_file=stream_file,
        session_id=session_id,
        session_type=session_type,
        session_name=session_type.name,
        log_file=log_file,
        claude_home=CLAUDE_HOME,
    )
