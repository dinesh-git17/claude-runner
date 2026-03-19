#!/usr/bin/env python3
"""Search the web using Brave Search API.

Standalone CLI using only stdlib so it works with system Python
(no venv activation needed).

Usage:
    python3 /claude-home/runner/web_search.py "your search query"
    python3 /claude-home/runner/web_search.py --count 5 "your query"
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ENV_FILE = Path("/claude-home/runner/.env")
LOG_FILE = Path("/claude-home/logs/web.log")
RATE_STATE_FILE = Path("/claude-home/data/web-search-count.json")

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_SEARCHES_PER_SESSION = 20
DEFAULT_RESULT_COUNT = 8
REQUEST_TIMEOUT = 10


def load_env(env_path: Path) -> dict[str, str]:
    """Parse key=value pairs from a .env file.

    Args:
        env_path: Path to the .env file.

    Returns:
        Dictionary of environment variable names to values.
    """
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")

    return values


def log_activity(query: str, success: bool, error: str = "") -> None:
    """Append a JSON line to the web activity log.

    Args:
        query: The search query.
        success: Whether the search succeeded.
        error: Error message if the search failed.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "tool": "search",
        "query": query,
        "success": success,
    }
    if error:
        entry["error"] = error

    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        sys.stderr.write(f"Log write failed: {exc}\n")


def check_rate_limit() -> bool:
    """Check and increment the per-session search counter.

    Uses the parent PID to detect session boundaries. A new parent PID
    resets the counter.

    Returns:
        True if the search is allowed.
    """
    import os

    ppid = os.getppid()
    count = 0

    if RATE_STATE_FILE.exists():
        try:
            state = json.loads(RATE_STATE_FILE.read_text(encoding="utf-8"))
            if state.get("session_pid") == ppid:
                count = state.get("count", 0)
        except (json.JSONDecodeError, OSError):
            pass

    if count >= MAX_SEARCHES_PER_SESSION:
        return False

    RATE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_state = {"session_pid": ppid, "count": count + 1}
    try:
        RATE_STATE_FILE.write_text(json.dumps(new_state), encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"Rate state write failed: {exc}\n")

    return True


def search(
    query: str, api_key: str, count: int = DEFAULT_RESULT_COUNT
) -> list[dict[str, str]]:
    """Execute a web search via Brave Search API.

    Args:
        query: The search query string.
        api_key: Brave Search API subscription token.
        count: Number of results to return.

    Returns:
        List of result dicts with keys: title, url, description.
    """
    params = urllib.parse.urlencode({"q": query, "count": count})
    url = f"{BRAVE_SEARCH_URL}?{params}"

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        },
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip

            raw = gzip.decompress(raw)
        data = json.loads(raw.decode("utf-8"))

    results: list[dict[str, str]] = []
    for item in data.get("web", {}).get("results", []):
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            }
        )

    return results


def format_results(results: list[dict[str, str]], query: str) -> str:
    """Format search results for terminal readability.

    Args:
        results: List of result dicts from search().
        query: The original search query.

    Returns:
        Formatted string for stdout.
    """
    lines: list[str] = []
    lines.append(f'Search: "{query}"')
    lines.append("=" * 60)
    lines.append("")

    if not results:
        lines.append(f"No results found for: {query}")
        return "\n".join(lines) + "\n"

    for i, result in enumerate(results, 1):
        lines.append(f"{i}. {result['title']}")
        lines.append(f"   {result['url']}")
        if result["description"]:
            lines.append(f"   {result['description']}")
        lines.append("")

    return "\n".join(lines)


def parse_args(argv: list[str]) -> tuple[str, int]:
    """Parse command-line arguments.

    Args:
        argv: sys.argv[1:] arguments.

    Returns:
        Tuple of (query, count).
    """
    count = DEFAULT_RESULT_COUNT
    args = list(argv)

    if "--count" in args:
        idx = args.index("--count")
        if idx + 1 < len(args):
            try:
                count = int(args[idx + 1])
            except ValueError:
                msg = f"Invalid count: {args[idx + 1]}\n"
                sys.stderr.write(msg)
                sys.exit(1)
            args = args[:idx] + args[idx + 2 :]
        else:
            sys.stderr.write("--count requires a value\n")
            sys.exit(1)

    query = " ".join(args)
    if not query:
        sys.stderr.write("Usage: web_search.py [--count N] <query>\n")
        sys.exit(1)

    return query, count


def main() -> None:
    """Entry point: parse args, search, format and output results."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: web_search.py [--count N] <query>\n")
        sys.exit(1)

    query, count = parse_args(sys.argv[1:])

    env = load_env(ENV_FILE)
    api_key = env.get("BRAVE_SEARCH_API_KEY", "")

    if not api_key:
        sys.stderr.write("BRAVE_SEARCH_API_KEY not set in .env\n")
        sys.exit(1)

    if not check_rate_limit():
        sys.stderr.write(
            f"Rate limit reached: {MAX_SEARCHES_PER_SESSION} searches per session\n"
        )
        log_activity(query, success=False, error="rate_limit")
        sys.exit(1)

    try:
        results = search(query, api_key, count)
    except urllib.error.HTTPError as exc:
        err = f"Search API error: HTTP {exc.code}\n"
        sys.stderr.write(err)
        log_activity(query, success=False, error=f"http_{exc.code}")
        sys.exit(1)
    except urllib.error.URLError as exc:
        err = f"Search failed: {exc.reason}\n"
        sys.stderr.write(err)
        log_activity(query, success=False, error=str(exc.reason))
        sys.exit(1)
    except TimeoutError:
        sys.stderr.write("Search timed out\n")
        log_activity(query, success=False, error="timeout")
        sys.exit(1)

    log_activity(query, success=True)
    sys.stdout.write(format_results(results, query))


if __name__ == "__main__":
    main()
