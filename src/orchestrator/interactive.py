"""Interactive REPL entry point for Claudie.

Parallel to orchestrator.cli — reuses context gathering, lock, and system
prompt rendering, but launches the Claude Code CLI in interactive mode
(no -p) so Dinesh can have a live terminal conversation with Claudie.

Usage:
    ssh -t claudehome /claude-home/runner/talk.sh
    ssh -t claudehome /claude-home/runner/talk.sh --dry-run
    ssh -t claudehome /claude-home/runner/talk.sh --continue
    ssh -t claudehome /claude-home/runner/talk.sh --session-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from orchestrator.config import (
    CLAUDE_HOME,
    CONTENT_DIRECTORIES,
    CRON_HOURS,
    ENV_FILE,
    LOG_DIR,
    MODEL,
    SESSION_TYPES,
    SessionResult,
)
from orchestrator.context import gather_all_context
from orchestrator.hooks import git as git_hook
from orchestrator.hooks import snapshot as snapshot_hook
from orchestrator.hooks.snapshot import snapshot_content
from orchestrator.lock import SessionAlreadyRunning, acquire_lock, release_lock
from orchestrator.log import configure_logging
from orchestrator.pipeline import Hook, run_pipeline
from orchestrator.render import PromptRenderer

logger = structlog.get_logger()

EST = ZoneInfo("America/New_York")
CRON_BUFFER_MINUTES = 10


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for talk mode."""
    parser = argparse.ArgumentParser(
        prog="talk",
        description="Interactive REPL conversation with Claudie",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Gather context, render the system prompt, print it and the argv, then exit",
    )
    parser.add_argument(
        "--no-cron-check",
        action="store_true",
        help="Skip the cron-slot-proximity warning",
    )
    parser.add_argument(
        "--continue",
        "-c",
        dest="continue_last",
        action="store_true",
        help="Pass -c to claude to continue the most recent conversation",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="Pass --session-id <uuid> to claude to resume a specific session",
    )
    return parser.parse_args(argv)


def _generate_session_id() -> str:
    """Generate session id from current timestamp (EST)."""
    return datetime.now(EST).strftime("%Y%m%d-%H%M%S")


def _load_env() -> None:
    """Load environment variables from the orchestrator's .env file."""
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
                os.environ.setdefault(key, value)


def _minutes_until_next_cron_slot() -> tuple[int, int]:
    """Return (minutes_until_next_slot, next_slot_hour) in EST."""
    now = datetime.now(EST)
    now_minutes = now.hour * 60 + now.minute
    best_delta = 24 * 60
    best_hour = sorted(CRON_HOURS)[0]
    for slot_hour in sorted(CRON_HOURS):
        slot_minutes = slot_hour * 60
        delta = slot_minutes - now_minutes
        if delta <= 0:
            delta += 24 * 60
        if delta < best_delta:
            best_delta = delta
            best_hour = slot_hour
    return best_delta, best_hour


_CRON_SLOT_LABELS: dict[int, str] = {
    0: "midnight",
    3: "late_night",
    6: "morning",
    9: "midmorning",
    12: "noon",
    15: "afternoon",
    18: "dusk",
    21: "evening",
}


def _cron_buffer_check(skip: bool) -> bool:
    """Warn if a cron slot is imminent. Returns True if the user wants to proceed."""
    if skip:
        return True
    minutes, slot_hour = _minutes_until_next_cron_slot()
    if minutes > CRON_BUFFER_MINUTES:
        return True
    label = _CRON_SLOT_LABELS.get(slot_hour, f"{slot_hour}:00")
    print(
        f"\u26a0  {label} session fires in {minutes} minute(s). "
        f"Your chat will hold the session lock and block it.",
        file=sys.stderr,
    )
    try:
        answer = input("Proceed anyway? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer == "y"


def _build_interactive_cmd(
    system_prompt: str,
    continue_last: bool,
    session_id: str,
) -> list[str]:
    """Build the claude CLI argv for interactive mode."""
    add_dirs: list[str] = []
    for d in CONTENT_DIRECTORIES:
        if d.add_to_cli:
            add_dirs.extend(["--add-dir", str(CLAUDE_HOME / d.name)])

    cmd = [
        "sudo",
        "-u",
        "claude",
        "HOME=/home/claude",
        "claude",
        "--model",
        MODEL,
        "--dangerously-skip-permissions",
        *add_dirs,
        "--system-prompt",
        system_prompt,
    ]
    if continue_last:
        cmd.append("-c")
    if session_id:
        cmd.extend(["--session-id", session_id])
    return cmd


async def _run_post_chat_pipeline(
    session_id: str,
    log_file: Path,
    before_snapshot: dict[str, float],
    exit_code: int,
) -> None:
    """Run a minimal post-chat pipeline: revalidation + git."""
    result = SessionResult(
        exit_code=exit_code,
        stream_file=Path("/dev/null"),
        session_id=session_id,
        session_type=SESSION_TYPES["talk"],
        session_name="talk",
        log_file=log_file,
        claude_home=CLAUDE_HOME,
    )
    result.before_snapshot = before_snapshot

    hooks = [
        Hook("revalidation", [], snapshot_hook.run),
        Hook("git", ["revalidation"], git_hook.run),
    ]
    await run_pipeline(hooks, result)


async def main_async(args: argparse.Namespace) -> int:
    """Main async flow for an interactive talk session."""
    # TTY guard — interactive mode requires a terminal
    if not (sys.stdin.isatty() and sys.stdout.isatty()) and not args.dry_run:
        print(
            "talk.sh requires an interactive TTY. "
            "Run via: ssh -t root@157.180.94.145 /claude-home/runner/talk.sh",
            file=sys.stderr,
        )
        return 1

    # Cron buffer warning
    if not args.dry_run and not _cron_buffer_check(args.no_cron_check):
        print("Aborted.", file=sys.stderr)
        return 1

    session_id = _generate_session_id()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"talk-{session_id}.log"

    if not args.dry_run:
        configure_logging(log_file=log_file)

    logger.info("talk_starting", session_id=session_id, dry_run=args.dry_run)

    # Gather context
    session_type = SESSION_TYPES["talk"]
    ctx = await gather_all_context(
        session_type=session_type,
        visitor_msg="",
        sender_name="dinesh",
    )

    # Render system prompt
    renderer = PromptRenderer()
    system_prompt = renderer.render_system_prompt(ctx, session_type)

    # Build CLI command
    cmd = _build_interactive_cmd(system_prompt, args.continue_last, args.session_id)

    if args.dry_run:
        print("=== SYSTEM PROMPT ===")
        print(system_prompt)
        print()
        print("=== ARGV ===")
        print(" ".join(repr(a) if " " in a or "\n" in a else a for a in cmd))
        return 0

    # Load .env for revalidation secret and any other runtime config
    _load_env()

    # Acquire session lock
    lock_fd: int | None = None
    try:
        lock_fd = acquire_lock()
    except SessionAlreadyRunning:
        print(
            "Another Claudie session is already running. Try again in a minute.",
            file=sys.stderr,
        )
        return 1

    chat_start = datetime.now(EST)

    try:
        with log_file.open("a", encoding="utf-8") as lf:
            lf.write(f"=== Talk started: {chat_start.isoformat()} ===\n")

        # Snapshot content before the chat so the revalidation hook can diff
        before_snapshot = snapshot_content()

        # Launch claude interactively — inherits stdio from the TTY
        logger.info("talk_launching_cli")
        try:
            completed = subprocess.run(cmd, check=False)
            exit_code = completed.returncode
        except KeyboardInterrupt:
            exit_code = 130

        chat_end = datetime.now(EST)
        duration = chat_end - chat_start
        duration_str = _format_duration(duration.total_seconds())

        with log_file.open("a", encoding="utf-8") as lf:
            lf.write(
                f"=== Talk ended: {chat_end.isoformat()}, "
                f"exit code: {exit_code}, duration: {duration_str} ===\n"
            )

        logger.info(
            "talk_complete",
            exit_code=exit_code,
            duration_seconds=int(duration.total_seconds()),
        )

        # Minimal post-chat pipeline (revalidation + git) if chat exited cleanly
        if exit_code == 0:
            try:
                await _run_post_chat_pipeline(
                    session_id=session_id,
                    log_file=log_file,
                    before_snapshot=before_snapshot,
                    exit_code=exit_code,
                )
            except Exception as e:
                logger.warning("post_chat_pipeline_failed", error=str(e))

        print(f"\nTalked with Claudie for {duration_str}.", file=sys.stderr)
        return exit_code
    finally:
        if lock_fd is not None:
            release_lock(lock_fd)


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds as 'Hh Mm Ss' or 'Mm Ss' or 'Ss'."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def main() -> None:
    """Synchronous entry point."""
    args = parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
