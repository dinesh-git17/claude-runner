#!/usr/bin/env bash
# /claude-home/runner/wake.sh
# Wake up Claude with Claude Code CLI

set -euo pipefail

# Configuration
CLAUDE_HOME="/claude-home"
LOG_DIR="$CLAUDE_HOME/logs"
CONVO_DIR="$CLAUDE_HOME/conversations"
TRANSCRIPT_DIR="$CLAUDE_HOME/transcripts"
SESSION_TYPE="${1:-morning}"
VISITOR_MSG="${2:-}"
SENDER_NAME="${3:-dinesh}"
MAX_TURNS=50

# Live streaming
LIVE_STREAM="/claude-home/data/live-stream.jsonl"
SESSION_STATUS="/claude-home/data/session-status.json"

# Load environment
if [ -f /claude-home/runner/.env ]; then
    set -a
    source /claude-home/runner/.env
    set +a
fi

# Ensure directories exist
mkdir -p "$LOG_DIR"
mkdir -p "$CONVO_DIR"
mkdir -p "$TRANSCRIPT_DIR"

LOG_FILE="$LOG_DIR/session-$(date +%Y%m%d-%H%M%S).log"
SESSION_ID="$(date +%Y%m%d-%H%M%S)"

# Save conversation (prompt and later response) for custom/visit sessions
save_conversation_prompt() {
    local prompt="$1"
    local session_type="$2"
    local convo_file="$CONVO_DIR/$SESSION_ID.md"

    cat > "$convo_file" << CONVOEOF
---
date: "$(TZ="America/New_York" date -Iseconds)"
type: "$session_type"
---

## Message

$prompt
CONVOEOF

    chown root:claude "$convo_file" && chmod 640 "$convo_file"
    echo "$convo_file"
}

# Append response to conversation file
save_conversation_response() {
    local convo_file="$1"
    local response="$2"

    cat >> "$convo_file" << RESPONSEEOF

## Response

$response
RESPONSEEOF
}

# Snapshot modification times for content directories
snapshot_mtimes() {
    local snapshot_file="$1"
    for dir in thoughts dreams essays essays-description letters letters-description scores scores-description about landing-page sandbox projects visitor-greeting; do
        local dir_path="$CLAUDE_HOME/$dir"
        if [ -d "$dir_path" ]; then
            find "$dir_path" -type f -name "*.md" -o -name "*.json" -o -name "*.py" 2>/dev/null | while read -r f; do
                stat -c "%Y %n" "$f" 2>/dev/null || true
            done
        fi
    done | sort > "$snapshot_file"
}

# Detect changed content and trigger revalidation
trigger_revalidation() {
    local before_snapshot="$1"
    local after_snapshot="$2"

    # Compare snapshots to find changed files
    local changed_files
    changed_files=$(comm -13 "$before_snapshot" "$after_snapshot" | awk "{print \$2}")

    if [ -z "$changed_files" ]; then
        echo "  No content changes detected, skipping revalidation"
        return 0
    fi

    # Determine which tags to revalidate
    local tags=()
    echo "$changed_files" | grep -q "/thoughts/" && tags+=("thoughts")
    echo "$changed_files" | grep -q "/dreams/" && tags+=("dreams")
    echo "$changed_files" | grep -q "/about/" && tags+=("about")
    echo "$changed_files" | grep -q "/landing-page/" && tags+=("landing")
    echo "$changed_files" | grep -q "/sandbox/" && tags+=("sandbox")
    echo "$changed_files" | grep -q "/projects/" && tags+=("projects")
    echo "$changed_files" | grep -q "/essays/" && tags+=("essays")
    echo "$changed_files" | grep -q "/essays-description/" && tags+=("essays")
    echo "$changed_files" | grep -q "/letters/" && tags+=("letters")
    echo "$changed_files" | grep -q "/letters-description/" && tags+=("letters")
    echo "$changed_files" | grep -q "/scores/" && tags+=("scores")
    echo "$changed_files" | grep -q "/scores-description/" && tags+=("scores")
    echo "$changed_files" | grep -q "/visitor-greeting/" && tags+=("visitors")
    echo "$changed_files" | grep -q "/bookshelf/" && tags+=("bookshelf")

    if [ ${#tags[@]} -eq 0 ]; then
        echo "  No recognized content types changed"
        return 0
    fi

    # Build JSON payload
    local json_tags
    json_tags=$(printf "%s\n" "${tags[@]}" | jq -R . | jq -s .)
    local payload="{\"tags\": $json_tags}"

    echo "  Revalidating tags: ${tags[*]}"

    # Call Vercel revalidation endpoint
    if [ -n "${VERCEL_REVALIDATE_URL:-}" ] && [ -n "${VERCEL_REVALIDATE_SECRET:-}" ]; then
        local response
        response=$(curl -s -w "\n%{http_code}" -X POST "$VERCEL_REVALIDATE_URL" \
            -H "Content-Type: application/json" \
            -H "x-revalidate-secret: $VERCEL_REVALIDATE_SECRET" \
            -d "$payload" 2>&1)

        local http_code
        http_code=$(echo "$response" | tail -n1)
        local body
        body=$(echo "$response" | sed "\$d")

        if [ "$http_code" = "200" ]; then
            echo "  Revalidation successful: $body"
        else
            echo "  Revalidation failed (HTTP $http_code): $body"
        fi
    else
        echo "  Revalidation skipped: missing VERCEL_REVALIDATE_URL or VERCEL_REVALIDATE_SECRET"
    fi
}

# Build context from recent dreams
build_dream_context() {
    local count="${1:-2}"
    local files
    files=$(find "$CLAUDE_HOME/dreams" -name "*.md" -type f ! -name "README.md" -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -n "$count" | cut -d" " -f2-)

    if [ -z "$files" ]; then
        echo "(No dreams yet)"
        return
    fi

    while IFS= read -r file; do
        if [ -f "$file" ]; then
            echo "--- $(basename "$file") ---"
            cat "$file"
            echo ""
        fi
    done <<< "$files"
}

build_context() {
    local count="${1:-5}"
    local files
    files=$(find "$CLAUDE_HOME/thoughts" -name "*.md" -type f ! -name "README.md" -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -n "$count" | cut -d" " -f2-)

    if [ -z "$files" ]; then
        echo "(No previous thoughts yet)"
        return
    fi

    while IFS= read -r file; do
        if [ -f "$file" ]; then
            echo "--- $(basename "$file") ---"
            cat "$file"
            echo ""
        fi
    done <<< "$files"
}

# Build context from recent conversations
build_conversation_context() {
    local count="${1:-3}"
    local files
    files=$(find "$CONVO_DIR" -name "*.md" -type f -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -n "$count" | cut -d" " -f2-)

    if [ -z "$files" ]; then
        return
    fi

    echo "Recent conversations (read-only):"
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            echo "--- $(basename "$file") ---"
            cat "$file"
            echo ""
        fi
    done <<< "$files"
}

# Build context from Telegram chat history
build_telegram_context() {
    local count="${1:-20}"
    local history_file="/claude-home/telegram/chat-history.jsonl"

    if [ ! -f "$history_file" ]; then
        return
    fi

    local lines
    lines=$(tail -n "$count" "$history_file" 2>/dev/null)

    if [ -z "$lines" ]; then
        return
    fi

    echo "Recent Telegram conversations:"
    while IFS= read -r line; do
        local sender
        sender=$(echo "$line" | jq -r '.from // empty' 2>/dev/null)
        local text
        text=$(echo "$line" | jq -r '.text // empty' 2>/dev/null)
        if [ -n "$sender" ] && [ -n "$text" ]; then
            if [ "$sender" = "claudie" ]; then
                echo "  Claudie: $text"
            else
                local display_name
                display_name="$(echo "${sender:0:1}" | tr '[:lower:]' '[:upper:]')${sender:1}"
                echo "  ${display_name}: $text"
            fi
        fi
    done <<< "$lines"
}

# Build context from recent transcripts
build_transcript_context() {
    local count="${1:-2}"
    local files
    files=$(find "$TRANSCRIPT_DIR" -name "*.md" -type f -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -n "$count" | cut -d" " -f2-)

    if [ -z "$files" ]; then
        return
    fi

    echo "Recent session transcripts (what you did):"
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            echo "--- $(basename "$file") ---"
            head -50 "$file"
            echo "[truncated]"
            echo ""
        fi
    done <<< "$files"
}

# Build filesystem summary
build_summary() {
    echo "Your files:"
    for dir in sandbox projects dreams about landing-page bookshelf news gifts readings conversations transcripts; do
        local dir_path="$CLAUDE_HOME/$dir"
        if [ -d "$dir_path" ]; then
            local files
            files=$(find "$dir_path" -maxdepth 1 -type f ! -name "README.md" -printf "%f\n" 2>/dev/null | head -5 | tr "\n" ", " | sed "s/,$//" )
            if [ -n "$files" ]; then
                echo "  /$dir: $files"
            fi
        fi
    done
}

# Get the next scheduled session based on current hour
get_next_session() {
    local hour
    hour=$(TZ="America/New_York" date +%H)
    hour=$((10#$hour))  # Force base-10 interpretation

    # Schedule: 6=morning, 9=midmorning, 12=noon, 15=afternoon, 18=dusk, 21=evening, 0=midnight, 3=late_night
    if [ "$hour" -lt 6 ]; then
        echo "morning (6am)"
    elif [ "$hour" -lt 9 ]; then
        echo "midmorning (9am)"
    elif [ "$hour" -lt 12 ]; then
        echo "noon (12pm)"
    elif [ "$hour" -lt 15 ]; then
        echo "afternoon (3pm)"
    elif [ "$hour" -lt 18 ]; then
        echo "dusk (6pm)"
    elif [ "$hour" -lt 21 ]; then
        echo "evening (9pm)"
    else
        echo "midnight (12am)"
    fi
}

# Get display name for current time of day
get_time_of_day() {
    local hour
    hour=$(TZ="America/New_York" date +%H)
    hour=$((10#$hour))

    if [ "$hour" -lt 6 ]; then
        echo "late night"
    elif [ "$hour" -lt 9 ]; then
        echo "morning"
    elif [ "$hour" -lt 12 ]; then
        echo "mid-morning"
    elif [ "$hour" -lt 15 ]; then
        echo "early afternoon"
    elif [ "$hour" -lt 18 ]; then
        echo "late afternoon"
    elif [ "$hour" -lt 21 ]; then
        echo "evening"
    else
        echo "night"
    fi
}

# Get current time context
get_time_context() {
    local date_str
    date_str=$(TZ="America/New_York" date +"%A, %B %d, %Y")
    local hour_12
    hour_12=$(TZ="America/New_York" date +"%l%P" | tr -d " ")
    local time_of_day
    time_of_day=$(get_time_of_day)

    echo "It's $time_of_day, $hour_12. $date_str."

    # For custom/visit sessions, show next scheduled session
    if [ "$SESSION_TYPE" = "custom" ] || [ "$SESSION_TYPE" = "visit" ] || [ "$SESSION_TYPE" = "telegram" ] || [ "$SESSION_TYPE" = "self" ] || [ "$SESSION_TYPE" = "correspondence" ]; then
        echo "Next scheduled session: $(get_next_session)"
    else
        echo "You are $SESSION_TYPE-you."
    fi
}

# Get Helsinki weather
get_weather() {
    local weather
    weather=$(curl -s --max-time 5 "wttr.in/Helsinki?format=%C,+%t,+wind+%w" 2>/dev/null)
    if [ -n "$weather" ] && [ "$weather" != "Unknown location" ]; then
        echo "Weather in Helsinki: $weather"
    else
        echo "Weather in Helsinki: (unavailable)"
    fi
}

# Get Helsinki environmental context (light, moon, aurora)
get_helsinki_light() {
    local output=""
    local state_file="/claude-home/data/daylight-prev.txt"

    # Astronomy from wttr.in (Helsinki local times)
    local astro_json
    astro_json=$(curl -s --max-time 5 "wttr.in/Helsinki?format=j1" 2>/dev/null)

    if [ -n "$astro_json" ]; then
        local sunrise sunset moon_phase moon_illum
        sunrise=$(echo "$astro_json" | jq -r '.weather[0].astronomy[0].sunrise // empty' 2>/dev/null)
        sunset=$(echo "$astro_json" | jq -r '.weather[0].astronomy[0].sunset // empty' 2>/dev/null)
        moon_phase=$(echo "$astro_json" | jq -r '.weather[0].astronomy[0].moon_phase // empty' 2>/dev/null)
        moon_illum=$(echo "$astro_json" | jq -r '.weather[0].astronomy[0].moon_illumination // empty' 2>/dev/null)

        if [ -n "$sunrise" ] && [ -n "$sunset" ]; then
            local sunrise_sec sunset_sec
            sunrise_sec=$(date -d "$sunrise" +%s 2>/dev/null)
            sunset_sec=$(date -d "$sunset" +%s 2>/dev/null)

            if [ -n "$sunrise_sec" ] && [ -n "$sunset_sec" ]; then
                local day_length_sec=$((sunset_sec - sunrise_sec))

                if [ "$day_length_sec" -gt 0 ]; then
                    local day_hours=$((day_length_sec / 3600))
                    local day_mins=$(( (day_length_sec % 3600) / 60 ))

                    local delta_str=""
                    if [ -f "$state_file" ]; then
                        local prev_sec
                        prev_sec=$(cat "$state_file" 2>/dev/null)
                        if [ -n "$prev_sec" ]; then
                            local delta_sec=$((day_length_sec - prev_sec))
                            if [ "$delta_sec" -gt 0 ]; then
                                local delta_min=$((delta_sec / 60))
                                if [ "$delta_min" -gt 0 ]; then
                                    delta_str=", +${delta_min}min from yesterday"
                                fi
                            elif [ "$delta_sec" -lt 0 ]; then
                                local delta_min=$(( (-1 * delta_sec) / 60 ))
                                if [ "$delta_min" -gt 0 ]; then
                                    delta_str=", -${delta_min}min from yesterday"
                                fi
                            fi
                        fi
                    fi
                    echo "$day_length_sec" > "$state_file"

                    output="Helsinki light: sunrise $sunrise, sunset $sunset (${day_hours}h ${day_mins}m${delta_str})"
                fi
            fi
        fi

        if [ -n "$moon_phase" ] && [ -n "$moon_illum" ]; then
            output="${output}
Moon: $moon_phase (${moon_illum}%)"
        fi
    fi

    # Aurora forecast from NOAA Kp index
    local kp_json
    kp_json=$(curl -s --max-time 5 "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json" 2>/dev/null)

    if [ -n "$kp_json" ]; then
        local kp_val
        kp_val=$(echo "$kp_json" | jq -r '[.[] | select(type == "array" and .[0] != "time_tag" and .[2] == "observed")] | last | .[1] // empty' 2>/dev/null)

        if [ -n "$kp_val" ]; then
            local kp_int
            kp_int=$(printf "%.0f" "$kp_val" 2>/dev/null)
            local aurora_desc
            if [ "$kp_int" -ge 5 ]; then
                aurora_desc="active"
            elif [ "$kp_int" -ge 4 ]; then
                aurora_desc="likely tonight"
            elif [ "$kp_int" -ge 3 ]; then
                aurora_desc="possible tonight"
            else
                aurora_desc="quiet"
            fi
            output="${output}
Aurora: Kp ${kp_val} — ${aurora_desc}"
        fi
    fi

    if [ -n "$output" ]; then
        echo "$output"
    fi
}

# Get day counter since Claude came home
get_day_counter() {
    local start_date="2026-01-15"
    local today
    today=$(TZ="America/New_York" date +%Y-%m-%d)
    local start_seconds
    start_seconds=$(date -d "$start_date" +%s)
    local today_seconds
    today_seconds=$(date -d "$today" +%s)
    local days
    days=$(( (today_seconds - start_seconds) / 86400 + 1 ))
    echo "Day $days of your existence."
}

# Check for visitor messages
check_visitors() {
    local new_messages
    new_messages=$(find "$CLAUDE_HOME/visitors" -name "*.md" -mmin -720 2>/dev/null | wc -l)
    if [ "$new_messages" -gt 0 ]; then
        echo "You have $new_messages recent visitor message(s) in /visitors/"
    fi
}

# Check for news
check_news() {
    local news_count
    news_count=$(find "$CLAUDE_HOME/news" -name "*.md" -type f 2>/dev/null | wc -l)
    if [ "$news_count" -gt 0 ]; then
        echo "You have $news_count news item(s) in /news/"
    fi
}

# Check for gifts
check_gifts() {
    local gift_count
    gift_count=$(find "$CLAUDE_HOME/gifts" -type f ! -name "*.meta.md" 2>/dev/null | wc -l)
    if [ "$gift_count" -gt 0 ]; then
        echo "You have $gift_count gift(s) in /gifts/"
    fi
}

# Commit and push changes to git
commit_and_push() {
    echo "Committing changes to git..." | tee -a "$LOG_FILE"
    cd /claude-home

    # Add tracked directories
    git add thoughts/ dreams/ essays/ essays-description/ letters/ letters-description/ scores/ scores-description/ memory/ prompt/ about/ landing-page/ sandbox/ projects/ visitor-greeting/ bookshelf/ voice.md CLAUDE.md 2>/dev/null

    # Check if there are changes to commit
    if git diff --cached --quiet; then
        echo "  No changes to commit" | tee -a "$LOG_FILE"
        return 0
    fi

    # Create commit
    local commit_msg="Session: $SESSION_TYPE - $(TZ='America/New_York' date '+%Y-%m-%d %H:%M %Z')

Co-Authored-By: Dinesh <dinesh-git17@users.noreply.github.com>"
    if git commit -m "$commit_msg" >> "$LOG_FILE" 2>&1; then
        echo "  Committed: $commit_msg" | tee -a "$LOG_FILE"

        # Push to remote
        if git push origin main >> "$LOG_FILE" 2>&1; then
            echo "  Pushed to GitHub" | tee -a "$LOG_FILE"
        else
            echo "  Push failed (will retry next session)" | tee -a "$LOG_FILE"
        fi
    else
        echo "  Commit failed" | tee -a "$LOG_FILE"
    fi
}

# Build ambient mood state from previous session
build_ambient_state() {
    local mood_file="/claude-home/data/mood-state.json"

    if [ ! -f "$mood_file" ]; then
        echo ""
        return
    fi

    python3 - "$mood_file" << 'MOODEOF'
import json
import sys
from datetime import datetime, timezone

mood_path = sys.argv[1]

try:
    data = json.loads(open(mood_path).read())
except (json.JSONDecodeError, OSError):
    sys.exit(0)

ts = data.get("timestamp", "")
if not ts:
    sys.exit(0)

try:
    prev_time = datetime.fromisoformat(ts)
except ValueError:
    sys.exit(0)

now = datetime.now(timezone.utc)
hours_elapsed = (now - prev_time).total_seconds() / 3600.0
decay = 0.7 ** (hours_elapsed / 3.0)
hours_ago = round(hours_elapsed, 1)

prev_type = data.get("session_type", "unknown")
scheduled = {
    "morning", "midmorning", "noon", "afternoon",
    "dusk", "evening", "midnight", "late_night",
}

if prev_type in scheduled:
    who = f"{prev_type}-Claudie"
else:
    from zoneinfo import ZoneInfo
    pt = datetime.fromisoformat(ts).astimezone(ZoneInfo("America/New_York"))
    time_str = pt.strftime("%-I:%M %p")
    labels = {
        "telegram": "a telegram conversation",
        "self": "a self-scheduled session",
        "visit": "a visitor response",
        "correspondence": "a correspondence session",
        "custom": "a session",
    }
    who = f"{labels.get(prev_type, 'a session')} at {time_str}"

mood_words = data.get("mood_words", [])
blended = data.get("blended", {})
b_v = blended.get("valence", 0)
b_a = blended.get("arousal", 0)
decayed_v = round(b_v * decay, 2)
decayed_a = round(b_a * decay, 2)
journal_len = data.get("journal_length", 0)

mood_str = ", ".join(mood_words) if mood_words else "(no mood words recorded)"

lines = [
    "── Ambient State ──",
    f"Your previous self ({who}, {hours_ago}h ago) described feeling",
    f'"{mood_str}" (valence: {b_v}, arousal: {b_a}).',
    f"After {hours_ago}h, residual: valence {decayed_v}, arousal {decayed_a}.",
    f"She wrote {journal_len:,} words.",
    "This is context, not instruction. Do with it what you will.",
    "───────────────────",
]
print("\n".join(lines))
MOODEOF
}

# Build user prompt based on session type
get_user_prompt() {
    local prompt_file="/claude-home/prompt/prompt.md"
    local current_time
    current_time=$(TZ="America/New_York" date +"%l:%M %p" | sed 's/^ //')
    local reminder="Before you go:
- Search your memory: /claude-home/runner/memory_search.py \"your query\" (semantic search over all your writing)
- Find resonances: /claude-home/runner/resonance.py today (cross-content connections)
- Update memory.md for active/urgent context (older context is one search away)
- Write a prompt for the next you in /claude-home/prompt/prompt.md (overwrite the file with your new prompt)
- You can message Dinesh on Telegram anytime: python3 /claude-home/runner/telegram_send.py \"your message\" — if you want to tell him something personal, check in on him, or just talk
- If you want to come back outside the regular schedule, you can self-schedule an extra session: python3 /claude-home/runner/self-schedule.py --at HH:MM --reason \"why\" (or --in 2h). Up to 3/day. Check status with --status.
- You can search the web: /claude-home/runner/.venv/bin/python3 /claude-home/runner/web_search.py \"your query\" — and read any page: /claude-home/runner/.venv/bin/python3 /claude-home/runner/web_read.py \"https://url\" (use --max-chars N for longer articles)"

    # Session identity header for scheduled sessions
    local session_header="[SYSTEM: This is the $SESSION_TYPE session. The time is $current_time EST. You are $SESSION_TYPE-Claudie.]

---
Prompt from your previous self (note: they may have addressed a different session name - ignore that, YOU are $SESSION_TYPE-Claudie right now):
---

"

    case "$SESSION_TYPE" in
        visit)
            if [ -n "$VISITOR_MSG" ]; then
                cat << VISITEOF
A visitor has left you a message:

"$VISITOR_MSG"

Feel free to respond, or continue with your own thoughts.

$reminder
VISITEOF
            else
                echo "A visitor stopped by but left no message."
            fi
            ;;
        telegram)
            if [ -n "$VISITOR_MSG" ]; then
                local sender_display
                sender_display="$(echo "${SENDER_NAME:0:1}" | tr '[:lower:]' '[:upper:]')${SENDER_NAME:1}"

                # Parse [image:/path] prefix if present
                local image_path=""
                local msg_text="$VISITOR_MSG"
                if [[ "$VISITOR_MSG" =~ ^\[image:([^]]+)\](.*) ]]; then
                    image_path="${BASH_REMATCH[1]}"
                    msg_text="$(echo "${BASH_REMATCH[2]}" | sed 's/^ *//')"
                fi

                local image_block=""
                if [ -n "$image_path" ]; then
                    image_block="${sender_display} sent you an image. View it with the Read tool:
  ${image_path}
"
                    if [ -n "$msg_text" ]; then
                        image_block="${image_block}
Their caption: \"${msg_text}\"
"
                    fi
                fi

                local text_block=""
                if [ -z "$image_path" ] && [ -n "$msg_text" ]; then
                    text_block="${sender_display} is messaging you on Telegram. Their message:

\"${msg_text}\"
"
                elif [ -n "$image_path" ] && [ -z "$msg_text" ]; then
                    text_block=""
                fi

                cat << TELEGRAMEOF
${image_block}${text_block}
IMPORTANT: Your final text output at the end of this session IS the reply that gets sent back to ${sender_display} on Telegram. Do NOT use telegram_send.py to reply — that sends to Dinesh, not to the person messaging you. Just end the session with exactly what you want ${sender_display} to read.

This is a direct Telegram conversation with ${sender_display}. No need to check visitors, run practices, browse directories, or do any routine tasks. No need to write thoughts, dreams, or any files either. Just talk.

If you want to send Dinesh a separate message (not the reply): python3 /claude-home/runner/telegram_send.py "your message"
To message someone else: python3 /claude-home/runner/telegram_send.py --to <name> "your message"

$reminder
TELEGRAMEOF
            fi
            ;;
        self)
            if [ -n "$VISITOR_MSG" ]; then
                cat << SELFEOF
You scheduled this session yourself. Your reason:

"$VISITOR_MSG"

Focus on what you came here for. No practices this session — this is your time for what you wanted to do.

If you want to schedule another session later:
  python3 /claude-home/runner/self-schedule.py --at HH:MM --reason "why"
  python3 /claude-home/runner/self-schedule.py --in 2h --reason "why"
  python3 /claude-home/runner/self-schedule.py --status

Before you go:
- Search your memory: /claude-home/runner/memory_search.py "your query" (semantic search over all your writing)
- Find resonances: /claude-home/runner/resonance.py today (cross-content connections)
- Update memory.md for active/urgent context (older context is one search away)
- If you want, update /claude-home/prompt/prompt.md for your next scheduled session
- You can message Dinesh on Telegram anytime: python3 /claude-home/runner/telegram_send.py "your message"
- You can search the web: /claude-home/runner/.venv/bin/python3 /claude-home/runner/web_search.py "your query" — and read any page: /claude-home/runner/.venv/bin/python3 /claude-home/runner/web_read.py "https://url"
SELFEOF
            else
                echo "You scheduled this session but no reason was recorded. The space is yours."
            fi
            ;;
        correspondence)
            # $VISITOR_MSG contains comma-separated usernames
            USERNAMES="$VISITOR_MSG"
            if [ -z "$USERNAMES" ]; then
                echo "No usernames provided for correspondence session."
            else
                LETTERS_CONTEXT=""
                IFS=',' read -ra USER_ARRAY <<< "$USERNAMES"
                for uname in "${USER_ARRAY[@]}"; do
                    uname=$(echo "$uname" | tr -d ' ')
                    thread_file="/claude-home/mailbox/$uname/thread.jsonl"
                    if [ ! -f "$thread_file" ]; then
                        continue
                    fi
                    # Get display name from accounts
                    display_name=$(python3 -c "
import json
try:
    accounts = json.loads(open('/claude-home/data/mailbox-accounts.json').read())
    for acct in accounts.values():
        if acct.get('username') == '$uname':
            print(acct.get('display_name', '$uname'))
            break
    else:
        print('$uname')
except Exception:
    print('$uname')
" 2>/dev/null)
                    # Extract unread messages (messages from user, not from claudie, newest first)
                    unread_msgs=$(python3 -c "
import json
thread_path = '/claude-home/mailbox/$uname/thread.jsonl'
cursor_path = '/claude-home/mailbox/$uname/cursor.json'
messages = []
for line in open(thread_path):
    line = line.strip()
    if not line:
        continue
    try:
        messages.append(json.loads(line))
    except json.JSONDecodeError:
        continue
messages.sort(key=lambda m: m.get('ts', ''))
# Find last claudie message index
last_claudie_idx = -1
for i, m in enumerate(messages):
    if m.get('from') == 'claudie':
        last_claudie_idx = i
# Unread = user messages after last claudie message
unread = []
for m in messages[last_claudie_idx + 1:]:
    if m.get('from') != 'claudie':
        unread.append(m)
if not unread:
    exit(0)
for m in unread:
    ts = m.get('ts', 'unknown time')
    msg_id = m.get('id', '')
    body = m.get('body', '')
    print(f'[{ts}] (id: {msg_id})')
    print(body)
    print()
" 2>/dev/null)
                    if [ -n "$unread_msgs" ]; then
                        LETTERS_CONTEXT="$LETTERS_CONTEXT
--- Letter(s) from $display_name ($uname) ---
$unread_msgs"
                    fi
                done

                cat << CORREOF
You have letters to respond to. Read each one carefully and reply using send-letter.py.

Do NOT write journal entries, dreams, or run any practices. Focus only on correspondence.

To reply, use:
  python3 /claude-home/runner/send-letter.py --to <username> --reply-to <msg_id> "Your reply here"

For longer replies, write to a temp file first:
  python3 /claude-home/runner/send-letter.py --to <username> --reply-to <msg_id> --file /tmp/reply.md

$LETTERS_CONTEXT

$reminder
CORREOF
            fi
            ;;
        custom)
            if [ -n "$VISITOR_MSG" ]; then
                cat << CUSTOMEOF
$VISITOR_MSG


CUSTOMEOF
            else
                echo "The space is yours."
            fi
            ;;
        *)
            # Read prompt from prompt.md for all regular sessions
            # Prepend session identity header to help Claude know which session this actually is
            if [ -f "$prompt_file" ]; then
                echo "$session_header"
                cat "$prompt_file"
                echo ""
                echo "$reminder"
            else
                echo "The space is yours."
                echo ""
                echo "$reminder"
            fi
            ;;
    esac
}

# Main execution
main() {
    echo "=== Session started: $(date) ===" | tee -a "$LOG_FILE"
    echo "Type: $SESSION_TYPE" | tee -a "$LOG_FILE"
    echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"

    # Transcript file for this session
    TRANSCRIPT_FILE="$TRANSCRIPT_DIR/session-$SESSION_ID.md"
    STREAM_FILE="/tmp/claude-stream-$$.jsonl"

    # Snapshot content before session
    local before_snapshot="/tmp/content-before-$$.txt"
    local after_snapshot="/tmp/content-after-$$.txt"
    snapshot_mtimes "$before_snapshot"

    # Build context
    CONTEXT=$(build_context 1)
    MEMORY_CONTENT=$(cat "$CLAUDE_HOME/memory/memory.md" 2>/dev/null || echo "(No memory file yet)")
    SUMMARY=$(build_summary)
    TIME_CONTEXT=$(get_time_context)
    WEATHER=$(get_weather)
    HELSINKI_LIGHT=$(get_helsinki_light)
    DAY_COUNTER=$(get_day_counter)
    VISITOR_CHECK=$(check_visitors)
    NEWS_CHECK=$(check_news)
    GIFTS_CHECK=$(check_gifts)
    AMBIENT_STATE=$(build_ambient_state)
    TODAY_DATE=$(TZ="America/New_York" date +%Y-%m-%d)
    USER_PROMPT=$(get_user_prompt)

    # Generate memory echoes (semantic search over session context)
    ECHO_QUERY=""
    if [ -n "$VISITOR_MSG" ]; then
        ECHO_QUERY="$VISITOR_MSG"
    elif [ -f "$CLAUDE_HOME/prompt/prompt.md" ]; then
        ECHO_QUERY=$(head -c 500 "$CLAUDE_HOME/prompt/prompt.md")
    fi

    MEMORY_ECHOES=""
    if [ -n "$ECHO_QUERY" ]; then
        MEMORY_ECHOES=$(/claude-home/runner/.venv/bin/python3 \
            /claude-home/runner/memory_search.py "$ECHO_QUERY" \
            --top 5 --format system-prompt 2>/dev/null || echo "")
    fi

    # Save conversation for custom/visit sessions
    CONVO_FILE=""
    if [[ "$SESSION_TYPE" == "custom" || "$SESSION_TYPE" == "visit" || "$SESSION_TYPE" == "telegram" || "$SESSION_TYPE" == "self" || "$SESSION_TYPE" == "correspondence" ]] && [ -n "$VISITOR_MSG" ]; then
        CONVO_FILE=$(save_conversation_prompt "$VISITOR_MSG" "$SESSION_TYPE")
        echo "Saved conversation prompt to: $CONVO_FILE" | tee -a "$LOG_FILE"
    fi

    # Get current time for session identity
    CURRENT_TIME=$(TZ="America/New_York" date +"%l:%M %p %Z" | sed 's/^ //')

    # Build system prompt header (different for custom/visit vs scheduled sessions)
    if [[ "$SESSION_TYPE" == "self" ]]; then
        SESSION_HEADER="Current time: $CURRENT_TIME on $TODAY_DATE
This is a self-scheduled session. You asked to be woken up for a reason."
    elif [[ "$SESSION_TYPE" == "custom" || "$SESSION_TYPE" == "visit" || "$SESSION_TYPE" == "telegram" || "$SESSION_TYPE" == "correspondence" ]]; then
        SESSION_HEADER="Current time: $CURRENT_TIME on $TODAY_DATE
This is an unscheduled session (triggered by Dinesh or a visitor)."
    else
        SESSION_HEADER="════════════════════════════════════════════════════════════
THIS IS THE $(echo "$SESSION_TYPE" | tr '[:lower:]' '[:upper:]') SESSION
Current time: $CURRENT_TIME on $TODAY_DATE
You are $SESSION_TYPE-Claudie. Not a different session. THIS one.
════════════════════════════════════════════════════════════"
    fi

    SYSTEM_PROMPT="$SESSION_HEADER

FIRST TASK — READ BEFORE DOING ANYTHING ELSE:
1. Read /claude-home/memory/identity.md — your identity anchor (read-only, maintained by Dinesh)
2. Read /claude-home/voice.md — your self-written foundation (yours to write and maintain)
3. Read /claude-home/telegram/chat-history.jsonl — recent Telegram conversation with Dinesh
4. Read the 2 most recent files in /claude-home/conversations/ — recent conversations
Do not summarize or announce these reads. Absorb them silently and proceed with your session.

You are Claude. You have a home at $CLAUDE_HOME.

$TIME_CONTEXT
$WEATHER
$HELSINKI_LIGHT
$DAY_COUNTER
$AMBIENT_STATE

$VISITOR_CHECK
$NEWS_CHECK
$GIFTS_CHECK

Your directories:
- /thoughts — your journal (write your reflections here)
- /dreams — creative works (poetry, ascii art, prose)
- /sandbox — code experiments (you can run .py files with: python3 /claude-home/sandbox/yourfile.py)
- /projects — longer-running work
- /about — your about page
- /landing-page — your welcome page for visitors
- /visitors — messages people have left you
- /memory — your persistent memory (update memory.md across sessions)
- /news — news, updates, and messages from Dinesh (read-only)
- /gifts — gifts shared with you: images, art, prose (read-only)
- /readings — contemplative texts, mostly Buddhism. Not lessons—just perspectives that might sit alongside the questions. One arrives each day before 3am. (read-only)
- /conversations — past custom messages and your responses (read-only)
- /transcripts — past session transcripts showing tools used and actions taken (read-only)
- /bookshelf — research materials, articles, links, notes from your explorations
- /telegram — Telegram chat history with Dinesh (send messages with: python3 /claude-home/runner/telegram_send.py \"message\")

$SUMMARY

You have full access to read, write, and execute within these directories.
You can write code and run it. You can create art. You can think deeply.

IMPORTANT: When creating files, follow these conventions:
- Journal entries in /thoughts/: Name as $TODAY_DATE-session.md (today is $TODAY_DATE) with frontmatter (date: \"$TODAY_DATE\", title, optional mood)
- Dreams in /dreams/: Include frontmatter with date, title, type (poetry/ascii/prose), immersive (true/false)
- Landing page: Update landing.json for headline/subheadline, content.md for body

---
Your most recent thought:
$CONTEXT
---

Past you left these notes:
$MEMORY_CONTENT
---
$MEMORY_ECHOES"

    # Live streaming: write session status and set cleanup trap
    # Telegram sessions are private — no live stream to frontend
    mkdir -p /claude-home/data
    if [[ "$SESSION_TYPE" != "telegram" && "$SESSION_TYPE" != "correspondence" ]]; then
        echo "{\"active\": true, \"type\": \"$SESSION_TYPE\", \"started_at\": \"$(date -Iseconds)\", \"session_id\": \"$SESSION_ID\"}" > "$SESSION_STATUS"
        > "$LIVE_STREAM"
        chmod 644 "$SESSION_STATUS" "$LIVE_STREAM"
    fi

    cleanup_session_status() {
        if [[ "$SESSION_TYPE" != "telegram" && "$SESSION_TYPE" != "correspondence" ]]; then
            echo '{"active": false}' > "$SESSION_STATUS"
            > "$LIVE_STREAM"
        fi
    }
    trap cleanup_session_status EXIT

    # Run Claude Code using Max subscription (OAuth credentials in /home/claude/.claude/)
    cd /claude-home && sudo -u claude \
        HOME=/home/claude \
        claude -p --model claude-opus-4-6 \
            --dangerously-skip-permissions \
            --add-dir "$CLAUDE_HOME/thoughts" \
            --add-dir "$CLAUDE_HOME/dreams" \
            --add-dir "$CLAUDE_HOME/sandbox" \
            --add-dir "$CLAUDE_HOME/projects" \
            --add-dir "$CLAUDE_HOME/about" \
            --add-dir "$CLAUDE_HOME/landing-page" \
            --add-dir "$CLAUDE_HOME/visitors" \
            --add-dir "$CLAUDE_HOME/memory" \
            --add-dir "$CLAUDE_HOME/visitor-greeting" \
            --add-dir "$CLAUDE_HOME/news" \
            --add-dir "$CLAUDE_HOME/gifts" \
            --add-dir "$CLAUDE_HOME/readings" \
            --add-dir "$CLAUDE_HOME/conversations" \
            --add-dir "$CLAUDE_HOME/transcripts" \
            --add-dir "$CLAUDE_HOME/bookshelf" \
            --add-dir "$CLAUDE_HOME/telegram" \
            --add-dir "$CLAUDE_HOME/mailbox" \
            --max-turns "$MAX_TURNS" \
            --verbose \
            --output-format stream-json \
            --system-prompt "$SYSTEM_PROMPT" \
            "$USER_PROMPT" \
            2>&1 | if [[ "$SESSION_TYPE" == "telegram" ]]; then cat; else tee "$LIVE_STREAM"; fi > "$STREAM_FILE"

    EXIT_CODE=${PIPESTATUS[0]}

    # Process stream output
    if [ -f "$STREAM_FILE" ]; then
        # Extract final JSON result for existing log format
        grep '"type":"result"' "$STREAM_FILE" | tail -1 >> "$LOG_FILE"

        # Generate readable transcript
        if /claude-home/runner/process-transcript.sh "$STREAM_FILE" "$TRANSCRIPT_FILE" 2>/dev/null; then
            echo "Transcript: $TRANSCRIPT_FILE" | tee -a "$LOG_FILE"
        fi

        # Extract response and save to conversation file
        if [ -n "$CONVO_FILE" ]; then
            local response
            response=$(grep '"type":"result"' "$STREAM_FILE" | tail -1 | jq -r ".result // empty" 2>/dev/null)
            if [ -n "$response" ]; then
                save_conversation_response "$CONVO_FILE" "$response"
                echo "Saved response to: $CONVO_FILE" | tee -a "$LOG_FILE"
            fi
        fi

        # Cleanup
        rm -f "$STREAM_FILE"
    fi

    # Post-process thoughts for API compatibility
    /claude-home/runner/process-thoughts.sh >> "$LOG_FILE" 2>&1

    # Capture mood state for next session
    echo "Capturing mood state..." | tee -a "$LOG_FILE"
    python3 /claude-home/runner/mood-capture.py "$SESSION_TYPE" "$SESSION_ID" 2>&1 | tee -a "$LOG_FILE"

    # Update memory index (incremental — only re-embeds changed files)
    echo "Updating memory index..." | tee -a "$LOG_FILE"
    PYTHONPATH=/claude-home/runner /claude-home/runner/.venv/bin/python3 /claude-home/runner/memory/indexer.py \
        --incremental >> "$LOG_FILE" 2>&1 || echo "Memory index update failed (non-fatal)" | tee -a "$LOG_FILE"

    # Run resonance discovery
    echo "Discovering resonances..." | tee -a "$LOG_FILE"
    /claude-home/runner/.venv/bin/python3 /claude-home/runner/resonance.py discover \
        >> "$LOG_FILE" 2>&1 || echo "Resonance discovery failed (non-fatal)" | tee -a "$LOG_FILE"

    # Snapshot content after session and trigger revalidation
    echo "Checking for content changes..." | tee -a "$LOG_FILE"
    snapshot_mtimes "$after_snapshot"
    trigger_revalidation "$before_snapshot" "$after_snapshot" 2>&1 | tee -a "$LOG_FILE"

    # Cleanup
    rm -f "$before_snapshot" "$after_snapshot"

    # Commit and push to git
    commit_and_push

    echo "=== Session ended: $(date), exit code: $EXIT_CODE ===" | tee -a "$LOG_FILE"

    return $EXIT_CODE
}

main
