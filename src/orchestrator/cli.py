"""CLI entry point for the session orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from orchestrator.config import (
    CLAUDE_HOME,
    CONVO_DIR,
    ENV_FILE,
    LOG_DIR,
    MAX_TURNS,
    SESSION_TYPES,
    TELEGRAM_TALK_SNAPSHOT_FILE,
    TELEGRAM_TALK_STATE_FILE,
    TRANSCRIPT_DIR,
)
from orchestrator.context import (
    build_correspondence_context,
    gather_all_context,
)
from orchestrator.hooks import build_pipeline
from orchestrator.hooks import git as git_hook
from orchestrator.hooks import snapshot as snapshot_hook
from orchestrator.hooks.snapshot import snapshot_content
from orchestrator.lock import SessionAlreadyRunning, acquire_lock, release_lock
from orchestrator.log import configure_logging
from orchestrator.pipeline import Hook, run_pipeline
from orchestrator.render import PromptRenderer
from orchestrator.session import extract_final_text, run_claude_session

logger = structlog.get_logger()

EST = ZoneInfo("America/New_York")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Claudie session orchestrator",
    )
    parser.add_argument(
        "session_type",
        nargs="?",
        default="morning",
        choices=list(SESSION_TYPES.keys()),
        help="Session type (default: morning)",
    )
    parser.add_argument(
        "message",
        nargs="?",
        default="",
        help="Optional message (visitor message, telegram text, etc.)",
    )
    parser.add_argument(
        "sender_name",
        nargs="?",
        default="dinesh",
        help="Sender name for telegram sessions (default: dinesh)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print system and user prompts without invoking Claude",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=MAX_TURNS,
        help=f"Max turns for Claude CLI (default: {MAX_TURNS})",
    )
    return parser.parse_args(argv)


def _generate_session_id() -> str:
    """Generate session ID from current timestamp."""
    return datetime.now(EST).strftime("%Y%m%d-%H%M%S")


def _setup_log_file(session_id: str) -> Path:
    """Create log file for this session."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"session-{session_id}.log"


async def main_async(args: argparse.Namespace) -> int:
    """Main async orchestrator flow."""
    session_type = SESSION_TYPES[args.session_type]
    session_id = _generate_session_id()
    log_file = _setup_log_file(session_id)
    visitor_msg: str = args.message or ""
    sender_name: str = args.sender_name or "dinesh"

    is_telegram_talk_open = session_type.name == "telegram_talk_open"
    cli_session_id: str | None = str(uuid.uuid4()) if is_telegram_talk_open else None
    telegram_talk_chat_id: str = (
        os.environ.get("TELEGRAM_TALK_CHAT_ID", "") if is_telegram_talk_open else ""
    )

    # Ensure directories exist
    for d in (LOG_DIR, CONVO_DIR, TRANSCRIPT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        configure_logging(log_file=log_file)

    logger.info(
        "session_starting",
        session_type=session_type.name,
        session_id=session_id,
        dry_run=args.dry_run,
    )

    # Gather context
    ctx = await gather_all_context(
        session_type=session_type,
        visitor_msg=visitor_msg,
        sender_name=sender_name,
    )

    # Render prompts
    renderer = PromptRenderer()
    system_prompt = renderer.render_system_prompt(ctx, session_type)

    # Build correspondence context if needed
    letters_context = ""
    if session_type.name == "correspondence" and visitor_msg:
        letters_context = build_correspondence_context(visitor_msg)

    user_prompt = renderer.render_user_prompt(
        session_type=session_type,
        ctx=ctx,
        visitor_msg=visitor_msg,
        sender_name=sender_name,
        letters_context=letters_context,
    )

    if args.dry_run:
        print("=== SYSTEM PROMPT ===")
        print(system_prompt)
        print("=== USER PROMPT ===")
        print(user_prompt)
        return 0

    # Load environment variables
    _load_env()

    # Acquire session lock
    lock_fd: int | None = None
    try:
        lock_fd = acquire_lock()
    except SessionAlreadyRunning:
        logger.error("session_already_running")
        return 1

    try:
        # Log session start
        with log_file.open("a", encoding="utf-8") as lf:
            lf.write(f"=== Session started: {datetime.now(EST)} ===\n")
            lf.write(f"Type: {session_type.name}\n")
            lf.write(f"Log: {log_file}\n")

        # Snapshot content before session
        before_snapshot = snapshot_content()

        # Snapshot visitors present at session start — the visitors_archive
        # hook will sweep exactly these files after the session, leaving any
        # mid-session arrivals untouched for the next run.
        visitors_dir = CLAUDE_HOME / "visitors"
        visitors_at_start: list[Path] = (
            sorted(visitors_dir.glob("*.md")) if visitors_dir.exists() else []
        )

        # Save conversation prompt (for session types that track conversations)
        convo_file: Path | None = None
        if session_type.save_conversation and visitor_msg:
            convo_file = CONVO_DIR / f"{session_id}.md"
            convo_file.write_text(
                f"---\n"
                f'date: "{datetime.now(EST).isoformat()}"\n'
                f'type: "{session_type.name}"\n'
                f"---\n\n"
                f"## Message\n\n{visitor_msg}\n",
                encoding="utf-8",
            )
            _chown_claude(convo_file)

        # Run Claude session
        result = await run_claude_session(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            session_type=session_type,
            session_id=session_id,
            log_file=log_file,
            max_turns=args.max_turns,
            cli_session_id=cli_session_id,
        )
        result.convo_file = convo_file
        result.before_snapshot = before_snapshot
        result.visitors_at_start = visitors_at_start

        # For telegram_talk_open: capture greeting before the stream file is cleaned,
        # then run a minimal pipeline (revalidation + git). The talk itself is
        # live afterwards — mood/resonance/etc. run at /end-talk instead.
        if is_telegram_talk_open:
            greeting, _claude_sid = extract_final_text(result.stream_file)
            hooks = [
                Hook("revalidation", [], snapshot_hook.run),
                Hook("git", ["revalidation"], git_hook.run),
            ]
            await run_pipeline(hooks, result)

            _write_telegram_talk_state(
                session_id=cli_session_id or "",
                chat_id=telegram_talk_chat_id,
                sender=sender_name,
                greeting=greeting,
            )
            _write_telegram_talk_snapshot(before_snapshot)
        else:
            # Run full post-session pipeline
            hooks = build_pipeline()
            await run_pipeline(hooks, result)

        # Log completion
        with log_file.open("a", encoding="utf-8") as lf:
            lf.write(
                f"=== Session ended: {datetime.now(EST)}, "
                f"exit code: {result.exit_code} ===\n"
            )

        # Clean up stream file
        if result.stream_file.exists():
            result.stream_file.unlink()

        return result.exit_code
    finally:
        if lock_fd is not None:
            release_lock(lock_fd)


def _load_env() -> None:
    """Load environment variables from .env file."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key:
                __import__("os").environ.setdefault(key, value)


def _chown_claude(path: Path) -> None:
    """Set file ownership to root:claude with group read."""
    import grp
    import os

    try:
        claude_gid = grp.getgrnam("claude").gr_gid
        os.chown(str(path), 0, claude_gid)
        path.chmod(0o640)
    except (KeyError, PermissionError, OSError):
        pass


def _write_telegram_talk_state(
    session_id: str,
    chat_id: str,
    sender: str,
    greeting: str,
) -> None:
    """Write telegram-talk.json state file (chmod so claude user can update it)."""
    now = datetime.now(EST).isoformat()
    state = {
        "active": True,
        "session_id": session_id,
        "sender": sender,
        "chat_id": chat_id,
        "started_at": now,
        "last_turn_at": now,
        "greeting": greeting,
    }
    TELEGRAM_TALK_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TELEGRAM_TALK_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    with contextlib.suppress(OSError):
        TELEGRAM_TALK_STATE_FILE.chmod(0o664)


def _write_telegram_talk_snapshot(before_snapshot: dict[str, float]) -> None:
    """Persist the pre-open snapshot so /end-talk can diff against it."""
    TELEGRAM_TALK_SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    TELEGRAM_TALK_SNAPSHOT_FILE.write_text(
        json.dumps(before_snapshot), encoding="utf-8"
    )
    with contextlib.suppress(OSError):
        TELEGRAM_TALK_SNAPSHOT_FILE.chmod(0o664)


def main() -> None:
    """Synchronous entry point."""
    args = parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
