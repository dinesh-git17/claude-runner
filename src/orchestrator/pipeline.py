"""Dependency-aware post-session hook pipeline.

Hooks declare dependencies. The pipeline resolves execution order
and runs independent hooks in parallel via asyncio.gather.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from orchestrator.config import SessionResult

logger = structlog.get_logger()


@dataclass
class HookResult:
    """Result from a single hook execution."""

    name: str
    status: str  # "success" | "failed" | "skipped"
    duration_ms: int
    error: str | None = None


@dataclass
class Hook:
    """A post-session hook with dependency declarations."""

    name: str
    depends_on: list[str]
    fn: Callable[[SessionResult], Awaitable[HookResult]]


@dataclass
class PipelineReport:
    """Summary of a full pipeline execution."""

    results: list[HookResult] = field(default_factory=list)
    total_duration_ms: int = 0

    @property
    def failed(self) -> list[HookResult]:
        """Return hooks that failed."""
        return [r for r in self.results if r.status == "failed"]


async def _run_hook(hook: Hook, result: SessionResult) -> HookResult:
    """Execute a single hook, catching exceptions."""
    start = time.monotonic()
    try:
        return await hook.fn(result)
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.error("hook_exception", hook=hook.name, error=str(e))
        return HookResult(
            name=hook.name,
            status="failed",
            duration_ms=elapsed,
            error=str(e),
        )


async def run_pipeline(
    hooks: list[Hook],
    result: SessionResult,
) -> PipelineReport:
    """Execute hooks in dependency order, parallelizing independent groups."""
    pipeline_start = time.monotonic()
    report = PipelineReport()
    completed: set[str] = set()

    while True:
        # Find hooks whose dependencies are all satisfied
        remaining = [h for h in hooks if h.name not in completed]
        if not remaining:
            break

        ready = [h for h in remaining if all(dep in completed for dep in h.depends_on)]

        if not ready:
            # Remaining hooks have unmet dependencies — skip them
            for h in remaining:
                unmet = [d for d in h.depends_on if d not in completed]
                logger.warning(
                    "hook_skipped_unmet_deps",
                    hook=h.name,
                    unmet=unmet,
                )
                report.results.append(
                    HookResult(
                        name=h.name,
                        status="skipped",
                        duration_ms=0,
                        error=f"unmet dependencies: {unmet}",
                    )
                )
                completed.add(h.name)
            break

        # Run all ready hooks in parallel
        if len(ready) == 1:
            hook_result = await _run_hook(ready[0], result)
            report.results.append(hook_result)
            completed.add(ready[0].name)
            logger.info(
                "hook_complete",
                hook=hook_result.name,
                status=hook_result.status,
                duration_ms=hook_result.duration_ms,
            )
        else:
            group_results = await asyncio.gather(
                *[_run_hook(h, result) for h in ready],
            )
            for hook_result in group_results:
                report.results.append(hook_result)
                completed.add(hook_result.name)
                logger.info(
                    "hook_complete",
                    hook=hook_result.name,
                    status=hook_result.status,
                    duration_ms=hook_result.duration_ms,
                )

    report.total_duration_ms = int((time.monotonic() - pipeline_start) * 1000)
    logger.info(
        "pipeline_complete",
        total_duration_ms=report.total_duration_ms,
        hooks_run=len(report.results),
        hooks_failed=len(report.failed),
    )
    return report
