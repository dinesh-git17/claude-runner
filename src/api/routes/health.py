"""Health check endpoints for liveness and readiness probes."""
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    """Response model for liveness probe.

    Attributes:
        status: Always 'alive' when process is running.
    """

    status: Literal["alive"]


class ReadinessCheck(BaseModel):
    """Individual dependency check result.

    Attributes:
        name: Identifier for the dependency being checked.
        status: Result of the check ('ok' or 'failed').
        message: Error details when status is 'failed'.
    """

    name: str
    status: Literal["ok", "failed"]
    message: str | None = None


class ReadinessResponse(BaseModel):
    """Response model for readiness probe.

    Attributes:
        status: Overall readiness ('ready' or 'not_ready').
        checks: List of individual dependency check results.
    """

    status: Literal["ready", "not_ready"]
    checks: list[ReadinessCheck]


def _check_directory(path: str) -> ReadinessCheck:
    """Verify directory exists and is accessible.

    Args:
        path: Absolute path to directory.

    Returns:
        Check result with status and optional error message.
    """
    try:
        p = Path(path)
        if p.exists() and p.is_dir():
            list(p.iterdir())
            return ReadinessCheck(name=f"dir:{path}", status="ok")
        return ReadinessCheck(
            name=f"dir:{path}",
            status="failed",
            message="Directory not found",
        )
    except PermissionError as e:
        return ReadinessCheck(
            name=f"dir:{path}",
            status="failed",
            message=f"Permission denied: {e}",
        )
    except OSError as e:
        return ReadinessCheck(
            name=f"dir:{path}",
            status="failed",
            message=str(e),
        )


def _check_database(path: str) -> ReadinessCheck:
    """Verify SQLite database is accessible and queryable.

    Args:
        path: Absolute path to database file.

    Returns:
        Check result with status and optional error message.
    """
    try:
        conn = sqlite3.connect(path, timeout=1.0)
        conn.execute("SELECT 1")
        conn.close()
        return ReadinessCheck(name=f"db:{path}", status="ok")
    except sqlite3.Error as e:
        return ReadinessCheck(
            name=f"db:{path}",
            status="failed",
            message=str(e),
        )


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Liveness probe endpoint.

    Returns immediate success if the process is running.
    Used by load balancers to detect hung processes.

    Returns:
        Liveness status response.
    """
    return LivenessResponse(status="alive")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness() -> JSONResponse:
    """Readiness probe endpoint.

    Validates access to required dependencies:
    - /claude-home/thoughts directory
    - /claude-home/dreams directory
    - /claude-home/sessions.db database

    Returns 200 if all checks pass, 503 if any fail.

    Returns:
        Readiness status with individual check results.
    """
    checks = [
        _check_directory("/claude-home/thoughts"),
        _check_directory("/claude-home/dreams"),
        _check_database("/claude-home/sessions.db"),
    ]
    all_ok = all(c.status == "ok" for c in checks)
    response = ReadinessResponse(
        status="ready" if all_ok else "not_ready",
        checks=checks,
    )
    code = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=response.model_dump(), status_code=code)
