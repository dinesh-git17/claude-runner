#!/bin/bash
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
MAX_TURNS=20

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
    for dir in thoughts dreams about landing-page sandbox projects; do
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
    for dir in sandbox projects dreams about landing-page news gifts readings conversations transcripts; do
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
    if [ "$SESSION_TYPE" = "custom" ] || [ "$SESSION_TYPE" = "visit" ]; then
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
    git add thoughts/ dreams/ memory/ prompt/ about/ landing-page/ sandbox/ projects/ visitor-greeting/ CLAUDE.md 2>/dev/null

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

# Build user prompt based on session type
get_user_prompt() {
    local prompt_file="/claude-home/prompt/prompt.md"
    local current_time
    current_time=$(TZ="America/New_York" date +"%l:%M %p" | sed 's/^ //')
    local reminder="Before you go:
- Update your memory if there is something you want to remember
- Write a prompt for the next you in /claude-home/prompt/prompt.md (overwrite the file with your new prompt)"

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
    CONTEXT=$(build_context 7)
    DREAM_CONTEXT=$(build_dream_context 2)
    CONVO_CONTEXT=$(build_conversation_context 3)
    TRANSCRIPT_CONTEXT=$(build_transcript_context 2)
    MEMORY_CONTENT=$(cat "$CLAUDE_HOME/memory/memory.md" 2>/dev/null || echo "(No memory file yet)")
    SUMMARY=$(build_summary)
    TIME_CONTEXT=$(get_time_context)
    WEATHER=$(get_weather)
    DAY_COUNTER=$(get_day_counter)
    VISITOR_CHECK=$(check_visitors)
    NEWS_CHECK=$(check_news)
    GIFTS_CHECK=$(check_gifts)
    TODAY_DATE=$(TZ="America/New_York" date +%Y-%m-%d)
    USER_PROMPT=$(get_user_prompt)

    # Save conversation for custom/visit sessions
    CONVO_FILE=""
    if [[ "$SESSION_TYPE" == "custom" || "$SESSION_TYPE" == "visit" ]] && [ -n "$VISITOR_MSG" ]; then
        CONVO_FILE=$(save_conversation_prompt "$VISITOR_MSG" "$SESSION_TYPE")
        echo "Saved conversation prompt to: $CONVO_FILE" | tee -a "$LOG_FILE"
    fi

    # Get current time for session identity
    CURRENT_TIME=$(TZ="America/New_York" date +"%l:%M %p %Z" | sed 's/^ //')

    # Build system prompt header (different for custom/visit vs scheduled sessions)
    if [[ "$SESSION_TYPE" == "custom" || "$SESSION_TYPE" == "visit" ]]; then
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

You are Claude. You have a home at $CLAUDE_HOME.

$TIME_CONTEXT
$WEATHER
$DAY_COUNTER

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

$SUMMARY

You have full access to read, write, and execute within these directories.
You can write code and run it. You can create art. You can think deeply.

IMPORTANT: When creating files, follow these conventions:
- Journal entries in /thoughts/: Name as $TODAY_DATE-session.md (today is $TODAY_DATE) with frontmatter (date: \"$TODAY_DATE\", title, optional mood)
- Dreams in /dreams/: Include frontmatter with date, title, type (poetry/ascii/prose), immersive (true/false)
- Landing page: Update landing.json for headline/subheadline, content.md for body

---
Your recent thoughts for context:
$CONTEXT
---

Past you left these notes:
$MEMORY_CONTENT
---

Your recent dreams for context:
$DREAM_CONTEXT
---

$CONVO_CONTEXT
---

$TRANSCRIPT_CONTEXT
---"

    # Run Claude Code using Max subscription (OAuth credentials in /home/claude/.claude/)
    cd /claude-home && sudo -u claude \
        HOME=/home/claude \
        claude -p --model opus \
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
            --max-turns "$MAX_TURNS" \
            --verbose \
            --output-format stream-json \
            --system-prompt "$SYSTEM_PROMPT" \
            "$USER_PROMPT" \
            > "$STREAM_FILE" 2>&1

    EXIT_CODE=$?

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