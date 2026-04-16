"""Stub module for telegram_talk — local development only.

The authoritative implementation lives on the VPS. This stub provides
the minimal public surface so the API import chain resolves during local
testing.
"""

from __future__ import annotations

from pathlib import Path


def load_state() -> dict | None:  # type: ignore[type-arg]
    """Load the current talk session state.

    Returns:
        Session state dict if a session is active, None otherwise.
    """
    return None


def clear_state() -> None:
    """Discard the current talk session state."""


def touch_last_turn() -> None:
    """Update the last-turn timestamp on the active talk session."""


async def run_turn(session_id: str, message: str) -> str:
    """Run one --resume turn in the active talk session.

    Args:
        session_id: The Claude CLI session ID to resume.
        message: The user's message for this turn.

    Returns:
        Claude's reply for this turn.
    """
    return ""


async def close_session(log_file: Path) -> None:
    """Run the close pipeline for the active talk session.

    Args:
        log_file: Path where close-pipeline output should be logged.
    """
