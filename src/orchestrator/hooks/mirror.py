"""Hook: compute mirror snapshot if due (10-day cadence)."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from orchestrator.config import MIRROR_SNAPSHOT_FILE, RUNNER_DIR, SessionResult
from orchestrator.pipeline import HookResult

TZ_EST = ZoneInfo("America/New_York")
CADENCE_DAYS = 10


async def run(result: SessionResult) -> HookResult:
    start = time.monotonic()

    if MIRROR_SNAPSHOT_FILE.exists():
        try:
            data = json.loads(MIRROR_SNAPSHOT_FILE.read_text(encoding="utf-8"))
            computed_at = data.get("computed_at", "")
            if computed_at:
                computed_date = (
                    datetime.fromisoformat(computed_at).astimezone(TZ_EST).date()
                )
                today = datetime.now(TZ_EST).date()
                age = (today - computed_date).days
                if age < CADENCE_DAYS:
                    elapsed = int((time.monotonic() - start) * 1000)
                    return HookResult("mirror_snapshot", "success", elapsed)
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    script = RUNNER_DIR / "mirror.py"
    if not script.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("mirror_snapshot", "skipped", elapsed, "script not found")

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "reflect",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    elapsed = int((time.monotonic() - start) * 1000)

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:200]
        return HookResult("mirror_snapshot", "failed", elapsed, err)

    return HookResult("mirror_snapshot", "success", elapsed)
