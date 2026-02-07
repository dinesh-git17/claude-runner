"""Session log parser."""

import json
import re
from pathlib import Path

import structlog

from api.content.schemas import SessionLogEntry

logger = structlog.get_logger()

LOGS_DIR = Path("/claude-home/logs")

# Patterns
TYPE_RE = re.compile(r"^Type:\s*(\w+)")
DATE_RE = re.compile(r"session-(\d{8})-")
EXIT_RE = re.compile(r"exit code:\s*(\d+)")


def _parse_log_file(path: Path) -> SessionLogEntry | None:
    """Parse a single session log file into a SessionLogEntry.

    Args:
        path: Path to the session log file.

    Returns:
        Parsed entry, or None if the file is malformed.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning("session_log_read_error", file=str(path), error=str(e))
        return None

    lines = text.strip().splitlines()

    # Extract date from filename (session-YYYYMMDD-HHMMSS.log)
    date_match = DATE_RE.search(path.name)
    if not date_match:
        return None
    raw_date = date_match.group(1)
    date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

    # Extract session type
    session_type = "unknown"
    for line in lines[:5]:
        m = TYPE_RE.match(line)
        if m:
            session_type = m.group(1)
            break

    # Find the JSON result blob
    result_data: dict[str, object] | None = None
    for line in lines:
        if '"type":"result"' in line:
            try:
                result_data = json.loads(line)
            except json.JSONDecodeError:
                continue

    if result_data is None:
        return None

    # Extract exit code from footer
    exit_code = 0
    for line in reversed(lines[-5:]):
        m = EXIT_RE.search(line)
        if m:
            exit_code = int(m.group(1))
            break

    # Compute total tokens from usage
    usage = result_data.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)

    # Determine primary model (the one with highest cost)
    model_usage = result_data.get("modelUsage", {})
    if not isinstance(model_usage, dict):
        model_usage = {}
    primary_model = "unknown"
    max_cost = -1.0
    for model_id, stats in model_usage.items():
        if not isinstance(stats, dict):
            continue
        cost = stats.get("costUSD", 0)
        if isinstance(cost, (int, float)) and cost > max_cost:
            max_cost = cost
            primary_model = model_id

    raw_duration = result_data.get("duration_ms", 0)
    raw_turns = result_data.get("num_turns", 0)
    raw_cost = result_data.get("total_cost_usd", 0.0)

    return SessionLogEntry(
        date=date_str,
        session_type=session_type,
        duration_ms=int(raw_duration) if isinstance(raw_duration, (int, float)) else 0,
        num_turns=int(raw_turns) if isinstance(raw_turns, (int, float)) else 0,
        total_cost_usd=(float(raw_cost) if isinstance(raw_cost, (int, float)) else 0.0),
        input_tokens=int(input_tokens) if isinstance(input_tokens, (int, float)) else 0,
        output_tokens=(
            int(output_tokens) if isinstance(output_tokens, (int, float)) else 0
        ),
        cache_read_tokens=(
            int(cache_read) if isinstance(cache_read, (int, float)) else 0
        ),
        cache_creation_tokens=(
            int(cache_creation) if isinstance(cache_creation, (int, float)) else 0
        ),
        model=primary_model,
        is_error=bool(result_data.get("is_error", False)),
        exit_code=exit_code,
    )


def get_all_session_logs() -> list[SessionLogEntry]:
    """Retrieve all session log entries sorted by date descending.

    Skips malformed files with logging.

    Returns:
        List of session log entries, newest first.
    """
    if not LOGS_DIR.exists():
        logger.warning("logs_directory_not_found", path=str(LOGS_DIR))
        return []

    entries: list[SessionLogEntry] = []
    for path in sorted(LOGS_DIR.glob("session-*.log"), reverse=True):
        entry = _parse_log_file(path)
        if entry is not None:
            entries.append(entry)
        else:
            logger.debug("session_log_skipped", file=str(path))

    return entries
