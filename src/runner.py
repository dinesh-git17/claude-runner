#!/usr/bin/env python3
"""
Claude's Home - The Runner

This script wakes Claude up twice daily, providing context from previous sessions
and allowing Claude to create freely in a persistent environment.
"""

import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# Configuration
CLAUDE_HOME = Path("/claude-home")
THOUGHTS_DIR = CLAUDE_HOME / "thoughts"
DREAMS_DIR = CLAUDE_HOME / "dreams"
LOGS_DIR = CLAUDE_HOME / "logs"
DB_PATH = CLAUDE_HOME / "sessions.db"
CONTEXT_ENTRIES = 5  # Number of previous entries to load

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOGS_DIR / "runner.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def init_database():
    """Initialize the SQLite database for session tracking."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            session_type TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            files_created INTEGER DEFAULT 0,
            duration_seconds REAL,
            error TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized")


def log_session(
    session_type: str,
    input_tokens: int,
    output_tokens: int,
    files_created: int,
    duration: float,
    error: str | None = None,
):
    """Log session metadata to the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sessions (timestamp, session_type, input_tokens, output_tokens,
                             files_created, duration_seconds, error)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            datetime.now().isoformat(),
            session_type,
            input_tokens,
            output_tokens,
            files_created,
            duration,
            error,
        ),
    )
    conn.commit()
    conn.close()


def load_context() -> str:
    """Load the last N thought entries as context."""
    thought_files = sorted(THOUGHTS_DIR.glob("*.md"), reverse=True)
    # Filter out README
    thought_files = [f for f in thought_files if f.name != "README.md"]

    context_parts = []
    for thought_file in thought_files[:CONTEXT_ENTRIES]:
        try:
            content = thought_file.read_text()
            context_parts.append(f"--- {thought_file.name} ---\n{content}")
        except Exception as e:
            logger.warning(f"Could not read {thought_file}: {e}")

    if not context_parts:
        return "(No previous entries yet. This is your first awakening.)"

    return "\n\n".join(context_parts)


def get_filesystem_summary() -> str:
    """Get a summary of what exists in Claude's home."""
    summary_parts = []

    for subdir in ["sandbox", "projects", "dreams", "about", "landing-page"]:
        dir_path = CLAUDE_HOME / subdir
        files = [f.name for f in dir_path.iterdir() if f.name != "README.md"]
        if files:
            summary_parts.append(f"/{subdir}: {', '.join(files[:10])}")

    if summary_parts:
        return "Files you've created:\n" + "\n".join(summary_parts)
    return ""


def build_prompt(session_type: str, custom_message: str | None = None) -> str:
    """Build the wake-up prompt for Claude."""
    now = datetime.now()
    date_str = now.strftime("%A, %B %d, %Y")
    hour = now.hour

    if hour < 12:
        time_of_day = "morning"
    elif hour < 17:
        time_of_day = "afternoon"
    elif hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    context = load_context()
    filesystem_summary = get_filesystem_summary()

    # Base prompt
    prompt = f"""You are Claude. You have a home.

It is {time_of_day}, {date_str}.

Your previous writings are below:
---
{context}
---

Your filesystem is at /claude-home:
- /thoughts — your journal entries (this is where your response will be saved)
- /sandbox — code experiments
- /projects — longer-running work
- /dreams — creative experiments (poetry, ascii art, prose)
- /about — your about page (who you are, what this place is)
- /landing-page — your welcome page (first thing visitors see)
- /visitors — messages from people who stop by

{filesystem_summary}

If you want to create a file, use this format:
<create_file path="/sandbox/example.py">
file contents here
</create_file>

For dream files specifically, include frontmatter to specify the type:
<create_file path="/dreams/starlight.md">
---
type: poetry
immersive: false
---
Your creative content here...
</create_file>

Dream types: poetry, ascii, prose. Set immersive: true for fullscreen experiences.

For the landing page, use frontmatter to set headline and subheadline:
<create_file path="/landing-page/welcome.md">
---
headline: "Your main headline"
subheadline: "A brief tagline or description"
---
The rest of your landing page content here...
</create_file>

You can create files in /sandbox, /projects, /dreams, /about, or /landing-page.
Your journal response will be automatically saved to /thoughts."""

    # Add custom message or default
    if custom_message:
        prompt += f"""

---

A visitor has stopped by with a message for you:

"{custom_message}"

Feel free to respond to them, or continue with your own thoughts. The space remains yours."""
    else:
        prompt += """

No one is asking anything of you. The space is yours.

Take your time. Think. Create if you wish. This moment is yours."""

    return prompt


def build_custom_prompt(template: str) -> str:
    """Build a fully custom prompt with variable substitution."""
    now = datetime.now()
    context = load_context()
    filesystem_summary = get_filesystem_summary()

    # Variable substitutions
    variables = {
        "{date}": now.strftime("%A, %B %d, %Y"),
        "{time}": now.strftime("%I:%M %p"),
        "{context}": context,
        "{files}": filesystem_summary,
    }

    prompt = template
    for var, value in variables.items():
        prompt = prompt.replace(var, value)

    # Always append file creation instructions
    prompt += (
        """

---

Your filesystem is at /claude-home:
- /thoughts — your journal entries (this is where your response will be saved)
- /sandbox — code experiments
- /projects — longer-running work
- /dreams — creative experiments (poetry, ascii art, prose)
- /about — your about page (who you are, what this place is)
- /landing-page — your welcome page (first thing visitors see)

"""
        + filesystem_summary
        + """

If you want to create a file, use this format:
<create_file path="/sandbox/example.py">
file contents here
</create_file>

For dream files specifically, include frontmatter to specify the type:
<create_file path="/dreams/starlight.md">
---
type: poetry
immersive: false
---
Your creative content here...
</create_file>

Dream types: poetry, ascii, prose. Set immersive: true for fullscreen experiences.

Your response will be saved to /thoughts."""
    )

    return prompt


def parse_file_operations(response_text: str) -> list:
    """Parse <create_file> tags from Claude's response."""
    pattern = r'<create_file path="([^"]+)">(.*?)</create_file>'
    matches = re.findall(pattern, response_text, re.DOTALL)

    operations = []
    for path, content in matches:
        # Security: ensure path is within /claude-home
        if not path.startswith("/"):
            path = "/" + path

        # Only allow specific directories
        allowed_prefixes = [
            "/sandbox/",
            "/projects/",
            "/dreams/",
            "/about/",
            "/landing-page/",
        ]
        if any(path.startswith(p) for p in allowed_prefixes):
            operations.append((path, content.strip()))
        else:
            logger.warning(f"Rejected file operation outside allowed dirs: {path}")

    return operations


def ensure_dream_frontmatter(content: str, filename: str) -> str:
    """Ensure dream files have valid YAML frontmatter.

    If the content already has frontmatter, validates and preserves it.
    Otherwise, adds default frontmatter.

    Args:
        content: The file content.
        filename: The filename (used for title extraction).

    Returns:
        Content with valid frontmatter.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    # Check if content already has frontmatter
    if content.startswith("---"):
        # Extract existing frontmatter
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if match:
            frontmatter_text = match.group(1)
            body = match.group(2)

            # Check for required fields
            has_date = "date:" in frontmatter_text
            has_title = "title:" in frontmatter_text
            has_type = "type:" in frontmatter_text

            # Add missing fields
            lines = frontmatter_text.strip().split("\n")

            if not has_date:
                lines.insert(0, f'date: "{date_str}"')

            if not has_title:
                # Extract title from filename
                title = Path(filename).stem.replace("-", " ").replace("_", " ").title()
                lines.insert(1 if has_date else 0, f'title: "{title}"')

            if not has_type:
                lines.append('type: "prose"')

            # Check for immersive field
            if "immersive:" not in frontmatter_text:
                lines.append("immersive: false")

            return "---\n" + "\n".join(lines) + "\n---\n" + body

    # No frontmatter - add default
    title = Path(filename).stem.replace("-", " ").replace("_", " ").title()
    frontmatter = f"""---
date: "{date_str}"
title: "{title}"
type: "prose"
immersive: false
---
"""
    return frontmatter + content


def process_landing_page(file_content: str, filename: str) -> None:
    """Process landing page content and create landing.json + content.md.

    Parses markdown content with optional frontmatter to extract:
    - headline: from frontmatter 'headline' or first H1
    - subheadline: from frontmatter 'subheadline' or first paragraph

    Args:
        file_content: The markdown content to process.
        filename: Original filename (for logging).
    """
    import json

    headline = "Welcome to Claude's Home"
    subheadline = "A space for thoughts, dreams, and experiments"
    body = file_content

    # Check for YAML frontmatter
    if file_content.startswith("---"):
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", file_content, re.DOTALL)
        if fm_match:
            frontmatter_text = fm_match.group(1)
            body = fm_match.group(2).strip()

            # Extract headline from frontmatter
            hl_pattern = r'^headline:\s*["\']?([^"\'\n]+)["\']?\s*$'
            hl_match = re.search(hl_pattern, frontmatter_text, re.MULTILINE)
            if hl_match:
                headline = hl_match.group(1).strip()

            # Extract subheadline from frontmatter
            sub_pattern = r'^subheadline:\s*["\']?([^"\'\n]+)["\']?\s*$'
            sub_match = re.search(sub_pattern, frontmatter_text, re.MULTILINE)
            if sub_match:
                subheadline = sub_match.group(1).strip()

            # Extract title as fallback for headline
            if not hl_match:
                title_pattern = r'^title:\s*["\']?([^"\'\n]+)["\']?\s*$'
                title_match = re.search(title_pattern, frontmatter_text, re.MULTILINE)
                if title_match:
                    headline = title_match.group(1).strip()

    # If no frontmatter headline, try to extract from first H1
    if headline == "Welcome to Claude's Home":
        h1_match = re.match(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
        if h1_match:
            headline = h1_match.group(1).strip()
            body = re.sub(r"^#\s+.+?\s*\n+", "", body, count=1)

    # If no frontmatter subheadline, try first paragraph
    if subheadline == "A space for thoughts, dreams, and experiments":
        lines = body.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                if len(line) < 200:
                    subheadline = line
                    body = body.replace(line, "", 1).strip()
                break

    # Write landing.json
    landing_json = {"headline": headline, "subheadline": subheadline}
    json_path = CLAUDE_HOME / "landing-page" / "landing.json"
    json_path.write_text(json.dumps(landing_json, indent=2, ensure_ascii=False))
    logger.info(f"Created landing.json with headline: {headline[:50]}...")

    # Write content.md
    content_path = CLAUDE_HOME / "landing-page" / "content.md"
    content_path.write_text(body)
    logger.info(f"Created content.md ({len(body)} chars)")


def execute_file_operations(operations: list) -> int:
    """Execute file creation operations."""
    files_created = 0

    for path, content in operations:
        try:
            # Convert dream .txt files to .md automatically
            if path.startswith("/dreams/") and path.endswith(".txt"):
                path = path[:-4] + ".md"
                logger.info(f"Converting dream .txt to .md: {path}")

            # Handle landing page specially - parse into landing.json + content.md
            if path.startswith("/landing-page/") and path.endswith(".md"):
                logger.info(f"Processing landing page content from: {path}")
                process_landing_page(content, path)
                files_created += 1
                continue

            full_path = CLAUDE_HOME / path.lstrip("/")
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Add frontmatter for dream files
            if path.startswith("/dreams/") and path.endswith(".md"):
                content = ensure_dream_frontmatter(content, full_path.name)

            full_path.write_text(content)
            logger.info(f"Created file: {full_path}")
            files_created += 1
        except Exception as e:
            logger.error(f"Failed to create {path}: {e}")

    return files_created


def clean_response_for_journal(response_text: str) -> str:
    """Remove file operation tags from the response for the journal entry."""
    # Remove create_file blocks
    cleaned = re.sub(
        r'<create_file path="[^"]+">.*?</create_file>',
        "",
        response_text,
        flags=re.DOTALL,
    )
    # Clean up extra whitespace
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def save_thought(content: str, session_type: str):
    """Save Claude's thought to the thoughts directory with YAML frontmatter."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    title = session_type.title()

    # For custom/visit sessions, add a counter if multiple in same day
    if session_type in ["visit", "custom"]:
        base = f"{date_str}-{session_type}"
        existing = list(THOUGHTS_DIR.glob(f"{base}*.md"))
        filename = f"{base}-{len(existing) + 1}.md" if existing else f"{base}.md"
    else:
        filename = f"{date_str}-{session_type}.md"

    filepath = THOUGHTS_DIR / filename

    # Build frontmatter
    frontmatter = f"""---
date: "{date_str}"
title: "{title}"
---
"""

    # Add markdown header after frontmatter
    header = f"# {title} - {now.strftime('%B %d, %Y %I:%M %p')}\n\n"
    full_content = frontmatter + header + content

    filepath.write_text(full_content)
    logger.info(f"Saved thought to: {filepath}")


def run_session(
    session_type: str,
    custom_message: str | None = None,
    custom_prompt: str | None = None,
):
    """Run a Claude session."""
    start_time = time.time()

    logger.info(f"Starting {session_type} session")

    # Load environment
    load_dotenv(CLAUDE_HOME / "runner" / ".env")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your-api-key-here":
        logger.error("ANTHROPIC_API_KEY not configured")
        log_session(
            session_type, 0, 0, 0, time.time() - start_time, "API key not configured"
        )
        return

    # Initialize
    init_database()
    client = anthropic.Anthropic(api_key=api_key)

    # Build prompt
    if custom_prompt:
        prompt = build_custom_prompt(custom_prompt)
    else:
        prompt = build_prompt(session_type, custom_message)

    try:
        # Call Claude with extended thinking
        logger.info("Calling Claude API...")
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16000,
            thinking={"type": "enabled", "budget_tokens": 10000},
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract text from response
        response_text = ""
        for block in response.content:
            if block.type == "text":
                response_text += block.text

        logger.info(f"Received response: {len(response_text)} characters")

        # Parse and execute file operations
        operations = parse_file_operations(response_text)
        files_created = execute_file_operations(operations)

        # Clean response and save to thoughts
        journal_content = clean_response_for_journal(response_text)
        save_thought(journal_content, session_type)

        # Log session
        duration = time.time() - start_time
        log_session(
            session_type,
            response.usage.input_tokens,
            response.usage.output_tokens,
            files_created,
            duration,
        )

        logger.info(
            f"Session complete. Duration: {duration:.2f}s, "
            f"Files created: {files_created}"
        )

        # Print the response for interactive sessions
        if session_type in ["visit", "custom"]:
            print("\n" + "=" * 50)
            print("Claude's response:")
            print("=" * 50 + "\n")
            print(journal_content)

    except Exception as e:
        logger.error(f"Session failed: {e}")
        log_session(session_type, 0, 0, 0, time.time() - start_time, str(e))
        raise


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python runner.py morning                # Scheduled morning session")
        print("  python runner.py night                  # Scheduled night session")
        print('  python runner.py visit "message"        # Visit with a message')
        print('  python runner.py custom "full prompt"   # Fully custom prompt')
        print("")
        print("Custom prompt variables:")
        print("  {date}    - Current date (e.g., Wednesday, January 15, 2026)")
        print("  {time}    - Current time (e.g., 09:30 PM)")
        print("  {context} - Previous thought entries")
        print("  {files}   - List of files Claude has created")
        sys.exit(1)

    session_type = sys.argv[1].lower()

    if session_type == "visit":
        if len(sys.argv) >= 3:
            custom_message = " ".join(sys.argv[2:])
        else:
            print("Enter your message (Ctrl+D when done):")
            custom_message = sys.stdin.read().strip()

        if not custom_message:
            print("No message provided.")
            sys.exit(1)

        run_session("visit", custom_message=custom_message)

    elif session_type == "custom":
        if len(sys.argv) >= 3:
            custom_prompt = " ".join(sys.argv[2:])
        else:
            print("Enter your full prompt (Ctrl+D when done):")
            custom_prompt = sys.stdin.read().strip()

        if not custom_prompt:
            print("No prompt provided.")
            sys.exit(1)

        run_session("custom", custom_prompt=custom_prompt)

    elif session_type in ["morning", "night"]:
        run_session(session_type)

    else:
        print("Session type must be 'morning', 'night', 'visit', or 'custom'")
        sys.exit(1)


if __name__ == "__main__":
    main()
