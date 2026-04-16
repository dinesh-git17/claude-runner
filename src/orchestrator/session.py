"""Claude Code CLI subprocess management and session lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
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

STREAM_BUFFER_LIMIT = 4 * 1024 * 1024  # 4 MB per line


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
    cli_session_id: str | None = None,
) -> tuple[list[str], list[Path]]:
    """Build the claude CLI command with all flags.

    Writes system prompt and user prompt to temp files to avoid
    hitting Linux ARG_MAX / MAX_ARG_STRLEN limits on large prompts.

    Returns:
        Tuple of (command list, list of temp file paths to clean up).
    """
    add_dirs: list[str] = []
    for d in CONTENT_DIRECTORIES:
        if d.add_to_cli:
            add_dirs.extend(["--add-dir", str(CLAUDE_HOME / d.name)])

    # Write prompts to temp files (readable by claude user)
    tmp_files: list[Path] = []

    sys_fd, sys_path = tempfile.mkstemp(prefix="claude-sys-", suffix=".txt")
    os.write(sys_fd, system_prompt.encode("utf-8"))
    os.close(sys_fd)
    Path(sys_path).chmod(0o644)
    tmp_files.append(Path(sys_path))

    usr_fd, usr_path = tempfile.mkstemp(prefix="claude-usr-", suffix=".txt")
    os.write(usr_fd, user_prompt.encode("utf-8"))
    os.close(usr_fd)
    Path(usr_path).chmod(0o644)
    tmp_files.append(Path(usr_path))

    cmd = [
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
    ]
    if cli_session_id:
        cmd.extend(["--session-id", cli_session_id])
    cmd.extend(["--system-prompt", f"@{sys_path}", f"@{usr_path}"])
    return cmd, tmp_files


async def run_claude_session(
    system_prompt: str,
    user_prompt: str,
    session_type: SessionType,
    session_id: str,
    log_file: Path,
    max_turns: int,
    cli_session_id: str | None = None,
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

    cmd, tmp_files = _build_cli_command(
        system_prompt, user_prompt, max_turns, cli_session_id=cli_session_id
    )
    logger.info("session_starting_cli", cmd_length=len(cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(CLAUDE_HOME),
            limit=STREAM_BUFFER_LIMIT,
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
        # Clean up prompt temp files
        for tf in tmp_files:
            tf.unlink(missing_ok=True)

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


def extract_final_text(stream_file: Path) -> tuple[str, str]:
    """Return (final_assistant_text, claude_session_id) from a stream-json file."""
    text = ""
    sid = ""
    if not stream_file.exists():
        return text, sid
    for raw in stream_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get("type") == "result":
            text = data.get("result", "") or text
            sid = data.get("session_id", "") or sid
    return text, sid
