"""FTS5-backed full-text search index for thoughts and dreams."""

import re
import sqlite3
import threading
from pathlib import Path

import structlog

from api.content.loader import ContentResult, read_content
from api.content.paths import ALLOWED_ROOTS
from api.content.schemas import DreamMeta, ThoughtMeta
from api.search.schemas import SearchResponse, SearchResult, SearchResultType

logger = structlog.get_logger()

_MARKDOWN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"\*(.+?)\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"_(.+?)_"), r"\1"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
    (re.compile(r"`(.+?)`"), r"\1"),
    (re.compile(r"^```.*?```$", re.MULTILINE | re.DOTALL), ""),
    (re.compile(r"!?\[([^\]]*)\]\([^)]*\)"), r"\1"),
    (re.compile(r"^>\s?", re.MULTILINE), ""),
    (re.compile(r"^[-*+]\s", re.MULTILINE), ""),
    (re.compile(r"^\d+\.\s", re.MULTILINE), ""),
    (re.compile(r"^---+$", re.MULTILINE), ""),
    (re.compile(r"\n{3,}"), "\n\n"),
]

# FTS5 special characters that need escaping in queries
_FTS5_SPECIAL = re.compile(r"[\"*(){}[\]^~:\-]")


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting for cleaner indexing.

    Args:
        text: Raw markdown content.

    Returns:
        Plain text with markdown syntax removed.
    """
    result = text
    for pattern, replacement in _MARKDOWN_PATTERNS:
        result = pattern.sub(replacement, result)
    return result.strip()


def _sanitize_query(raw: str) -> str | None:
    """Sanitize user input for FTS5 MATCH safety.

    Escapes special characters, handles unbalanced quotes, and wraps
    multi-word queries. Returns None if the query is empty after
    sanitization.

    Args:
        raw: Raw user query string.

    Returns:
        Sanitized FTS5 query string, or None if unusable.
    """
    query = raw.strip()
    if not query:
        return None

    query = _FTS5_SPECIAL.sub(" ", query)
    query = re.sub(r"\s+", " ", query).strip()
    if not query:
        return None

    tokens = query.split()
    if len(tokens) == 1:
        return f"{tokens[0]}*"

    # Multi-word: quote exact tokens, prefix-match on last for typeahead
    parts = [f'"{t}"' for t in tokens[:-1]]
    parts.append(f"{tokens[-1]}*")
    return " ".join(parts)


class SearchIndex:
    """In-memory SQLite FTS5 index for content search.

    Thread-safe via a reentrant lock. The database uses
    check_same_thread=False since watchdog callbacks fire
    from different threads.
    """

    def __init__(self) -> None:
        """Initialize search index (call initialize() before use)."""
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """Create in-memory database and FTS5 virtual table."""
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.execute("""
            CREATE VIRTUAL TABLE content_fts USING fts5(
                title,
                body,
                slug UNINDEXED,
                content_type UNINDEXED,
                date UNINDEXED,
                mood UNINDEXED,
                dream_type UNINDEXED,
                tokenize='porter unicode61'
            )
            """)
        self._conn.commit()
        logger.info("search_index_initialized")

    def rebuild(
        self,
        thoughts_dir: str | None = None,
        dreams_dir: str | None = None,
    ) -> int:
        """Rebuild the entire index from filesystem.

        Args:
            thoughts_dir: Path to thoughts directory. Uses ALLOWED_ROOTS default.
            dreams_dir: Path to dreams directory. Uses ALLOWED_ROOTS default.

        Returns:
            Total number of documents indexed.
        """
        t_dir = Path(thoughts_dir or ALLOWED_ROOTS["thoughts"])
        d_dir = Path(dreams_dir or ALLOWED_ROOTS["dreams"])
        count = 0

        with self._lock:
            assert self._conn is not None
            self._conn.execute("DELETE FROM content_fts")

            count += self._index_directory(t_dir, ThoughtMeta, SearchResultType.THOUGHT)
            count += self._index_directory(d_dir, DreamMeta, SearchResultType.DREAM)

            self._conn.commit()

        logger.info("search_index_rebuilt", document_count=count)
        return count

    def _index_directory(
        self,
        directory: Path,
        schema: type[ThoughtMeta] | type[DreamMeta],
        content_type: SearchResultType,
    ) -> int:
        """Index all markdown files in a directory.

        Args:
            directory: Path to scan for .md files.
            schema: Pydantic model for frontmatter validation.
            content_type: Type tag for indexed documents.

        Returns:
            Number of documents successfully indexed.
        """
        count = 0
        if not directory.exists():
            return count

        for filepath in sorted(directory.glob("*.md")):
            try:
                result: ContentResult[ThoughtMeta | DreamMeta] = read_content(
                    filepath, schema
                )
                self._insert_document(filepath, result, content_type)
                count += 1
            except Exception:
                logger.warning("search_index_skip", path=str(filepath))
        return count

    def _insert_document(
        self,
        filepath: Path,
        result: ContentResult[ThoughtMeta | DreamMeta],
        content_type: SearchResultType,
    ) -> None:
        """Insert a single document into the FTS5 table.

        Args:
            filepath: Source file path (slug derived from stem).
            result: Parsed content with validated frontmatter.
            content_type: Whether this is a thought or dream.
        """
        assert self._conn is not None
        meta = result.meta
        slug = filepath.stem
        body = _strip_markdown(result.content)

        mood: str | None = None
        dream_type: str | None = None

        if isinstance(meta, ThoughtMeta):
            mood = meta.mood
        elif isinstance(meta, DreamMeta):
            dream_type = meta.type.value

        self._conn.execute(
            """
            INSERT INTO content_fts (title, body, slug, content_type, date, mood, dream_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta.title,
                body,
                slug,
                content_type.value,
                meta.date,
                mood or "",
                dream_type or "",
            ),
        )

    def upsert_document(self, filepath: Path) -> None:
        """Index or re-index a single file (handles create + modify).

        Args:
            filepath: Absolute path to the markdown file.
        """
        slug = filepath.stem
        parent = filepath.parent.name

        if parent == "thoughts":
            schema: type[ThoughtMeta] | type[DreamMeta] = ThoughtMeta
            content_type = SearchResultType.THOUGHT
        elif parent == "dreams":
            schema = DreamMeta
            content_type = SearchResultType.DREAM
        else:
            return

        try:
            result = read_content(filepath, schema)
        except Exception:
            logger.warning("search_upsert_read_failed", path=str(filepath))
            return

        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "DELETE FROM content_fts WHERE slug = ? AND content_type = ?",
                (slug, content_type.value),
            )
            self._insert_document(filepath, result, content_type)
            self._conn.commit()

        logger.info("search_document_upserted", slug=slug, type=content_type.value)

    def delete_document(self, slug: str, content_type: str) -> None:
        """Remove a document from the index.

        Args:
            slug: Document slug identifier.
            content_type: "thought" or "dream".
        """
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "DELETE FROM content_fts WHERE slug = ? AND content_type = ?",
                (slug, content_type),
            )
            self._conn.commit()

        logger.info("search_document_deleted", slug=slug, type=content_type)

    def search(
        self,
        query: str,
        content_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Execute a full-text search with BM25 ranking.

        Args:
            query: Raw user search query.
            content_type: Optional filter ("thought", "dream", or None for all).
            limit: Maximum results to return.
            offset: Number of results to skip.

        Returns:
            SearchResponse with ranked results and pagination metadata.
        """
        sanitized = _sanitize_query(query)
        if sanitized is None:
            return SearchResponse(
                query=query, results=[], total=0, limit=limit, offset=offset
            )

        with self._lock:
            assert self._conn is not None

            if content_type and content_type in ("thought", "dream"):
                count_sql = (
                    "SELECT COUNT(*) FROM content_fts "
                    "WHERE content_fts MATCH ? AND content_type = ?"
                )
                count_params: tuple[str, ...] = (sanitized, content_type)

                search_sql = (
                    "SELECT slug, content_type, date, mood, dream_type, "
                    "snippet(content_fts, 0, '<mark>', '</mark>', '...', 16) AS title_snippet, "
                    "snippet(content_fts, 1, '<mark>', '</mark>', '...', 32) AS body_snippet, "
                    "bm25(content_fts, 10.0, 1.0) AS score "
                    "FROM content_fts "
                    "WHERE content_fts MATCH ? AND content_type = ? "
                    "ORDER BY score "
                    "LIMIT ? OFFSET ?"
                )
                search_params: tuple[str | int, ...] = (
                    sanitized,
                    content_type,
                    limit,
                    offset,
                )
            else:
                count_sql = "SELECT COUNT(*) FROM content_fts WHERE content_fts MATCH ?"
                count_params = (sanitized,)

                search_sql = (
                    "SELECT slug, content_type, date, mood, dream_type, "
                    "snippet(content_fts, 0, '<mark>', '</mark>', '...', 16) AS title_snippet, "
                    "snippet(content_fts, 1, '<mark>', '</mark>', '...', 32) AS body_snippet, "
                    "bm25(content_fts, 10.0, 1.0) AS score "
                    "FROM content_fts "
                    "WHERE content_fts MATCH ? "
                    "ORDER BY score "
                    "LIMIT ? OFFSET ?"
                )
                search_params = (sanitized, limit, offset)

            try:
                total = self._conn.execute(count_sql, count_params).fetchone()[0]
                rows = self._conn.execute(search_sql, search_params).fetchall()
            except sqlite3.OperationalError:
                logger.warning("search_query_failed", query=query)
                return SearchResponse(
                    query=query, results=[], total=0, limit=limit, offset=offset
                )

        results: list[SearchResult] = []
        for row in rows:
            slug, ct, date, mood, dream_type, title_snip, body_snip, score = row
            result_type = SearchResultType(ct)
            results.append(
                SearchResult(
                    slug=slug,
                    title=title_snip if title_snip else slug,
                    result_type=result_type,
                    date=date,
                    snippet=body_snip or "",
                    score=round(score, 4),
                    mood=mood if mood else None,
                    dream_type=dream_type if dream_type else None,
                )
            )

        return SearchResponse(
            query=query,
            results=results,
            total=total,
            limit=limit,
            offset=offset,
        )

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
                logger.info("search_index_closed")
