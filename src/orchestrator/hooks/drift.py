"""Hook: compute drift signals from recent writing."""

from __future__ import annotations

import asyncio
import sys
import time

from orchestrator.config import RUNNER_DIR, SessionResult
from orchestrator.pipeline import HookResult

SCRIPT = RUNNER_DIR / "drift.py"


async def run(result: SessionResult) -> HookResult:
    """Run drift computation with session name."""
    start = time.monotonic()

    if not SCRIPT.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("drift", "skipped", elapsed, "script not found")

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(SCRIPT),
        result.session_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    elapsed = int((time.monotonic() - start) * 1000)

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:200]
        return HookResult("drift", "failed", elapsed, err)

    return HookResult("drift", "success", elapsed)
