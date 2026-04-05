"""Hook: update the FAISS memory index incrementally."""

from __future__ import annotations

import asyncio
import time

from orchestrator.config import RUNNER_DIR, SessionResult
from orchestrator.pipeline import HookResult

VENV_PYTHON = RUNNER_DIR / ".venv" / "bin" / "python3"
INDEXER = RUNNER_DIR / "memory" / "indexer.py"


async def run(result: SessionResult) -> HookResult:
    """Run memory/indexer.py --incremental."""
    start = time.monotonic()

    if not VENV_PYTHON.exists() or not INDEXER.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("memory_index", "skipped", elapsed, "script not found")

    env = {"PYTHONPATH": str(RUNNER_DIR)}
    proc = await asyncio.create_subprocess_exec(
        str(VENV_PYTHON),
        str(INDEXER),
        "--incremental",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**__import__("os").environ, **env},
    )
    await proc.communicate()
    elapsed = int((time.monotonic() - start) * 1000)
    status = "success" if proc.returncode == 0 else "failed"
    return HookResult("memory_index", status, elapsed)
