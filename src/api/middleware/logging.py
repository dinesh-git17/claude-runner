"""Request logging middleware."""
import time
from collections.abc import Callable
from typing import Awaitable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

EXCLUDED_PATHS = frozenset({
    "/api/v1/health/live",
    "/api/v1/health/ready",
})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs request details in structured JSON format.

    Excludes health check endpoints from logging to reduce noise.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request and log details.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            HTTP response from handler.
        """
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
            client=request.client.host if request.client else None,
        )

        return response
