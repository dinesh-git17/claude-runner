"""Hook: normalize thought frontmatter for API compatibility."""

from __future__ import annotations

import asyncio
import time

from orchestrator.config import RUNNER_DIR, SessionResult
from orchestrator.pipeline import HookResult

SCRIPT = RUNNER_DIR / "process-thoughts.sh"


async def run(result: SessionResult) -> HookResult:
    """Run process-thoughts.sh."""
    start = time.monotonic()

    if not SCRIPT.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("thoughts", "skipped", elapsed, "script not found")

    proc = await asyncio.create_subprocess_exec(
        "bash",
        str(SCRIPT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()
    elapsed = int((time.monotonic() - start) * 1000)
    status = "success" if proc.returncode == 0 else "failed"
    return HookResult("thoughts", status, elapsed)
