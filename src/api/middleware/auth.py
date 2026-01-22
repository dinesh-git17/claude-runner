"""API key authentication middleware."""

import secrets
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

PUBLIC_PATHS = frozenset(
    {
        "/api/v1/health/live",
        "/api/v1/health/ready",
    }
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware that validates API key for protected endpoints.

    Health check endpoints are excluded to allow monitoring without auth.
    """

    def __init__(self, app: Callable[..., Awaitable[Response]], api_key: str) -> None:
        """Initialize middleware with API key.

        Args:
            app: ASGI application.
            api_key: Expected API key value.
        """
        super().__init__(app)  # type: ignore[arg-type]
        self._api_key = api_key

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Validate API key for non-public endpoints.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            HTTP response, or 401 if authentication fails.
        """
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        provided_key = request.headers.get("X-API-Key", "")

        if not provided_key:
            return JSONResponse(
                status_code=401,
                content={"error": "Missing X-API-Key header"},
            )

        if not secrets.compare_digest(provided_key, self._api_key):
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid API key"},
            )

        return await call_next(request)
