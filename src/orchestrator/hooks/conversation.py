"""Hook: extract response from stream-json and save conversation file."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from orchestrator.pipeline import HookResult

if TYPE_CHECKING:
    from orchestrator.config import SessionResult


async def run(result: SessionResult) -> HookResult:
    """Extract final response and append to conversation file."""
    start = time.monotonic()

    if result.convo_file is None:
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("conversation", "skipped", elapsed, "no convo file")

    if not result.stream_file.exists():
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("conversation", "skipped", elapsed, "no stream file")

    # Extract final result text from stream-json
    response = ""
    for line in result.stream_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("type") == "result":
            response = data.get("result", "")

    if response and result.convo_file.exists():
        with result.convo_file.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## Response\n\n{response}")

    elapsed = int((time.monotonic() - start) * 1000)
    return HookResult("conversation", "success", elapsed)
