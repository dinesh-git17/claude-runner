"""Hook: commit and push content changes to git."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog

from orchestrator.config import CLAUDE_HOME, GIT_TRACKED, SessionResult
from orchestrator.pipeline import HookResult

logger = structlog.get_logger()
EST = ZoneInfo("America/New_York")


async def _run_git(*args: str) -> tuple[int, str]:
    """Run a git command in CLAUDE_HOME and return (returncode, output)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(CLAUDE_HOME),
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace")


async def run(result: SessionResult) -> HookResult:
    """Stage, commit, and push content changes."""
    start = time.monotonic()

    # Stage tracked directories
    rc, output = await _run_git("add", *GIT_TRACKED)
    if rc != 0:
        logger.warning("git_add_failed", output=output)

    # Check for staged changes
    rc, _ = await _run_git("diff", "--cached", "--quiet")
    if rc == 0:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info("git_no_changes")
        return HookResult("git", "success", elapsed)

    # Commit
    now = datetime.now(EST)
    timestamp = now.strftime("%Y-%m-%d %H:%M %Z")
    commit_msg = (
        f"Session: {result.session_type.name} - {timestamp}\n\n"
        f"Co-Authored-By: Dinesh <dinesh-git17@users.noreply.github.com>"
    )

    rc, output = await _run_git("commit", "-m", commit_msg)
    if rc != 0:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.warning("git_commit_failed", output=output)
        return HookResult("git", "failed", elapsed, output.strip())

    logger.info("git_committed", message=commit_msg.split("\n", maxsplit=1)[0])

    # Push
    rc, output = await _run_git("push", "origin", "main")
    if rc != 0:
        logger.warning("git_push_failed", output=output)
    else:
        logger.info("git_pushed")

    elapsed = int((time.monotonic() - start) * 1000)
    return HookResult("git", "success", elapsed)
