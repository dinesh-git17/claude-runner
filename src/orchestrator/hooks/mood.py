"""Hook: capture mood state from the session's journal entry."""

from __future__ import annotations

import asyncio
import sys
import time

from orchestrator.config import RUNNER_DIR, SessionResult
from orchestrator.pipeline import HookResult

SCRIPT = RUNNER_DIR / "mood-capture.py"


async def run(result: SessionResult) -> HookResult:
    """Run mood-capture.py with session type and ID."""
    start = time.monotonic()

    if not SCRIPT.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("mood", "skipped", elapsed, "script not found")

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(SCRIPT),
        result.session_type.name,
        result.session_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    elapsed = int((time.monotonic() - start) * 1000)
    status = "success" if proc.returncode == 0 else "failed"
    return HookResult("mood", status, elapsed)
