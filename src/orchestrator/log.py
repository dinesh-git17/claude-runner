"""Structured logging configuration for the session orchestrator."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def configure_logging(
    log_file: Path | None = None,
    debug: bool = False,
) -> None:
    """Configure structlog for JSON output to stdout and optionally a file.

    Args:
        log_file: If provided, also log to this file.
        debug: Enable debug-level logging.
    """
    level = logging.DEBUG if debug else logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        handlers.append(logging.FileHandler(str(log_file), encoding="utf-8"))

    logging.basicConfig(
        format="%(message)s",
        level=level,
        handlers=handlers,
        force=True,
    )
