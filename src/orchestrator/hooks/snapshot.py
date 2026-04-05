"""Hook: snapshot content mtimes and trigger Vercel revalidation."""

from __future__ import annotations

import os
import time

import httpx
import structlog

from orchestrator.config import (
    CLAUDE_HOME,
    REVALIDATION_TAGS,
    SNAPSHOT_DIRECTORIES,
    SessionResult,
)
from orchestrator.pipeline import HookResult

logger = structlog.get_logger()


def snapshot_content() -> dict[str, float]:
    """Snapshot modification times for all content files."""
    result: dict[str, float] = {}
    for dirname in SNAPSHOT_DIRECTORIES:
        dir_path = CLAUDE_HOME / dirname
        if not dir_path.is_dir():
            continue
        for f in dir_path.rglob("*"):
            if f.is_file() and f.suffix in (".md", ".json", ".py"):
                result[str(f)] = f.stat().st_mtime
    return result


async def run(result: SessionResult) -> HookResult:
    """Diff content snapshots and trigger Vercel revalidation."""
    start = time.monotonic()

    # Compute after-snapshot
    after = snapshot_content()
    before = result.before_snapshot

    # Find changed files
    changed: list[str] = []
    for path, mtime in after.items():
        if path not in before or before[path] != mtime:
            changed.append(path)

    if not changed:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info("revalidation_skipped", reason="no content changes")
        return HookResult("revalidation", "success", elapsed)

    # Determine tags to revalidate
    tags: set[str] = set()
    for filepath in changed:
        for pattern, tag in REVALIDATION_TAGS.items():
            if pattern in filepath:
                tags.add(tag)

    if tags:
        tags.add("echoes")

    if not tags:
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("revalidation", "success", elapsed)

    # Call Vercel revalidation endpoint
    revalidate_url = os.environ.get("VERCEL_REVALIDATE_URL", "")
    revalidate_secret = os.environ.get("VERCEL_REVALIDATE_SECRET", "")

    if not revalidate_url or not revalidate_secret:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.info("revalidation_skipped", reason="missing env vars")
        return HookResult("revalidation", "skipped", elapsed, "missing env vars")

    tag_list = sorted(tags)
    logger.info("revalidating", tags=tag_list)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                revalidate_url,
                json={"tags": tag_list},
                headers={
                    "Content-Type": "application/json",
                    "x-revalidate-secret": revalidate_secret,
                },
            )
            if resp.is_success:
                logger.info("revalidation_success", body=resp.text)
            else:
                logger.warning(
                    "revalidation_failed",
                    status=resp.status_code,
                    body=resp.text,
                )
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return HookResult("revalidation", "failed", elapsed, str(e))

    elapsed = int((time.monotonic() - start) * 1000)
    return HookResult("revalidation", "success", elapsed)
