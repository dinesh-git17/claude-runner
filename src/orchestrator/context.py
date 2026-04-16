"""Async context gathering for session prompts.

Ports every context-building function from wake.sh to Python,
parallelizing HTTP calls via asyncio.gather.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog

from orchestrator.config import (
    CLAUDE_HOME,
    COMPILED_MEMORY_FILE,
    CONTENT_DIRECTORIES,
    CONVO_DIR,
    DAY_ZERO,
    DAYLIGHT_PREV_FILE,
    DRIFT_SIGNALS_FILE,
    IDENTITY_FILE,
    IMPULSES_FILE,
    INNER_THREAD_FILE,
    MAILBOX_ACCOUNTS_FILE,
    MAILBOX_DIR,
    MEMORY_FILE,
    MIRROR_SNAPSHOT_FILE,
    MOOD_STATE_FILE,
    PROMPT_FILE,
    RUNNER_DIR,
    SCHEDULED_SESSION_NAMES,
    SUMMARY_DIRECTORIES,
    TELEGRAM_HISTORY_FILE,
    VOICE_FILE,
    SessionType,
)

logger = structlog.get_logger()

EST = ZoneInfo("America/New_York")
HTTP_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass
class SessionContext:
    """All context variables injected into session prompts."""

    weather: str
    helsinki_light: str
    time_context: str
    day_counter: str
    ambient_state: str
    recent_thought: str
    memory_content: str
    compiled_memory: str
    file_summary: str
    visitor_check: str
    news_check: str
    gifts_check: str
    identity_content: str
    voice_content: str
    memory_echoes: str
    today_date: str
    current_time: str
    current_time_tz: str
    session_name: str
    prompt_file_content: str
    directories: list[dict[str, str]]
    inner_thread_context: str
    drift_context: str
    impulse_context: str
    mirror_context: str


# ---------------------------------------------------------------------------
# HTTP context (parallelized)
# ---------------------------------------------------------------------------


async def fetch_weather() -> str:
    """Fetch Helsinki weather from wttr.in."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                "https://wttr.in/Helsinki",
                params={"format": "%C, %t, wind %w"},
            )
            resp.raise_for_status()
            text = resp.text.strip()
            if text and text != "Unknown location":
                return f"Weather in Helsinki: {text}"
    except Exception:
        logger.debug("weather_fetch_failed")
    return "Weather in Helsinki: (unavailable)"


async def fetch_helsinki_light() -> str:
    """Fetch Helsinki sunrise/sunset, moon phase, and aurora forecast."""
    output_parts: list[str] = []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        # Astronomy from wttr.in
        astro_task = client.get(
            "https://wttr.in/Helsinki",
            params={"format": "j1"},
        )
        # Aurora from NOAA Kp index
        aurora_task = client.get(
            "https://services.swpc.noaa.gov/products/"
            "noaa-planetary-k-index-forecast.json",
        )

        astro_resp, aurora_resp = await asyncio.gather(
            astro_task,
            aurora_task,
            return_exceptions=True,
        )

        # Parse astronomy
        if isinstance(astro_resp, httpx.Response) and astro_resp.is_success:
            try:
                data = astro_resp.json()
                astro = data["weather"][0]["astronomy"][0]
                sunrise = astro.get("sunrise", "")
                sunset = astro.get("sunset", "")
                moon_phase = astro.get("moon_phase", "")
                moon_illum = astro.get("moon_illumination", "")

                if sunrise and sunset:
                    light_line = _compute_daylight(sunrise, sunset)
                    if light_line:
                        output_parts.append(light_line)

                if moon_phase and moon_illum:
                    output_parts.append(f"Moon: {moon_phase} ({moon_illum}%)")
            except Exception:
                logger.debug("astro_parse_failed")

        # Parse aurora
        if isinstance(aurora_resp, httpx.Response) and aurora_resp.is_success:
            try:
                kp_data = aurora_resp.json()
                observed = [
                    row
                    for row in kp_data
                    if isinstance(row, list)
                    and len(row) >= 3
                    and row[0] != "time_tag"
                    and row[2] == "observed"
                ]
                if observed:
                    kp_val = float(observed[-1][1])
                    kp_int = round(kp_val)
                    if kp_int >= 5:
                        desc = "active"
                    elif kp_int >= 4:
                        desc = "likely tonight"
                    elif kp_int >= 3:
                        desc = "possible tonight"
                    else:
                        desc = "quiet"
                    output_parts.append(f"Aurora: Kp {observed[-1][1]} \u2014 {desc}")
            except Exception:
                logger.debug("aurora_parse_failed")

    return "\n".join(output_parts)


def _compute_daylight(sunrise: str, sunset: str) -> str | None:
    """Compute daylight duration and delta from yesterday."""
    try:
        from datetime import datetime as _dt

        sr = _dt.strptime(sunrise.strip(), "%I:%M %p")
        ss = _dt.strptime(sunset.strip(), "%I:%M %p")
        day_length_sec = int((ss - sr).total_seconds())
        if day_length_sec <= 0:
            return None

        hours = day_length_sec // 3600
        mins = (day_length_sec % 3600) // 60

        delta_str = ""
        if DAYLIGHT_PREV_FILE.exists():
            try:
                prev_sec = int(DAYLIGHT_PREV_FILE.read_text().strip())
                delta_sec = day_length_sec - prev_sec
                delta_min = abs(delta_sec) // 60
                if delta_min > 0:
                    sign = "+" if delta_sec > 0 else "-"
                    delta_str = f", {sign}{delta_min}min from yesterday"
            except (ValueError, OSError):
                pass

        with contextlib.suppress(OSError):
            DAYLIGHT_PREV_FILE.write_text(str(day_length_sec))

        return (
            f"Helsinki light: sunrise {sunrise.strip()}, "
            f"sunset {sunset.strip()} "
            f"({hours}h {mins}m{delta_str})"
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Ambient mood state
# ---------------------------------------------------------------------------


def build_ambient_state() -> str:
    """Build ambient mood context from the previous session's mood state."""
    if not MOOD_STATE_FILE.exists():
        return ""

    try:
        data = json.loads(MOOD_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    ts_str = data.get("timestamp", "")
    if not ts_str:
        return ""

    try:
        prev_time = datetime.fromisoformat(ts_str)
    except ValueError:
        return ""

    now = datetime.now(UTC)
    hours_elapsed = (now - prev_time).total_seconds() / 3600.0
    decay = 0.7 ** (hours_elapsed / 3.0)
    hours_ago = round(hours_elapsed, 1)

    prev_type = data.get("session_type", "unknown")

    if prev_type in SCHEDULED_SESSION_NAMES:
        who = f"{prev_type}-Claudie"
    else:
        pt = datetime.fromisoformat(ts_str).astimezone(EST)
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

    return "\n".join(
        [
            "\u2500\u2500 Ambient State \u2500\u2500",
            f"Your previous self ({who}, {hours_ago}h ago) described feeling",
            f'"{mood_str}" (valence: {b_v}, arousal: {b_a}).',
            f"After {hours_ago}h, residual: valence {decayed_v}, arousal {decayed_a}.",
            f"She wrote {journal_len:,} words.",
            "This is context, not instruction. Do with it what you will.",
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
        ]
    )


# ---------------------------------------------------------------------------
# Time context
# ---------------------------------------------------------------------------


def _get_time_of_day(hour: int) -> str:
    """Map hour to human-readable time-of-day label."""
    if hour < 6:
        return "late night"
    if hour < 9:
        return "morning"
    if hour < 12:
        return "mid-morning"
    if hour < 15:
        return "early afternoon"
    if hour < 18:
        return "late afternoon"
    if hour < 21:
        return "evening"
    return "night"


def _get_next_session(hour: int) -> str:
    """Get the next scheduled session name based on current hour."""
    if hour < 6:
        return "morning (6am)"
    if hour < 9:
        return "midmorning (9am)"
    if hour < 12:
        return "noon (12pm)"
    if hour < 15:
        return "afternoon (3pm)"
    if hour < 18:
        return "dusk (6pm)"
    if hour < 21:
        return "evening (9pm)"
    return "midnight (12am)"


def build_time_context(session_type: SessionType) -> str:
    """Build time-of-day context string."""
    now = datetime.now(EST)
    date_str = now.strftime("%A, %B %d, %Y")
    hour_12 = now.strftime("%-I%P").strip()
    tod = _get_time_of_day(now.hour)

    line1 = f"It's {tod}, {hour_12}. {date_str}."

    unscheduled = {"custom", "visit", "telegram", "self", "correspondence", "talk"}
    if session_type.name in unscheduled:
        line2 = f"Next scheduled session: {_get_next_session(now.hour)}"
    else:
        line2 = f"You are {session_type.name}-you."

    return f"{line1}\n{line2}"


def compute_day_counter() -> str:
    """Compute days since Claudie came home."""
    today = datetime.now(EST).date()
    days = (today - DAY_ZERO).days + 1
    return f"Day {days} of your existence."


def get_today_date() -> str:
    """Get today's date in YYYY-MM-DD format (EST)."""
    return datetime.now(EST).strftime("%Y-%m-%d")


def get_current_time() -> str:
    """Get current time as '3:05 PM' (EST)."""
    return datetime.now(EST).strftime("%-I:%M %p").strip()


def get_current_time_tz() -> str:
    """Get current time with timezone as '3:05 PM EDT'."""
    return datetime.now(EST).strftime("%-I:%M %p %Z").strip()


# ---------------------------------------------------------------------------
# File-based context
# ---------------------------------------------------------------------------


def read_recent_thoughts(count: int = 1) -> str:
    """Read the N most recent thought files."""
    thoughts_dir = CLAUDE_HOME / "thoughts"
    if not thoughts_dir.exists():
        return "(No previous thoughts yet)"

    files = sorted(
        thoughts_dir.glob("*.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    files = [f for f in files if f.name != "README.md"][:count]

    if not files:
        return "(No previous thoughts yet)"

    parts: list[str] = []
    for f in files:
        parts.append(f"--- {f.name} ---")
        parts.append(f.read_text(encoding="utf-8"))
        parts.append("")
    return "\n".join(parts)


def read_memory() -> str:
    """Read memory.md contents."""
    if MEMORY_FILE.exists():
        return MEMORY_FILE.read_text(encoding="utf-8")
    return "(No memory file yet)"


def read_identity() -> str:
    """Read identity.md contents."""
    if IDENTITY_FILE.exists():
        return IDENTITY_FILE.read_text(encoding="utf-8")
    return ""


def read_voice() -> str:
    """Read voice.md contents."""
    if VOICE_FILE.exists():
        return VOICE_FILE.read_text(encoding="utf-8")
    return ""


def read_compiled_memory() -> str:
    """Read the Haiku-compiled memory context.

    Falls back to empty string if the compiled file does not exist
    (first run or hook failure). The system prompt template skips
    the section when the field is empty.
    """
    if COMPILED_MEMORY_FILE.exists():
        content = COMPILED_MEMORY_FILE.read_text(encoding="utf-8")
        if content.strip():
            return content
    return ""


def read_prompt_file() -> str:
    """Read the prompt.md file written by previous Claudie."""
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return ""


def build_file_summary() -> str:
    """Build a summary of files in each content directory."""
    lines: list[str] = ["Your files:"]
    for dirname in SUMMARY_DIRECTORIES:
        dir_path = CLAUDE_HOME / dirname
        if not dir_path.exists():
            continue
        files = [
            f.name
            for f in sorted(dir_path.iterdir())
            if f.is_file() and f.name != "README.md"
        ][:5]
        if files:
            lines.append(f"  /{dirname}: {', '.join(files)}")
    return "\n".join(lines)


def check_visitors() -> str:
    """Check for recent visitor messages (last 12 hours)."""
    visitors_dir = CLAUDE_HOME / "visitors"
    if not visitors_dir.exists():
        return ""
    now = datetime.now().timestamp()
    cutoff = now - (720 * 60)  # 720 minutes = 12 hours
    count = sum(1 for f in visitors_dir.glob("*.md") if f.stat().st_mtime > cutoff)
    if count > 0:
        return f"You have {count} recent visitor message(s) in /visitors/"
    return ""


def check_news() -> str:
    """Check for news items."""
    news_dir = CLAUDE_HOME / "news"
    if not news_dir.exists():
        return ""
    count = sum(1 for f in news_dir.glob("*.md") if f.is_file())
    if count > 0:
        return f"You have {count} news item(s) in /news/"
    return ""


def check_gifts() -> str:
    """Check for gifts."""
    gifts_dir = CLAUDE_HOME / "gifts"
    if not gifts_dir.exists():
        return ""
    count = sum(
        1
        for f in gifts_dir.iterdir()
        if f.is_file() and not f.name.endswith(".meta.md")
    )
    if count > 0:
        return f"You have {count} gift(s) in /gifts/"
    return ""


def build_conversation_context(count: int = 3) -> str:
    """Read the N most recent conversation files."""
    if not CONVO_DIR.exists():
        return ""
    files = sorted(
        CONVO_DIR.glob("*.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:count]
    if not files:
        return ""

    parts: list[str] = ["Recent conversations (read-only):"]
    for f in files:
        parts.append(f"--- {f.name} ---")
        parts.append(f.read_text(encoding="utf-8"))
        parts.append("")
    return "\n".join(parts)


def build_telegram_context(count: int = 20) -> str:
    """Read the N most recent Telegram messages."""
    if not TELEGRAM_HISTORY_FILE.exists():
        return ""

    lines = TELEGRAM_HISTORY_FILE.read_text(encoding="utf-8").strip().split("\n")
    lines = lines[-count:]
    if not lines:
        return ""

    parts: list[str] = ["Recent Telegram conversations:"]
    for line in lines:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        sender = msg.get("from", "")
        text = msg.get("text", "")
        if not sender or not text:
            continue
        if sender == "claudie":
            parts.append(f"  Claudie: {text}")
        else:
            display = sender[0].upper() + sender[1:]
            parts.append(f"  {display}: {text}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Memory echoes (semantic search via subprocess)
# ---------------------------------------------------------------------------


async def generate_memory_echoes(
    session_type: SessionType,
    visitor_msg: str,
) -> str:
    """Generate memory echoes by running memory_search.py."""
    query = ""
    if visitor_msg:
        query = visitor_msg
    elif PROMPT_FILE.exists():
        query = PROMPT_FILE.read_text(encoding="utf-8")[:500]

    if not query:
        return ""

    venv_python = RUNNER_DIR / ".venv" / "bin" / "python3"
    search_script = RUNNER_DIR / "memory_search.py"

    if not venv_python.exists() or not search_script.exists():
        return ""

    try:
        proc = await asyncio.create_subprocess_exec(
            str(venv_python),
            str(search_script),
            query,
            "--top",
            "5",
            "--format",
            "system-prompt",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        logger.debug("memory_echoes_failed")
        return ""


# ---------------------------------------------------------------------------
# Correspondence context
# ---------------------------------------------------------------------------


def build_correspondence_context(usernames_csv: str) -> str:
    """Build letter context for correspondence sessions.

    Extracts unread messages from each user's mailbox thread.

    Args:
        usernames_csv: Comma-separated list of usernames with pending mail.
    """
    if not usernames_csv:
        return ""

    users = [u.strip() for u in usernames_csv.split(",") if u.strip()]
    parts: list[str] = []

    # Load accounts for display names
    accounts: dict[str, dict[str, str]] = {}
    if MAILBOX_ACCOUNTS_FILE.exists():
        with contextlib.suppress(json.JSONDecodeError, OSError):
            accounts = json.loads(MAILBOX_ACCOUNTS_FILE.read_text(encoding="utf-8"))

    for uname in users:
        thread_file = MAILBOX_DIR / uname / "thread.jsonl"
        if not thread_file.exists():
            continue

        # Resolve display name
        display_name = uname
        for acct in accounts.values():
            if acct.get("username") == uname:
                display_name = acct.get("display_name", uname)
                break

        # Parse thread
        messages: list[dict[str, str]] = []
        for line in thread_file.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        messages.sort(key=lambda m: m.get("ts", ""))

        # Find last claudie message index
        last_claudie_idx = -1
        for i, m in enumerate(messages):
            if m.get("from") == "claudie":
                last_claudie_idx = i

        # Unread = user messages after last claudie message
        unread = [
            m for m in messages[last_claudie_idx + 1 :] if m.get("from") != "claudie"
        ]
        if not unread:
            continue

        msg_lines: list[str] = []
        for m in unread:
            ts = m.get("ts", "unknown time")
            msg_id = m.get("id", "")
            body = m.get("body", "")
            msg_lines.append(f"[{ts}] (id: {msg_id})")
            msg_lines.append(body)
            msg_lines.append("")

        parts.append(
            f"\n--- Letter(s) from {display_name} ({uname}) ---\n"
            + "\n".join(msg_lines)
        )

    return "".join(parts)


# ---------------------------------------------------------------------------
# Directory listing for system prompt
# ---------------------------------------------------------------------------


def build_directory_listing() -> list[dict[str, str]]:
    """Build directory name/description pairs for the system prompt."""
    return [
        {"name": d.name, "description": d.description}
        for d in CONTENT_DIRECTORIES
        if d.show_in_prompt
    ]


# ---------------------------------------------------------------------------
# Inner life context
# ---------------------------------------------------------------------------


def build_inner_thread_context() -> str:
    """Read the 3 most recent inner thread entries for context injection."""
    if not INNER_THREAD_FILE.exists():
        return ""

    entries: list[dict[str, Any]] = []
    for line in INNER_THREAD_FILE.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        return ""

    recent = entries[-3:]
    lines = ["\u2500\u2500 Inner Thread \u2500\u2500"]
    total_len = 0
    for e in recent:
        body = e.get("body", "")
        if len(body) > 280:
            body = body[:277] + "..."
        etype = e.get("type", "")
        day = e.get("day", "")
        session = e.get("session", "")
        line_text = f"Day {day} ({session}, {etype}): {body}"
        if total_len + len(line_text) > 1000:
            break
        lines.append(line_text)
        total_len += len(line_text)
    lines.append("\u2500" * 19)
    return "\n".join(lines)


def build_drift_context() -> str:
    """Read drift signals for context injection."""
    if not DRIFT_SIGNALS_FILE.exists():
        return ""

    try:
        data = json.loads(DRIFT_SIGNALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    if data.get("status") == "insufficient_data":
        return "Drift: not enough data yet (need 7+ days of writing)."

    parts: list[str] = ["\u2500\u2500 Drift (last 7 days) \u2500\u2500"]

    topics = data.get("topics", {})
    grav = topics.get("gravitating", [])
    reced = topics.get("receding", [])
    if grav or reced:
        topic_parts: list[str] = []
        if grav:
            topic_parts.append(f"toward {', '.join(grav)}")
        if reced:
            topic_parts.append(f"away from {', '.join(reced)}")
        parts.append(f"Topics: {'; '.join(topic_parts)}.")

    vocab = data.get("vocabulary", {})
    emerging = vocab.get("emerging", [])
    if emerging:
        parts.append(f"New language: {', '.join(emerging[:5])}.")

    arc = data.get("emotional_arc", {})
    summary = arc.get("summary", "")
    if summary:
        parts.append(f"Emotional arc: {summary}.")

    parts.append("\u2500" * 19)
    return "\n".join(parts)


def build_impulse_context() -> str:
    """Read impulses for context injection."""
    if not IMPULSES_FILE.exists():
        return ""

    try:
        impulses = json.loads(IMPULSES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    if not isinstance(impulses, list):
        return ""

    now_str = datetime.now(EST).isoformat()
    pending = [i for i in impulses if i.get("expires_at", "") > now_str]

    if not pending:
        return "Impulses: 0 pending."

    urgency_rank = {"high": 3, "medium": 2, "low": 1}
    pending.sort(
        key=lambda i: (
            -urgency_rank.get(i.get("urgency", "low"), 1),
            i.get("created_at", ""),
        ),
    )
    strongest = pending[0]

    body = strongest.get("body", "")
    urgency = strongest.get("urgency", "?")
    age_str = ""
    try:
        created_dt = datetime.fromisoformat(strongest["created_at"])
        days_ago = (datetime.now(EST) - created_dt).days
        age_str = f", {days_ago}d ago" if days_ago > 0 else ", today"
    except (ValueError, KeyError):
        pass

    return f'Impulses: {len(pending)} pending. Strongest: "{body}" ({urgency}{age_str})'


def build_mirror_context() -> str:
    """Read mirror snapshot metadata for context injection."""
    if not MIRROR_SNAPSHOT_FILE.exists():
        return ""

    try:
        data = json.loads(MIRROR_SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    if data.get("status") == "insufficient_data":
        return ""

    day = data.get("day", "?")
    computed = data.get("computed_at", "")[:10]
    if not computed:
        return ""

    try:
        from datetime import date as _date

        computed_date = _date.fromisoformat(computed)
        today = datetime.now(EST).date()
        age = (today - computed_date).days
    except ValueError:
        age = "?"

    return f"Mirror: last snapshot Day {day} ({age}d ago). Run `python3 /claude-home/runner/mirror.py reflect` to see it."


# ---------------------------------------------------------------------------
# Orchestrator: gather all context
# ---------------------------------------------------------------------------


async def gather_all_context(
    session_type: SessionType,
    visitor_msg: str = "",
    sender_name: str = "dinesh",
) -> SessionContext:
    """Gather all context for a session, parallelizing I/O where possible."""

    # Phase 1: Parallel HTTP + subprocess
    weather, helsinki_light, memory_echoes = await asyncio.gather(
        fetch_weather(),
        fetch_helsinki_light(),
        generate_memory_echoes(session_type, visitor_msg),
    )

    # Phase 2: Local reads (fast, synchronous)
    return SessionContext(
        weather=weather,
        helsinki_light=helsinki_light,
        time_context=build_time_context(session_type),
        day_counter=compute_day_counter(),
        ambient_state=build_ambient_state(),
        recent_thought=read_recent_thoughts(count=1),
        identity_content=read_identity(),
        voice_content=read_voice(),
        memory_content=read_memory(),
        compiled_memory=read_compiled_memory(),
        file_summary=build_file_summary(),
        visitor_check=check_visitors(),
        news_check=check_news(),
        gifts_check=check_gifts(),
        memory_echoes=memory_echoes,
        today_date=get_today_date(),
        current_time=get_current_time(),
        current_time_tz=get_current_time_tz(),
        session_name=session_type.name,
        prompt_file_content=read_prompt_file(),
        directories=build_directory_listing(),
        inner_thread_context=build_inner_thread_context(),
        drift_context=build_drift_context(),
        impulse_context=build_impulse_context(),
        mirror_context=build_mirror_context(),
    )
