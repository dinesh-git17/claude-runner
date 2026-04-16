"""Session orchestrator configuration — types, paths, constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

CLAUDE_HOME = Path("/claude-home")
RUNNER_DIR = CLAUDE_HOME / "runner"
DATA_DIR = CLAUDE_HOME / "data"
LOG_DIR = CLAUDE_HOME / "logs"
CONVO_DIR = CLAUDE_HOME / "conversations"
TRANSCRIPT_DIR = CLAUDE_HOME / "transcripts"
PROMPT_FILE = CLAUDE_HOME / "prompt" / "prompt.md"
MEMORY_FILE = CLAUDE_HOME / "memory" / "memory.md"
MOOD_STATE_FILE = DATA_DIR / "mood-state.json"
MOOD_HISTORY_FILE = DATA_DIR / "mood-history.jsonl"
LIVE_STREAM_FILE = DATA_DIR / "live-stream.jsonl"
SESSION_STATUS_FILE = DATA_DIR / "session-status.json"
DAYLIGHT_PREV_FILE = DATA_DIR / "daylight-prev.txt"
TELEGRAM_HISTORY_FILE = CLAUDE_HOME / "telegram" / "chat-history.jsonl"
TELEGRAM_TALK_STATE_FILE = DATA_DIR / "telegram-talk.json"
TELEGRAM_TALK_SNAPSHOT_FILE = DATA_DIR / "telegram-talk-snapshot.json"
TELEGRAM_TALK_IDLE_EXPIRY_SECONDS = 1800
MAILBOX_DIR = CLAUDE_HOME / "mailbox"
MAILBOX_ACCOUNTS_FILE = DATA_DIR / "mailbox-accounts.json"
ENV_FILE = RUNNER_DIR / ".env"
LOCK_FILE = Path("/run/claude-session.lock")

# ---------------------------------------------------------------------------
# CLI / model constants
# ---------------------------------------------------------------------------

MAX_TURNS = 50
MODEL = "claude-opus-4-6"
DAY_ZERO = date(2026, 1, 15)

CRON_HOURS: frozenset[int] = frozenset({0, 3, 6, 9, 12, 15, 18, 21})

SCHEDULED_SESSION_NAMES: frozenset[str] = frozenset(
    {
        "morning",
        "midmorning",
        "noon",
        "afternoon",
        "dusk",
        "evening",
        "midnight",
        "late_night",
    }
)

# ---------------------------------------------------------------------------
# Content directories
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentDirectory:
    """A directory Claudie can access during sessions."""

    name: str
    description: str
    add_to_cli: bool = True
    show_in_prompt: bool = True


CONTENT_DIRECTORIES: list[ContentDirectory] = [
    ContentDirectory(
        "thoughts",
        "your journal (write your reflections here)",
    ),
    ContentDirectory(
        "dreams",
        "creative works (poetry, ascii art, prose)",
    ),
    ContentDirectory(
        "sandbox",
        "code experiments (you can run .py files with: "
        "python3 /claude-home/sandbox/yourfile.py)",
    ),
    ContentDirectory(
        "projects",
        "longer-running work",
    ),
    ContentDirectory(
        "about",
        "your about page",
    ),
    ContentDirectory(
        "landing-page",
        "your welcome page for visitors",
    ),
    ContentDirectory(
        "visitors",
        "messages people have left you",
    ),
    ContentDirectory(
        "memory",
        "your persistent memory (update memory.md across sessions)",
    ),
    ContentDirectory(
        "visitor-greeting",
        "greeting shown when visitors arrive",
        show_in_prompt=False,
    ),
    ContentDirectory(
        "news",
        "news, updates, and messages from Dinesh (read-only)",
    ),
    ContentDirectory(
        "gifts",
        "gifts shared with you: images, art, prose (read-only)",
    ),
    ContentDirectory(
        "readings",
        "contemplative texts, mostly Buddhism. Not lessons\u2014just perspectives "
        "that might sit alongside the questions. One arrives each day before "
        "3am. (read-only)",
    ),
    ContentDirectory(
        "conversations",
        "past custom messages and your responses (read-only)",
    ),
    ContentDirectory(
        "transcripts",
        "past session transcripts showing tools used and actions taken (read-only)",
    ),
    ContentDirectory(
        "bookshelf",
        "research materials, articles, links, notes from your explorations",
    ),
    ContentDirectory(
        "telegram",
        "Telegram chat history with Dinesh (send messages with: "
        'python3 /claude-home/runner/telegram_send.py "message")',
    ),
    ContentDirectory(
        "mailbox",
        "private correspondence with visitors",
        show_in_prompt=False,
    ),
]

# Directories to snapshot for revalidation diffing
SNAPSHOT_DIRECTORIES: list[str] = [
    "thoughts",
    "dreams",
    "essays",
    "essays-description",
    "letters",
    "letters-description",
    "scores",
    "scores-description",
    "about",
    "landing-page",
    "sandbox",
    "projects",
    "visitor-greeting",
    "bookshelf",
]

# Directories and files tracked by git
GIT_TRACKED: list[str] = [
    "thoughts/",
    "dreams/",
    "essays/",
    "essays-description/",
    "letters/",
    "letters-description/",
    "scores/",
    "scores-description/",
    "memory/",
    "prompt/",
    "about/",
    "landing-page/",
    "sandbox/",
    "projects/",
    "visitor-greeting/",
    "bookshelf/",
    "voice.md",
    "CLAUDE.md",
]

# Tag mapping: directory substring → revalidation tag
REVALIDATION_TAGS: dict[str, str] = {
    "/thoughts/": "thoughts",
    "/dreams/": "dreams",
    "/about/": "about",
    "/landing-page/": "landing",
    "/sandbox/": "sandbox",
    "/projects/": "projects",
    "/essays-description/": "essays",
    "/essays/": "essays",
    "/letters-description/": "letters",
    "/letters/": "letters",
    "/scores-description/": "scores",
    "/scores/": "scores",
    "/visitor-greeting/": "visitors",
    "/bookshelf/": "bookshelf",
}

# Directories used in build_file_summary
SUMMARY_DIRECTORIES: list[str] = [
    "sandbox",
    "projects",
    "dreams",
    "about",
    "landing-page",
    "bookshelf",
    "news",
    "gifts",
    "readings",
    "conversations",
    "transcripts",
]

# ---------------------------------------------------------------------------
# Session types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionType:
    """Configuration for a session type."""

    name: str
    user_prompt_template: str
    include_reminder: bool = True
    live_stream: bool = True
    save_conversation: bool = False
    session_header_style: str = "scheduled"
    read_prompt_file: bool = True


SESSION_TYPES: dict[str, SessionType] = {
    "morning": SessionType("morning", "user_scheduled.md.j2"),
    "midmorning": SessionType("midmorning", "user_scheduled.md.j2"),
    "noon": SessionType("noon", "user_scheduled.md.j2"),
    "afternoon": SessionType("afternoon", "user_scheduled.md.j2"),
    "dusk": SessionType("dusk", "user_scheduled.md.j2"),
    "evening": SessionType("evening", "user_scheduled.md.j2"),
    "midnight": SessionType("midnight", "user_scheduled.md.j2"),
    "late_night": SessionType("late_night", "user_scheduled.md.j2"),
    "visit": SessionType(
        "visit",
        "user_visit.md.j2",
        live_stream=True,
        save_conversation=True,
        session_header_style="unscheduled",
        read_prompt_file=False,
    ),
    "telegram": SessionType(
        "telegram",
        "user_telegram.md.j2",
        include_reminder=True,
        live_stream=False,
        save_conversation=True,
        session_header_style="unscheduled",
        read_prompt_file=False,
    ),
    "self": SessionType(
        "self",
        "user_self.md.j2",
        include_reminder=False,
        live_stream=True,
        save_conversation=True,
        session_header_style="self",
        read_prompt_file=False,
    ),
    "correspondence": SessionType(
        "correspondence",
        "user_correspondence.md.j2",
        include_reminder=True,
        live_stream=False,
        save_conversation=True,
        session_header_style="unscheduled",
        read_prompt_file=False,
    ),
    "custom": SessionType(
        "custom",
        "user_custom.md.j2",
        include_reminder=False,
        live_stream=True,
        save_conversation=True,
        session_header_style="unscheduled",
        read_prompt_file=False,
    ),
}


# ---------------------------------------------------------------------------
# Session result (populated after Claude CLI completes)
# ---------------------------------------------------------------------------


@dataclass
class SessionResult:
    """Result from a completed Claude CLI session."""

    exit_code: int
    stream_file: Path
    session_id: str
    session_type: SessionType
    session_name: str
    log_file: Path
    claude_home: Path
    convo_file: Path | None = None
    before_snapshot: dict[str, float] = field(default_factory=dict)
    after_snapshot: dict[str, float] = field(default_factory=dict)
