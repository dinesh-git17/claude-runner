"""Hook: generate echoes manifest for the frontend."""

from __future__ import annotations

import asyncio
import os
import time

from orchestrator.config import RUNNER_DIR, SessionResult
from orchestrator.pipeline import HookResult

VENV_PYTHON = RUNNER_DIR / ".venv" / "bin" / "python3"
SCRIPT = RUNNER_DIR / "resonance_manifest.py"


async def run(result: SessionResult) -> HookResult:
    """Run resonance_manifest.py to generate frontend echoes."""
    start = time.monotonic()

    if not VENV_PYTHON.exists() or not SCRIPT.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("echoes", "skipped", elapsed, "script not found")

    env = {"PYTHONPATH": str(RUNNER_DIR)}
    proc = await asyncio.create_subprocess_exec(
        str(VENV_PYTHON),
        str(SCRIPT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env},
    )
    await proc.communicate()
    elapsed = int((time.monotonic() - start) * 1000)
    status = "success" if proc.returncode == 0 else "failed"
    return HookResult("echoes", status, elapsed)
