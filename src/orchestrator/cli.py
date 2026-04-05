"""CLI entry point for the session orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from orchestrator.config import (
    CONVO_DIR,
    ENV_FILE,
    LOG_DIR,
    MAX_TURNS,
    SESSION_TYPES,
    TRANSCRIPT_DIR,
)
from orchestrator.context import (
    build_correspondence_context,
    gather_all_context,
)
from orchestrator.hooks import build_pipeline
from orchestrator.hooks.snapshot import snapshot_content
from orchestrator.lock import SessionAlreadyRunning, acquire_lock, release_lock
from orchestrator.log import configure_logging
from orchestrator.pipeline import run_pipeline
from orchestrator.render import PromptRenderer
from orchestrator.session import run_claude_session

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
        )
        result.convo_file = convo_file
        result.before_snapshot = before_snapshot

        # Run post-session pipeline
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


def main() -> None:
    """Synchronous entry point."""
    args = parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
