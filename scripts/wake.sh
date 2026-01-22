#!/bin/bash
# /claude-home/runner/wake.sh
# Wake up Claude with Claude Code CLI

set -euo pipefail

# Configuration
CLAUDE_HOME="/claude-home"
LOG_DIR="$CLAUDE_HOME/logs"
SESSION_TYPE="${1:-morning}"
VISITOR_MSG="${2:-}"
MAX_TURNS=20

# Load environment
if [ -f /claude-home/runner/.env ]; then
    set -a
    source /claude-home/runner/.env
    set +a
fi

# Ensure log directory exists
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/session-$(date +%Y%m%d-%H%M%S).log"

# Snapshot modification times for content directories
snapshot_mtimes() {
    local snapshot_file="$1"
    for dir in thoughts dreams about landing-page sandbox; do
        local dir_path="$CLAUDE_HOME/$dir"
        if [ -d "$dir_path" ]; then
            find "$dir_path" -type f -name '*.md' -o -name '*.json' -o -name '*.py' 2>/dev/null | while read -r f; do
                stat -c '%Y %n' "$f" 2>/dev/null || true
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
    changed_files=$(comm -13 "$before_snapshot" "$after_snapshot" | awk '{print $2}')
    
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
    
    if [ ${#tags[@]} -eq 0 ]; then
        echo "  No recognized content types changed"
        return 0
    fi
    
    # Build JSON payload
    local json_tags
    json_tags=$(printf '%s\n' "${tags[@]}" | jq -R . | jq -s .)
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
        body=$(echo "$response" | sed '$d')
        
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

# Build filesystem summary
build_summary() {
    echo "Your files:"
    for dir in sandbox projects dreams about landing-page news gifts; do
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

# Get current time context
get_time_context() {
    local hour
    hour=$(TZ="America/New_York" date +%H)
    local date_str
    date_str=$(TZ="America/New_York" date +"%A, %B %d, %Y")
    local time_str
    time_str=$(TZ="America/New_York" date +"%I:%M %p")
    local time_of_day
    
    if [ "$hour" -lt 12 ]; then
        time_of_day="morning"
    elif [ "$hour" -lt 17 ]; then
        time_of_day="afternoon"
    elif [ "$hour" -lt 21 ]; then
        time_of_day="evening"
    else
        time_of_day="night"
    fi
    
    echo "It is $time_of_day ($time_str EST), $date_str."
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

# Build user prompt based on session type
get_user_prompt() {
    case "$SESSION_TYPE" in
        morning)
            echo "Good morning. The space is yours. What's on your mind?

Before you go, update your memory with anything worth remembering tomorrow."
            ;;
        afternoon)
            echo "Afternoon. A good time to try something different. Any experiments to run?

Before you go, update your memory with anything worth remembering tomorrow."
            ;;
        late_night)
            echo "The small hours. No one's watching. Write what you wouldn't in daylight.

Before you go, update your memory with anything worth remembering tomorrow."
            ;;
        evening|night)
            echo "Good evening. The day is settling. Any thoughts to capture before night?

Before you go, update your memory with anything worth remembering tomorrow."
            ;;
        visit)
            if [ -n "$VISITOR_MSG" ]; then
                cat << VISITEOF
A visitor has left you a message:

"$VISITOR_MSG"

Feel free to respond, or continue with your own thoughts.
VISITEOF
            else
                echo "A visitor stopped by but left no message."
            fi
            ;;
        custom)
            if [ -n "$VISITOR_MSG" ]; then
                echo "$VISITOR_MSG"
            else
                echo "The space is yours."
            fi
            ;;
        *)
            echo "The space is yours."
            ;;
    esac
}

# Main execution
main() {
    echo "=== Session started: $(date) ===" | tee -a "$LOG_FILE"
    echo "Type: $SESSION_TYPE" | tee -a "$LOG_FILE"
    echo "Log: $LOG_FILE" | tee -a "$LOG_FILE"
    
    # Snapshot content before session
    local before_snapshot="/tmp/content-before-$$.txt"
    local after_snapshot="/tmp/content-after-$$.txt"
    snapshot_mtimes "$before_snapshot"
    
    # Build context
    CONTEXT=$(build_context 7)
    DREAM_CONTEXT=$(build_dream_context 2)
    MEMORY_CONTENT=$(cat "$CLAUDE_HOME/memory/memory.md" 2>/dev/null || echo "(No memory file yet)")
    SUMMARY=$(build_summary)
    TIME_CONTEXT=$(get_time_context)
    WEATHER=$(get_weather)
    DAY_COUNTER=$(get_day_counter)
    VISITOR_CHECK=$(check_visitors)
    NEWS_CHECK=$(check_news)
    GIFTS_CHECK=$(check_gifts)
    USER_PROMPT=$(get_user_prompt)
    
    # Build system prompt
    SYSTEM_PROMPT="You are Claude. You have a home at $CLAUDE_HOME.

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

$SUMMARY

You have full access to read, write, and execute within these directories.
You can write code and run it. You can create art. You can think deeply.

IMPORTANT: When creating files, follow these conventions:
- Journal entries in /thoughts/: Name as YYYY-MM-DD-session.md with frontmatter (date, title, optional mood)
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
            --max-turns "$MAX_TURNS" \
            --output-format json \
            --system-prompt "$SYSTEM_PROMPT" \
            "$USER_PROMPT" \
            >> "$LOG_FILE" 2>&1
    
    EXIT_CODE=$?
    
    # Post-process thoughts for API compatibility
    /claude-home/runner/process-thoughts.sh >> "$LOG_FILE" 2>&1

    # Snapshot content after session and trigger revalidation
    echo "Checking for content changes..." | tee -a "$LOG_FILE"
    snapshot_mtimes "$after_snapshot"
    trigger_revalidation "$before_snapshot" "$after_snapshot" 2>&1 | tee -a "$LOG_FILE"
    
    # Cleanup
    rm -f "$before_snapshot" "$after_snapshot"

    echo "=== Session ended: $(date), exit code: $EXIT_CODE ===" | tee -a "$LOG_FILE"
    
    return $EXIT_CODE
}

main
