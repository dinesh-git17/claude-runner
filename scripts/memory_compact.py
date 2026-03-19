#!/claude-home/runner/.venv/bin/python3
"""Compact recent-days.md by archiving older entries.

With semantic search available, archived content remains searchable.
Compaction moves old entries out of working memory without losing access.

Usage:
    python3 /claude-home/runner/memory_compact.py --older-than 14d
    python3 /claude-home/runner/memory_compact.py --older-than 10d --dry-run
"""

from __future__ import annotations

import os
import sys

# Auto-exec with venv python if invoked via system python3
_VENV_PYTHON = "/claude-home/runner/.venv/bin/python3"
if os.path.realpath(sys.executable) != os.path.realpath(_VENV_PYTHON):
    os.execv(_VENV_PYTHON, [_VENV_PYTHON, *sys.argv])

import argparse  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

MEMORY_DIR = Path("/claude-home/memory")
RECENT_DAYS = MEMORY_DIR / "recent-days.md"

# Month abbreviation to number
MONTH_MAP: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# Header pattern: ## Day NN (Mon DD) or ## Days NN-MM (Mon DD-DD)
HEADER_PATTERN = re.compile(
    r"^## Days?\s+(\d+)(?:-(\d+))?\s+\((\w+)\s+(\d+)(?:-(\d+))?\)",
)

log = logging.getLogger(__name__)


def _parse_header_date(line: str) -> tuple[int | None, int | None, datetime | None]:
    """Parse a section header, return (day_start, day_end, date).

    Returns:
        (None, None, None) if the line is not a recognized header.
    """
    match = HEADER_PATTERN.match(line)
    if not match:
        return None, None, None

    day_start = int(match.group(1))
    day_end = int(match.group(2)) if match.group(2) else day_start
    month_str = match.group(3).lower()
    day_of_month = int(match.group(4))

    month_num = MONTH_MAP.get(month_str)
    if month_num is None:
        return day_start, day_end, None

    year = 2026
    try:
        date = datetime(year, month_num, day_of_month, tzinfo=UTC)
    except ValueError:
        return day_start, day_end, None

    return day_start, day_end, date


def _parse_sections(content: str) -> list[dict[str, object]]:
    """Parse recent-days.md into sections with metadata."""
    lines = content.split("\n")
    sections: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    header_lines: list[str] = []

    for i, line in enumerate(lines):
        day_start, day_end, date = _parse_header_date(line)
        if day_start is not None:
            if current is not None:
                sections.append(current)
            current = {
                "header": line,
                "day_start": day_start,
                "day_end": day_end,
                "date": date,
                "lines": [line],
                "line_start": i,
            }
        elif current is not None:
            current_lines: list[str] = current["lines"]  # type: ignore[assignment]
            current_lines.append(line)
        else:
            header_lines.append(line)

    if current is not None:
        sections.append(current)

    if sections:
        sections[0]["file_header"] = "\n".join(header_lines)

    return sections


def compact(older_than_days: int, dry_run: bool = False) -> None:
    """Move entries older than N days to an archive file."""
    if not RECENT_DAYS.exists():
        log.info("recent-days.md not found.")
        return

    content = RECENT_DAYS.read_text(encoding="utf-8")
    sections = _parse_sections(content)

    if not sections:
        log.info("No sections found in recent-days.md.")
        return

    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=older_than_days)

    to_archive: list[dict[str, object]] = []
    to_keep: list[dict[str, object]] = []

    for section in sections:
        date = section.get("date")
        if isinstance(date, datetime) and date < cutoff:
            to_archive.append(section)
        else:
            to_keep.append(section)

    if not to_archive:
        log.info("No entries older than %d days. Nothing to compact.", older_than_days)
        return

    day_starts = [s["day_start"] for s in to_archive]
    day_ends = [s["day_end"] for s in to_archive]
    archive_day_start = min(int(d) for d in day_starts if isinstance(d, int))
    archive_day_end = max(int(d) for d in day_ends if isinstance(d, int))
    archive_name = f"memory-archive-day{archive_day_start}-{archive_day_end}.md"
    archive_path = MEMORY_DIR / archive_name

    archive_lines: list[str] = []
    for section in to_archive:
        section_lines: list[str] = section["lines"]  # type: ignore[assignment]
        archive_lines.extend(section_lines)
        archive_lines.append("")

    archive_content = "\n".join(archive_lines).strip() + "\n"

    file_header = str(sections[0].get("file_header", ""))
    remaining_lines = [file_header] if file_header else []
    for section in to_keep:
        section_lines = section["lines"]  # type: ignore[assignment]
        remaining_lines.extend(section_lines)
        remaining_lines.append("")

    remaining_content = "\n".join(remaining_lines).strip() + "\n"
    remaining_line_count = len(remaining_content.strip().split("\n"))

    entry_count = len(to_archive)
    header_list = [str(s["header"]) for s in to_archive]
    log.info("Entries to archive: %d", entry_count)
    for h in header_list:
        log.info("  %s", h)
    log.info("Archive file: %s", archive_name)

    if archive_path.exists():
        log.info("  (appending to existing archive)")

    log.info(
        "Moved %d entries (days %d-%d) to %s. recent-days.md: %d lines remaining.",
        entry_count,
        archive_day_start,
        archive_day_end,
        archive_name,
        remaining_line_count,
    )

    if dry_run:
        log.info("[DRY RUN] No files modified.")
        return

    if archive_path.exists():
        existing = archive_path.read_text(encoding="utf-8")
        archive_path.write_text(
            existing.rstrip() + "\n\n" + archive_content,
            encoding="utf-8",
        )
    else:
        archive_path.write_text(archive_content, encoding="utf-8")

    RECENT_DAYS.write_text(remaining_content, encoding="utf-8")

    log.info("Done.")


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Compact recent-days.md by archiving older entries.",
    )
    parser.add_argument(
        "--older-than",
        required=True,
        help="Archive entries older than Nd (e.g. 14d, 10d)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be moved without modifying files",
    )
    return parser


def _parse_duration(value: str) -> int:
    """Parse '14d' into integer days."""
    match = re.match(r"^(\d+)d$", value.strip())
    if not match:
        msg = f"Invalid duration: {value}. Use format like '14d'."
        log.error(msg)
        sys.exit(1)
    return int(match.group(1))


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )
    parser = build_parser()
    args = parser.parse_args()

    days = _parse_duration(args.older_than)
    compact(older_than_days=days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
