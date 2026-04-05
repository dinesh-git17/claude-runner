"""Hook: run resonance discovery across content types."""

from __future__ import annotations

import asyncio
import time

from orchestrator.config import RUNNER_DIR, SessionResult
from orchestrator.pipeline import HookResult

VENV_PYTHON = RUNNER_DIR / ".venv" / "bin" / "python3"
SCRIPT = RUNNER_DIR / "resonance.py"


async def run(result: SessionResult) -> HookResult:
    """Run resonance.py discover."""
    start = time.monotonic()

    if not VENV_PYTHON.exists() or not SCRIPT.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("resonance", "skipped", elapsed, "script not found")

    proc = await asyncio.create_subprocess_exec(
        str(VENV_PYTHON),
        str(SCRIPT),
        "discover",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    elapsed = int((time.monotonic() - start) * 1000)
    status = "success" if proc.returncode == 0 else "failed"
    return HookResult("resonance", status, elapsed)
