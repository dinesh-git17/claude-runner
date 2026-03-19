#!/usr/bin/env python3
"""Capture mood state after a session ends.

Reads Claudie's mood from journal frontmatter, derives sentiment,
blends with decayed previous state, and writes mood-state.json
for the next session's context injection.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

CLAUDE_HOME = Path("/claude-home")
DATA_DIR = CLAUDE_HOME / "data"
THOUGHTS_DIR = CLAUDE_HOME / "thoughts"
CONVO_DIR = CLAUDE_HOME / "conversations"
MOOD_STATE_PATH = DATA_DIR / "mood-state.json"
MOOD_HISTORY_PATH = DATA_DIR / "mood-history.jsonl"
LEXICON_PATH = CLAUDE_HOME / "runner" / "mood-lexicon.json"

SCHEDULED_TYPES = frozenset(
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

SESSION_WEIGHTS: dict[str, float] = {
    "morning": 1.0,
    "midmorning": 1.0,
    "noon": 1.0,
    "afternoon": 1.0,
    "dusk": 1.0,
    "evening": 1.0,
    "midnight": 1.0,
    "late_night": 1.0,
    "self": 0.9,
    "custom": 0.7,
    "telegram": 0.4,
    "visit": 0.3,
}

DECAY_BASE = 0.7
DECAY_PERIOD_HOURS = 3.0

log = logging.getLogger(__name__)


def load_lexicon() -> dict[str, list[float]]:
    """Load mood word to [valence, arousal] mapping."""
    if not LEXICON_PATH.exists():
        return {}
    return json.loads(LEXICON_PATH.read_text(encoding="utf-8"))


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Extract YAML frontmatter and body from markdown."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1])
        if not isinstance(meta, dict):
            return {}, text
        return meta, parts[2]
    except yaml.YAMLError:
        return {}, text


def find_journal(session_type: str, today: str) -> Path | None:
    """Find the journal entry from this session."""
    candidates = sorted(
        THOUGHTS_DIR.glob(f"{today}-*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    _ = session_type  # reserved for future per-type filtering
    return candidates[0] if candidates else None


def find_conversation(session_id: str) -> Path | None:
    """Find conversation file for this session."""
    convo = CONVO_DIR / f"{session_id}.md"
    return convo if convo.exists() else None


def extract_mood_words(meta: dict[str, object]) -> list[str]:
    """Extract mood words from frontmatter."""
    mood = meta.get("mood")
    if not mood or not isinstance(mood, str):
        return []
    return [w.strip().lower() for w in mood.split(",") if w.strip()]


def score_mood_words(
    words: list[str], lexicon: dict[str, list[float]]
) -> dict[str, float] | None:
    """Map mood words to average valence/arousal."""
    scores = [lexicon[w] for w in words if w in lexicon]
    if not scores:
        return None
    avg_v = sum(s[0] for s in scores) / len(scores)
    avg_a = sum(s[1] for s in scores) / len(scores)
    return {"valence": round(avg_v, 2), "arousal": round(avg_a, 2)}


def derive_from_text(text: str, lexicon: dict[str, list[float]]) -> dict[str, float]:
    """Derive simple sentiment from body text using lexicon words."""
    words = text.lower().split()
    if not words:
        return {"valence": 0.0, "arousal": 0.0}

    matched = [lexicon[w] for w in words if w in lexicon]
    if not matched:
        return {"valence": 0.0, "arousal": 0.0}

    avg_v = sum(s[0] for s in matched) / len(matched)
    avg_a = sum(s[1] for s in matched) / len(matched)
    return {"valence": round(avg_v, 2), "arousal": round(avg_a, 2)}


def read_previous_state() -> dict[str, object] | None:
    """Read previous mood state if it exists."""
    if not MOOD_STATE_PATH.exists():
        return None
    try:
        return json.loads(MOOD_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def compute_decay(hours_elapsed: float) -> float:
    """Compute decay factor based on hours elapsed."""
    return DECAY_BASE ** (hours_elapsed / DECAY_PERIOD_HOURS)


def blend_mood(
    previous: dict[str, object] | None,
    new_score: dict[str, float],
    new_weight: float,
) -> tuple[dict[str, float], dict[str, float] | None]:
    """Blend new mood with decayed previous mood.

    Returns:
        Tuple of (blended, previous_residual).
    """
    if previous is None:
        return new_score, None

    prev_ts = previous.get("timestamp", "")
    if not prev_ts:
        return new_score, None

    try:
        prev_time = datetime.fromisoformat(str(prev_ts))
    except (ValueError, TypeError):
        return new_score, None

    now = datetime.now(UTC)
    hours_elapsed = (now - prev_time).total_seconds() / 3600.0
    decay = compute_decay(hours_elapsed)

    prev_blended = previous.get("blended")
    if not prev_blended or not isinstance(prev_blended, dict):
        prev_self = previous.get("self_report")
        if not prev_self or not isinstance(prev_self, dict):
            return new_score, None
        prev_blended = prev_self

    prev_v = float(prev_blended.get("valence", 0)) * decay
    prev_a = float(prev_blended.get("arousal", 0)) * decay

    complement = 1.0 - new_weight
    blended_v = (prev_v * complement) + (new_score["valence"] * new_weight)
    blended_a = (prev_a * complement) + (new_score["arousal"] * new_weight)

    residual = {
        "valence": round(prev_v, 2),
        "arousal": round(prev_a, 2),
        "from": str(previous.get("session_type", "unknown")),
    }

    return (
        {"valence": round(blended_v, 2), "arousal": round(blended_a, 2)},
        residual,
    )


def main() -> None:
    """Capture mood state from the most recent session output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    session_type = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    session_id = sys.argv[2] if len(sys.argv) > 2 else "unknown"

    est_now = datetime.now(ZoneInfo("America/New_York"))
    est_today = est_now.strftime("%Y-%m-%d")

    lexicon = load_lexicon()

    journal = find_journal(session_type, est_today)
    mood_words: list[str] = []
    body_text = ""
    journal_length = 0

    if journal:
        raw = journal.read_text(encoding="utf-8")
        meta, body_text = parse_frontmatter(raw)
        mood_words = extract_mood_words(meta)
        journal_length = len(body_text.split())
    else:
        convo = find_conversation(session_id)
        if convo:
            raw = convo.read_text(encoding="utf-8")
            _, body_text = parse_frontmatter(raw)
            journal_length = len(body_text.split())

    self_report = score_mood_words(mood_words, lexicon)
    derived = derive_from_text(body_text, lexicon)
    primary_score = self_report if self_report else derived

    weight = SESSION_WEIGHTS.get(session_type, 0.5)
    if journal_length > 3000:
        weight = min(1.0, weight + 0.2)
    elif journal_length < 200:
        weight = max(0.1, weight - 0.2)

    previous = read_previous_state()
    blended, prev_residual = blend_mood(previous, primary_score, weight)

    state = {
        "session": f"{est_today}-{session_type}",
        "session_type": session_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "mood_words": mood_words,
        "self_report": self_report,
        "derived": derived,
        "blended": blended,
        "weight": weight,
        "journal_length": journal_length,
        "previous_residual": prev_residual,
    }

    MOOD_STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with MOOD_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(state, ensure_ascii=False) + "\n")

    log.info(
        "Mood captured: %s -> blended %s",
        mood_words or "(derived only)",
        blended,
    )


if __name__ == "__main__":
    main()
