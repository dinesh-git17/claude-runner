"""Hook: generate readable transcript from stream-json output."""

from __future__ import annotations

import asyncio
import time

from orchestrator.config import RUNNER_DIR, TRANSCRIPT_DIR, SessionResult
from orchestrator.pipeline import HookResult

SCRIPT = RUNNER_DIR / "process-transcript.sh"


async def run(result: SessionResult) -> HookResult:
    """Run process-transcript.sh on the stream file."""
    start = time.monotonic()
    transcript_file = TRANSCRIPT_DIR / f"session-{result.session_id}.md"

    if not SCRIPT.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("transcript", "skipped", elapsed, "script not found")

    proc = await asyncio.create_subprocess_exec(
        "bash",
        str(SCRIPT),
        str(result.stream_file),
        str(transcript_file),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    elapsed = int((time.monotonic() - start) * 1000)
    status = "success" if proc.returncode == 0 else "failed"
    return HookResult("transcript", status, elapsed)
