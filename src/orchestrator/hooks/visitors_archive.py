"""Hook: archive visitor files Claudie had the chance to see this session.

Sweeps files that existed in /claude-home/visitors/ at session start into
/claude-home/visitors/archive/YYYY-MM/. Files that arrived during the session
are left alone for the next run. Fixes the bug where scheduled sessions
re-processed the same visitor messages across wake-ups because /visitors/
had no read-state tracking.
"""

from __future__ import annotations

import shutil
import time
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from orchestrator.config import CLAUDE_HOME
from orchestrator.pipeline import HookResult

if TYPE_CHECKING:
    from orchestrator.config import SessionResult

logger = structlog.get_logger()

VISITORS_DIR = CLAUDE_HOME / "visitors"
ARCHIVE_DIR = VISITORS_DIR / "archive"


async def run(result: SessionResult) -> HookResult:
    """Move visitor files that existed at session start into archive/YYYY-MM/."""
    start = time.monotonic()

    if result.exit_code != 0:
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult(
            "visitors_archive",
            "skipped",
            elapsed,
            "session exited non-zero",
        )

    if not result.visitors_at_start:
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("visitors_archive", "success", elapsed)

    moved = 0
    skipped = 0
    failed = 0

    for src in result.visitors_at_start:
        if not src.exists():
            skipped += 1
            continue
        try:
            file_date = datetime.fromtimestamp(src.stat().st_mtime)
            dest_dir = ARCHIVE_DIR / file_date.strftime("%Y-%m")
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            if dest.exists():
                logger.warning(
                    "visitors_archive_conflict",
                    file=src.name,
                    dest=str(dest),
                )
                skipped += 1
                continue
            shutil.move(str(src), str(dest))
            moved += 1
        except OSError as e:
            logger.warning(
                "visitors_archive_failed",
                file=src.name,
                error=str(e),
            )
            failed += 1

    logger.info(
        "visitors_archived",
        moved=moved,
        skipped=skipped,
        failed=failed,
        total=len(result.visitors_at_start),
    )

    elapsed = int((time.monotonic() - start) * 1000)
    status = "failed" if failed and moved == 0 else "success"
    error = f"{failed} files failed to archive" if failed else None
    return HookResult("visitors_archive", status, elapsed, error)
