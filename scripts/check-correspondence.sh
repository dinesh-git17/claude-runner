#!/usr/bin/env bash
# /claude-home/runner/check-correspondence.sh
# Cron poller: checks for unread mailbox messages and fires correspondence sessions.
# Runs every 10 minutes via cron.

set -euo pipefail

MAILBOX_DIR="/claude-home/mailbox"
HISTORY_FILE="/claude-home/data/correspondence-history.jsonl"
DAILY_CAP=3
DEBOUNCE_MINUTES=30
CRON_BUFFER_MINUTES=30
LOG_PREFIX="[correspondence-poller]"

# Cron session hours (EST): 0, 3, 6, 9, 12, 15, 18, 21
CRON_HOURS=(0 3 6 9 12 15 18 21)

log() {
    echo "$LOG_PREFIX $(date '+%Y-%m-%d %H:%M:%S') $*"
}

# Check if a claude session is currently running
is_session_running() {
    pgrep -u claude -x claude >/dev/null 2>&1
}

# Check if current time is within buffer of a cron slot
is_near_cron_slot() {
    local hour minute now_minutes slot_minutes
    hour=$(TZ="America/New_York" date +%H)
    minute=$(TZ="America/New_York" date +%M)
    hour=$((10#$hour))
    minute=$((10#$minute))
    now_minutes=$((hour * 60 + minute))

    for slot_hour in "${CRON_HOURS[@]}"; do
        slot_minutes=$((slot_hour * 60))
        local diff=$((now_minutes - slot_minutes))
        if [ "$diff" -lt 0 ]; then
            diff=$((-diff))
        fi
        # Also check wrap-around (e.g., 23:45 is 15 min before 0:00)
        local wrap_diff=$((1440 - diff))
        if [ "$wrap_diff" -lt "$diff" ]; then
            diff=$wrap_diff
        fi
        if [ "$diff" -lt "$CRON_BUFFER_MINUTES" ]; then
            return 0
        fi
    done
    return 1
}

# Count today's correspondence sessions
count_today_sessions() {
    if [ ! -f "$HISTORY_FILE" ]; then
        echo 0
        return
    fi
    local today
    today=$(TZ="America/New_York" date +%Y-%m-%d)
    local count=0
    while IFS= read -r line; do
        local ts
        ts=$(echo "$line" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('date',''))" 2>/dev/null || true)
        if [ "$ts" = "$today" ]; then
            count=$((count + 1))
        fi
    done < "$HISTORY_FILE"
    echo "$count"
}

# Record a correspondence session in history
record_session() {
    local usernames="$1"
    local today
    today=$(TZ="America/New_York" date +%Y-%m-%d)
    local now
    now=$(date -Iseconds)
    mkdir -p "$(dirname "$HISTORY_FILE")"
    echo "{\"date\":\"$today\",\"ts\":\"$now\",\"usernames\":\"$usernames\"}" >> "$HISTORY_FILE"
}

# Find users who need replies
find_pending_users() {
    local pending=""
    local now_epoch
    now_epoch=$(date +%s)
    local debounce_seconds=$((DEBOUNCE_MINUTES * 60))

    for user_dir in "$MAILBOX_DIR"/*/; do
        [ -d "$user_dir" ] || continue
        local thread_file="${user_dir}thread.jsonl"
        [ -f "$thread_file" ] || continue

        # Read last non-empty line
        local last_line
        last_line=$(tac "$thread_file" | while IFS= read -r line; do
            line=$(echo "$line" | tr -d '[:space:]')
            if [ -n "$line" ]; then
                echo "$line"
                break
            fi
        done)

        [ -n "$last_line" ] || continue

        # Parse last message
        local from_field ts_field
        from_field=$(echo "$last_line" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('from',''))" 2>/dev/null || true)
        ts_field=$(echo "$last_line" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('ts',''))" 2>/dev/null || true)

        # Skip if last message is from claudie (already replied)
        if [ "$from_field" = "claudie" ]; then
            continue
        fi

        # Skip if message is too recent (debounce)
        if [ -n "$ts_field" ]; then
            local msg_epoch
            msg_epoch=$(date -d "$ts_field" +%s 2>/dev/null || echo 0)
            local age=$((now_epoch - msg_epoch))
            if [ "$age" -lt "$debounce_seconds" ]; then
                continue
            fi
        fi

        local username
        username=$(basename "$user_dir")
        if [ -n "$pending" ]; then
            pending="$pending,$username"
        else
            pending="$username"
        fi
    done

    echo "$pending"
}

# --- Main ---

log "Checking for pending correspondence..."

# Guard: session running
if is_session_running; then
    log "Session running, skipping"
    exit 0
fi

# Guard: near cron slot
if is_near_cron_slot; then
    log "Near cron slot, skipping"
    exit 0
fi

# Guard: daily cap
today_count=$(count_today_sessions)
if [ "$today_count" -ge "$DAILY_CAP" ]; then
    log "Daily cap reached ($today_count/$DAILY_CAP), skipping"
    exit 0
fi

# Find users needing replies
pending=$(find_pending_users)
if [ -z "$pending" ]; then
    log "No pending correspondence"
    exit 0
fi

log "Pending users: $pending"

# Record and fire
record_session "$pending"
log "Firing correspondence session for: $pending"
/claude-home/runner/wake.sh correspondence "$pending"
log "Correspondence session completed"
