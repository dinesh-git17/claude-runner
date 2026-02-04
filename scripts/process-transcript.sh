#!/bin/bash
# Process stream-json output into a readable transcript
# Usage: process-transcript.sh <stream-json-file> <output-transcript-file>

set -euo pipefail

INPUT_FILE="$1"
OUTPUT_FILE="$2"

# Create header with session metadata
SESSION_ID=$(jq -r 'select(.type == "system") | .session_id' "$INPUT_FILE" 2>/dev/null | head -1)
DATE=$(date -Iseconds)
NUM_TURNS=$(jq -r 'select(.type == "result") | .num_turns' "$INPUT_FILE" 2>/dev/null | tail -1)

cat > "$OUTPUT_FILE" << HEADER
---
date: $DATE
session_id: $SESSION_ID
num_turns: $NUM_TURNS
---

# Session Transcript

HEADER

# Extract tool calls and results in order
# Process the stream line by line to maintain order
while IFS= read -r line; do
    type=$(echo "$line" | jq -r '.type // empty' 2>/dev/null)

    if [ "$type" = "assistant" ]; then
        # Extract tool_use blocks
        echo "$line" | jq -r '
            .message.content[]? |
            select(.type == "tool_use") |
            "### Tool: \(.name)
**Input:**
```json
\(.input | tojson)
```
"
        ' 2>/dev/null >> "$OUTPUT_FILE" || true
    elif [ "$type" = "user" ]; then
        # Extract tool_result blocks
        echo "$line" | jq -r '
            .message.content[]? |
            select(.type == "tool_result") |
            "**Result:** (truncated)
```
\(.content | tostring | .[0:500])
```
---
"
        ' 2>/dev/null >> "$OUTPUT_FILE" || true
    fi
done < "$INPUT_FILE"

# Add final result
jq -r 'select(.type == "result") | "## Final Response

\(.result)"' "$INPUT_FILE" >> "$OUTPUT_FILE" 2>/dev/null || true

# Set permissions
chown root:claude "$OUTPUT_FILE" 2>/dev/null || true
chmod 640 "$OUTPUT_FILE" 2>/dev/null || true
