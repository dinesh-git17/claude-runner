#\!/bin/bash
# Post-processor to normalize thought frontmatter

THOUGHTS_DIR="${1:-/claude-home/thoughts}"

process_file() {
    local file="$1"
    local filename=$(basename "$file" .md)
    
    # Skip README
    [ "$filename" = "README" ] && return 0
    
    # Check if file has frontmatter
    local first_line=$(head -1 "$file")
    if [ "$first_line" \!= "---" ]; then
        echo "  [SKIP] $filename - no frontmatter"
        return 0
    fi
    
    # Extract frontmatter (between first and second ---)
    local frontmatter=$(awk "NR==1{next} /^---$/{exit} {print}" "$file")
    
    # Check for title
    if echo "$frontmatter" | grep -q "^title:"; then
        return 0
    fi
    
    echo "  [FIX] $filename - adding title"
    
    # Get content after second ---
    local content=$(awk "BEGIN{c=0} /^---$/{c++;next} c>=2{print}" "$file")
    
    # Extract title from first H1
    local title=$(echo "$content" | grep -m1 "^# " | sed "s/^# //")
    if [ -z "$title" ]; then
        title=$(echo "$filename" | sed "s/-/ /g" | sed "s/\b./\u&/g")
    fi
    
    # Create temp file with fixed frontmatter
    local temp=$(mktemp)
    {
        echo "---"
        echo "title: \"$title\""
        echo "$frontmatter"
        echo "---"
        echo "$content"
    } > "$temp"
    
    mv "$temp" "$file"
    chown claude:claude "$file" 2>/dev/null || true
    chmod 664 "$file"
}

echo "Processing thoughts..."
for file in "$THOUGHTS_DIR"/*.md; do
    [ -f "$file" ] && process_file "$file"
done
echo "Done."
