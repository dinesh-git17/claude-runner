#!/usr/bin/env bash
# /claude-home/runner/check-self-schedule.sh
# Cron poller: fires self-scheduled wake sessions when due

set -euo pipefail

SCHEDULE_FILE="/claude-home/data/self-schedule.json"
HISTORY_FILE="/claude-home/data/self-schedule-history.jsonl"

# Exit if no schedule pending
[ -f "$SCHEDULE_FILE" ] || exit 0

# Don't fire if a claude session is already running
if pgrep -u claude -x claude > /dev/null 2>&1; then
    exit 0
fi

# Parse wake_at from schedule
WAKE_AT=$(jq -r '.wake_at // empty' "$SCHEDULE_FILE" 2>/dev/null)
[ -z "$WAKE_AT" ] && exit 0

# Compare times
WAKE_EPOCH=$(date -d "$WAKE_AT" +%s 2>/dev/null) || exit 1
NOW_EPOCH=$(date +%s)
[ "$NOW_EPOCH" -lt "$WAKE_EPOCH" ] && exit 0

# Time to fire -- extract reason and archive to history
REASON=$(jq -r '.reason // ""' "$SCHEDULE_FILE" 2>/dev/null)
TODAY=$(TZ="America/New_York" date +%Y-%m-%d)
printf '{"date":"%s","wake_at":"%s","reason":"%s","fired_at":"%s"}\n' \
    "$TODAY" "$WAKE_AT" "$REASON" "$(date -Iseconds)" >> "$HISTORY_FILE"

# Remove schedule file before firing (prevents double-fire)
rm -f "$SCHEDULE_FILE"

# Fire the session
exec /claude-home/runner/wake.sh self "$REASON"
