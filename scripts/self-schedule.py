#!/usr/bin/env python3
"""Self-scheduling CLI for Claudie.

Schedule extra wake sessions outside the 8 cron slots.

Usage:
    python3 self-schedule.py --at 14:30 --reason "finish the essay"
    python3 self-schedule.py --in 2h --reason "check on something"
    python3 self-schedule.py --cancel
    python3 self-schedule.py --status
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ_EST = ZoneInfo("America/New_York")
SCHEDULE_FILE = Path("/claude-home/data/self-schedule.json")
HISTORY_FILE = Path("/claude-home/data/self-schedule-history.jsonl")
DAILY_CAP = 3
BUFFER_MINUTES = 30
CRON_HOURS = (0, 3, 6, 9, 12, 15, 18, 21)
CRON_SESSION_NAMES: dict[int, str] = {
    0: "midnight",
    3: "late_night",
    6: "morning",
    9: "midmorning",
    12: "noon",
    15: "afternoon",
    18: "dusk",
    21: "evening",
}

log = logging.getLogger(__name__)


def now_est() -> datetime:
    """Current time in EST."""
    return datetime.now(TZ_EST)


def check_cron_collision(wake_at: datetime) -> str | None:
    """Return error message if wake_at is within BUFFER_MINUTES of a cron slot."""
    wake_minutes = wake_at.hour * 60 + wake_at.minute
    for hour in CRON_HOURS:
        cron_minutes = hour * 60
        diff = abs(wake_minutes - cron_minutes)
        diff = min(diff, 1440 - diff)
        if diff < BUFFER_MINUTES:
            name = CRON_SESSION_NAMES[hour]
            return (
                f"Too close to {name} session ({hour:02d}:00). "
                f"Need {BUFFER_MINUTES}min buffer."
            )
    return None


def count_sessions_on_date(target_date: str) -> int:
    """Count self-scheduled sessions that fired on a given date."""
    if not HISTORY_FILE.exists():
        return 0
    count = 0
    for line in HISTORY_FILE.read_text(encoding="utf-8").strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("date") == target_date:
                count += 1
        except json.JSONDecodeError:
            continue
    return count


def read_pending() -> dict[str, str] | None:
    """Read pending schedule file."""
    if not SCHEDULE_FILE.exists():
        return None
    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return None
    except (json.JSONDecodeError, OSError):
        return None


def parse_duration(value: str) -> timedelta | None:
    """Parse duration like '2h', '30m', '1h30m'."""
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", value)
    if not match or (not match.group(1) and not match.group(2)):
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    if hours == 0 and minutes == 0:
        return None
    return timedelta(hours=hours, minutes=minutes)


def parse_time(value: str) -> datetime | None:
    """Parse HH:MM, return EST datetime for today or tomorrow if past."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    current = now_est()
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target


def cmd_schedule(wake_at: datetime, reason: str) -> int:
    """Validate and write a self-scheduled wake session."""
    current = now_est()

    if wake_at <= current:
        log.error("Cannot schedule in the past: %s", wake_at.strftime("%I:%M %p"))
        return 1

    collision = check_cron_collision(wake_at)
    if collision:
        log.error("%s", collision)
        return 1

    target_date = wake_at.date().isoformat()
    fired = count_sessions_on_date(target_date)
    pending = read_pending()
    pending_same_day = 0
    if pending and pending.get("wake_at", "")[:10] == target_date:
        pending_same_day = 1

    total = fired + pending_same_day
    if total >= DAILY_CAP:
        log.error(
            "Daily cap reached for %s: %d fired + %d pending = %d/%d",
            target_date,
            fired,
            pending_same_day,
            total,
            DAILY_CAP,
        )
        return 1

    if pending:
        old_time = pending.get("wake_at", "unknown")[:16]
        sys.stdout.write(f"Replacing existing schedule ({old_time})\n")

    schedule = {
        "wake_at": wake_at.isoformat(),
        "reason": reason,
        "created_at": current.isoformat(),
    }
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")

    sys.stdout.write(f"Scheduled: {wake_at.strftime('%I:%M %p on %A, %B %d')}\n")
    sys.stdout.write(f"Reason: {reason}\n")
    remaining = DAILY_CAP - total - 1
    if remaining > 0:
        sys.stdout.write(f"Remaining slots today: {remaining}\n")
    return 0


def cmd_cancel() -> int:
    """Cancel pending schedule."""
    pending = read_pending()
    if not pending:
        sys.stdout.write("Nothing scheduled.\n")
        return 0
    SCHEDULE_FILE.unlink(missing_ok=True)
    sys.stdout.write(f"Cancelled: {pending.get('wake_at', 'unknown')[:16]}\n")
    sys.stdout.write(f"Reason was: {pending.get('reason', 'unknown')}\n")
    return 0


def cmd_status() -> int:
    """Show current schedule status."""
    current = now_est()
    today = current.date().isoformat()
    fired = count_sessions_on_date(today)
    pending = read_pending()

    sys.stdout.write(f"Self-scheduled sessions today: {fired}/{DAILY_CAP}\n")

    if pending:
        sys.stdout.write(f"Pending: {pending.get('wake_at', 'unknown')[:16]}\n")
        sys.stdout.write(f"Reason: {pending.get('reason', 'unknown')}\n")
    else:
        sys.stdout.write("No session currently scheduled.\n")

    remaining = DAILY_CAP - fired
    if pending and pending.get("wake_at", "")[:10] == today:
        remaining -= 1
    if remaining > 0:
        sys.stdout.write(f"Remaining slots today: {remaining}\n")

    return 0


def main() -> int:
    """Entry point."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Self-schedule a wake session outside the 8 cron slots"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--at", metavar="HH:MM", help="Schedule at specific time (EST)")
    group.add_argument(
        "--in",
        metavar="DURATION",
        dest="in_duration",
        help="Schedule relative to now (e.g. 2h, 30m, 1h30m)",
    )
    group.add_argument("--cancel", action="store_true", help="Cancel pending schedule")
    group.add_argument("--status", action="store_true", help="Show schedule status")
    parser.add_argument(
        "--reason", help="Why you want to be woken up (required for --at/--in)"
    )

    args = parser.parse_args()

    if args.cancel:
        return cmd_cancel()
    if args.status:
        return cmd_status()

    if not args.reason:
        log.error("--reason is required when scheduling a session.")
        return 1

    if args.at:
        wake_at = parse_time(args.at)
        if wake_at is None:
            log.error("Invalid time: %s (use HH:MM, 24-hour format)", args.at)
            return 1
    else:
        duration = parse_duration(args.in_duration)
        if duration is None:
            log.error(
                "Invalid duration: %s (use e.g. 2h, 30m, 1h30m)", args.in_duration
            )
            return 1
        wake_at = now_est() + duration

    return cmd_schedule(wake_at, args.reason)


if __name__ == "__main__":
    sys.exit(main())
