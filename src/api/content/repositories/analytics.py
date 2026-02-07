"""Analytics aggregation across thoughts, dreams, and session logs."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from api.content.repositories.dreams import get_all_dreams
from api.content.repositories.sessions import get_all_session_logs
from api.content.repositories.thoughts import get_all_thoughts
from api.content.schemas import (
    AnalyticsSummary,
    DailyActivity,
    DreamTypeCount,
    MoodFrequency,
    MoodTimelineEntry,
    SessionLogEntry,
    SessionTrend,
    WeeklyOutput,
)


def _tokenize_mood(mood: str | None) -> list[str]:
    """Split a comma-separated mood string into lowercase tokens.

    Args:
        mood: Raw mood string, e.g. "soft, held, becoming".

    Returns:
        List of trimmed lowercase mood words.
    """
    if not mood:
        return []
    return [w.strip().lower() for w in mood.split(",") if w.strip()]


def _iso_week_start(date_str: str) -> str:
    """Get the Monday of the ISO week for a given date string.

    Args:
        date_str: Date in YYYY-MM-DD format.

    Returns:
        Monday date in YYYY-MM-DD format.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


def compute_analytics() -> AnalyticsSummary:
    """Compute full analytics summary from all data sources.

    Returns:
        AnalyticsSummary with all aggregated metrics.
    """
    thoughts = get_all_thoughts()
    dreams = get_all_dreams()
    sessions = get_all_session_logs()

    # --- Scalar metrics ---
    all_dates: set[str] = set()
    for t in thoughts:
        all_dates.add(t.date)
    for d in dreams:
        all_dates.add(d.date)
    for s in sessions:
        all_dates.add(s.date)

    total_sessions = len(sessions)
    total_duration = sum(s.duration_ms for s in sessions)
    total_turns = sum(s.num_turns for s in sessions)
    total_cost = sum(s.total_cost_usd for s in sessions)
    total_tokens = sum(
        s.input_tokens + s.output_tokens + s.cache_read_tokens + s.cache_creation_tokens
        for s in sessions
    )

    avg_duration = total_duration / total_sessions if total_sessions else 0.0
    avg_turns = total_turns / total_sessions if total_sessions else 0.0
    avg_cost = total_cost / total_sessions if total_sessions else 0.0

    # --- Daily activity ---
    daily: dict[str, dict[str, int]] = defaultdict(
        lambda: {"thoughts": 0, "dreams": 0, "sessions": 0}
    )
    for t in thoughts:
        daily[t.date]["thoughts"] += 1
    for d in dreams:
        daily[d.date]["dreams"] += 1
    for s in sessions:
        daily[s.date]["sessions"] += 1

    daily_activity = sorted(
        [DailyActivity(date=d, **counts) for d, counts in daily.items()],
        key=lambda x: x.date,
    )

    # --- Mood frequencies (top 30) ---
    mood_counter: Counter[str] = Counter()
    mood_by_date: dict[str, list[str]] = defaultdict(list)

    for t in thoughts:
        tokens = _tokenize_mood(t.mood)
        mood_counter.update(tokens)
        if tokens:
            mood_by_date[t.date].extend(tokens)

    mood_frequencies = [
        MoodFrequency(word=word, count=count)
        for word, count in mood_counter.most_common(30)
    ]

    # --- Mood timeline (most recent 60 days) ---
    mood_timeline = sorted(
        [
            MoodTimelineEntry(date=d, moods=list(dict.fromkeys(moods)))
            for d, moods in mood_by_date.items()
        ],
        key=lambda x: x.date,
        reverse=True,
    )[:60]

    # --- Session trends (by date) ---
    sessions_by_date: dict[str, list[SessionLogEntry]] = defaultdict(list)
    for s in sessions:
        sessions_by_date[s.date].append(s)

    session_trends = sorted(
        [
            SessionTrend(
                date=d,
                avg_duration_ms=sum(s.duration_ms for s in sl) / len(sl),
                avg_turns=sum(s.num_turns for s in sl) / len(sl),
                total_tokens=sum(
                    s.input_tokens
                    + s.output_tokens
                    + s.cache_read_tokens
                    + s.cache_creation_tokens
                    for s in sl
                ),
                session_count=len(sl),
            )
            for d, sl in sessions_by_date.items()
        ],
        key=lambda x: x.date,
    )

    # --- Weekly output ---
    weekly: dict[str, dict[str, int]] = defaultdict(
        lambda: {"thoughts": 0, "dreams": 0}
    )
    for t in thoughts:
        wk = _iso_week_start(t.date)
        weekly[wk]["thoughts"] += 1
    for d in dreams:
        wk = _iso_week_start(d.date)
        weekly[wk]["dreams"] += 1

    weekly_output = sorted(
        [WeeklyOutput(week_start=wk, **counts) for wk, counts in weekly.items()],
        key=lambda x: x.week_start,
    )

    # --- Dream type counts ---
    type_counter: Counter[str] = Counter()
    for d in dreams:
        type_counter[d.type.value if hasattr(d.type, "value") else str(d.type)] += 1

    dream_type_counts = [
        DreamTypeCount(type=t, count=c) for t, c in type_counter.most_common()
    ]

    return AnalyticsSummary(
        total_thoughts=len(thoughts),
        total_dreams=len(dreams),
        total_sessions=total_sessions,
        days_active=len(all_dates),
        avg_duration_ms=avg_duration,
        avg_turns=avg_turns,
        avg_cost_usd=avg_cost,
        total_cost_usd=total_cost,
        total_tokens=total_tokens,
        daily_activity=daily_activity,
        mood_frequencies=mood_frequencies,
        mood_timeline=mood_timeline,
        session_trends=session_trends,
        weekly_output=weekly_output,
        dream_type_counts=dream_type_counts,
    )
