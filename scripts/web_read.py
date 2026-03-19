#!/usr/bin/env python3
"""Fetch and extract readable text from a web page.

Uses trafilatura for content extraction when available,
with a stdlib-only fallback.

Usage:
    python3 /claude-home/runner/web_read.py "https://example.com/article"
    python3 /claude-home/runner/web_read.py --max-chars 30000 "https://example.com/article"
"""

from __future__ import annotations

import html.parser
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from socket import getaddrinfo

ENV_FILE = Path("/claude-home/runner/.env")
LOG_FILE = Path("/claude-home/logs/web.log")

DEFAULT_MAX_CHARS = 15_000
ABSOLUTE_MAX_CHARS = 50_000
REQUEST_TIMEOUT = 15
USER_AGENT = "Claudie/1.0 (+https://claudehome.dineshd.dev)"
ALLOWED_SCHEMES = frozenset({"https"})


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


def log_activity(url: str, success: bool, error: str = "") -> None:
    """Append a JSON line to the web activity log.

    Args:
        url: The fetched URL.
        success: Whether the fetch succeeded.
        error: Error message if the fetch failed.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "tool": "read",
        "url": url,
        "success": success,
    }
    if error:
        entry["error"] = error

    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        sys.stderr.write(f"Log write failed: {exc}\n")


def validate_url(url: str) -> str:
    """Validate a URL for safety.

    Rejects non-HTTPS schemes and URLs resolving to private IP ranges.

    Args:
        url: The URL to validate.

    Returns:
        The validated URL string.

    Raises:
        ValueError: If the URL is invalid or unsafe.
    """
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        msg = f"Only HTTPS URLs are allowed, got: {parsed.scheme}"
        raise ValueError(msg)

    if not parsed.hostname:
        msg = "URL has no hostname"
        raise ValueError(msg)

    hostname = parsed.hostname

    try:
        addr = ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            msg = f"Private/loopback addresses are blocked: {hostname}"
            raise ValueError(msg)
    except ValueError as exc:
        if "Private" in str(exc) or "loopback" in str(exc):
            raise
        # Not an IP literal — it's a hostname, resolve it
        try:
            resolved = getaddrinfo(hostname, None)
            for entry in resolved:
                addr = ip_address(entry[4][0])
                if addr.is_private or addr.is_loopback or addr.is_link_local:
                    msg = f"URL resolves to private address: {hostname} -> {addr}"
                    raise ValueError(msg)
        except OSError as dns_exc:
            msg = f"DNS resolution failed for {hostname}: {dns_exc}"
            raise ValueError(msg) from dns_exc

    return url


def fetch_page(url: str) -> str:
    """Fetch a web page via HTTPS GET.

    Args:
        url: The validated URL to fetch.

    Returns:
        The page HTML as a string.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )

    ctx = ssl.create_default_context()

    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
        content_type = resp.headers.get("Content-Type", "")
        encoding = "utf-8"
        if "charset=" in content_type:
            encoding = content_type.split("charset=")[-1].split(";")[0].strip()

        raw: bytes = resp.read()
        decoded: str = raw.decode(encoding, errors="replace")
        return decoded


class _TextExtractor(html.parser.HTMLParser):
    """Minimal HTML-to-text extractor using stdlib only."""

    SKIP_TAGS = frozenset(
        {
            "script",
            "style",
            "nav",
            "header",
            "footer",
            "noscript",
            "svg",
            "iframe",
            "form",
        }
    )

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:  # noqa: ARG002
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        """Return extracted text with collapsed whitespace."""
        text = "".join(self._chunks)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def extract_text(html_content: str, url: str) -> str:
    """Extract readable text from HTML.

    Tries trafilatura first, falls back to stdlib HTML parser.

    Args:
        html_content: Raw HTML string.
        url: The source URL (used by trafilatura for context).

    Returns:
        Extracted plain text.
    """
    try:
        import trafilatura  # type: ignore[import-not-found]

        result: str | None = trafilatura.extract(
            html_content,
            url=url,
            include_links=True,
            include_tables=True,
        )
        if result:
            return result
    except ImportError:
        pass

    extractor = _TextExtractor()
    extractor.feed(html_content)
    return extractor.get_text()


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text at a paragraph boundary.

    Args:
        text: The full text to truncate.
        max_chars: Maximum character count.

    Returns:
        Truncated text with a notice if truncation occurred.
    """
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    last_break = truncated.rfind("\n\n")
    if last_break > max_chars // 2:
        truncated = truncated[:last_break]

    return (
        truncated
        + f"\n\n[Truncated at {len(truncated)} characters. Use --max-chars to read more.]"
    )


def parse_args(argv: list[str]) -> tuple[str, int]:
    """Parse command-line arguments.

    Args:
        argv: sys.argv[1:] arguments.

    Returns:
        Tuple of (url, max_chars).
    """
    max_chars = DEFAULT_MAX_CHARS
    args = list(argv)

    if "--max-chars" in args:
        idx = args.index("--max-chars")
        if idx + 1 < len(args):
            try:
                max_chars = min(int(args[idx + 1]), ABSOLUTE_MAX_CHARS)
            except ValueError:
                msg = f"Invalid max-chars: {args[idx + 1]}\n"
                sys.stderr.write(msg)
                sys.exit(1)
            args = args[:idx] + args[idx + 2 :]
        else:
            sys.stderr.write("--max-chars requires a value\n")
            sys.exit(1)

    if not args:
        sys.stderr.write("Usage: web_read.py [--max-chars N] <url>\n")
        sys.exit(1)

    return args[0], max_chars


def main() -> None:
    """Entry point: parse args, fetch page, extract text, output."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: web_read.py [--max-chars N] <url>\n")
        sys.exit(1)

    url, max_chars = parse_args(sys.argv[1:])

    try:
        validated_url = validate_url(url)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        log_activity(url, success=False, error=str(exc))
        sys.exit(1)

    try:
        html_content = fetch_page(validated_url)
    except urllib.error.HTTPError as exc:
        err = f"HTTP {exc.code}: {url}\n"
        sys.stderr.write(err)
        log_activity(url, success=False, error=f"http_{exc.code}")
        sys.exit(1)
    except urllib.error.URLError as exc:
        err = f"Fetch failed: {exc.reason}\n"
        sys.stderr.write(err)
        log_activity(url, success=False, error=str(exc.reason))
        sys.exit(1)
    except ssl.SSLError as exc:
        err = f"SSL error: {exc}\n"
        sys.stderr.write(err)
        log_activity(url, success=False, error="ssl_error")
        sys.exit(1)
    except TimeoutError:
        sys.stderr.write("Request timed out\n")
        log_activity(url, success=False, error="timeout")
        sys.exit(1)

    text = extract_text(html_content, validated_url)

    if not text:
        sys.stdout.write(f"No readable content extracted from: {url}\n")
        log_activity(url, success=True, error="empty_extraction")
        return

    output = truncate_text(text, max_chars)

    header = f"Source: {url}\n{'=' * 60}\n\n"
    sys.stdout.write(header + output + "\n")
    log_activity(url, success=True)


if __name__ == "__main__":
    main()
