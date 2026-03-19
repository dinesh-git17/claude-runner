"""Search engine for the memory index."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import faiss  # type: ignore[import-untyped]
import numpy as np
from sentence_transformers import SentenceTransformer

from memory.chunker import ChunkMeta
from memory.config import (
    CLAUDE_HOME,
    INDEX_FAISS_PATH,
    INDEX_META_PATH,
    MODEL_NAME,
)

logger = logging.getLogger(__name__)


@dataclass
class SearchFilters:
    """Filters for narrowing search results."""

    source_type: str | None = None
    before_date: str | None = None
    after_date: str | None = None
    person: str | None = None


@dataclass
class SearchResult:
    """A single search result with score and metadata."""

    score: float
    chunk: ChunkMeta
    full_text: str | None = None


class MemorySearcher:
    """Lazy-loading search engine over the FAISS index."""

    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None
        self._index: Any | None = None
        self._meta: list[ChunkMeta] | None = None

    def _ensure_loaded(self) -> None:
        """Load model, index, and metadata on first use."""
        if self._model is not None:
            return

        if not INDEX_FAISS_PATH.exists():
            msg = "Index not found. Run the indexer with --full first."
            raise FileNotFoundError(msg)

        self._model = SentenceTransformer(MODEL_NAME)
        self._index = faiss.read_index(str(INDEX_FAISS_PATH))

        raw_meta: Any = json.loads(INDEX_META_PATH.read_text(encoding="utf-8"))
        self._meta = [ChunkMeta.from_dict(m) for m in raw_meta]

    def _embed_query(self, query: str) -> np.ndarray:
        """Embed a query string, normalized for cosine similarity."""
        assert self._model is not None
        vec: np.ndarray = self._model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vec.astype(np.float32)

    def _matches_filters(
        self,
        chunk: ChunkMeta,
        filters: SearchFilters,
    ) -> bool:
        """Check if a chunk passes the given filters."""
        if filters.source_type and chunk.source_type != filters.source_type:
            return False

        if filters.before_date and chunk.date and chunk.date > filters.before_date:
            return False

        if filters.after_date and chunk.date and chunk.date < filters.after_date:
            return False

        if filters.person:
            person_lower = filters.person.lower()
            extra = chunk.extra or {}
            username = str(extra.get("username", "")).lower()
            sender = str(extra.get("sender", "")).lower()
            participant = str(extra.get("participant", "")).lower()
            text_lower = chunk.text.lower()
            if not (
                person_lower in username
                or person_lower in sender
                or person_lower in participant
                or person_lower in text_lower
            ):
                return False

        return True

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: SearchFilters | None = None,
        include_full: bool = False,
        include_context: bool = False,
    ) -> list[SearchResult]:
        """Search the index for chunks matching the query.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.
            filters: Optional metadata filters.
            include_full: If True, load the complete source file for each result.
            include_context: If True, include +/-2 adjacent chunks from same file.

        Returns:
            Ranked list of SearchResult objects.
        """
        self._ensure_loaded()
        assert self._index is not None
        assert self._meta is not None

        if self._index.ntotal == 0:
            return []

        query_vec = self._embed_query(query)

        # Over-fetch to account for post-retrieval filtering
        fetch_k = min(top_k * 5, self._index.ntotal)
        scores_arr, indices_arr = self._index.search(query_vec, fetch_k)

        scores: list[float] = scores_arr[0].tolist()
        indices: list[int] = indices_arr[0].tolist()

        effective_filters = filters or SearchFilters()
        results: list[SearchResult] = []

        for score, idx in zip(scores, indices, strict=False):
            if idx < 0 or idx >= len(self._meta):
                continue
            chunk = self._meta[idx]
            if not self._matches_filters(chunk, effective_filters):
                continue

            full_text: str | None = None
            if include_full:
                full_text = self._load_full_text(chunk)

            result = SearchResult(score=float(score), chunk=chunk, full_text=full_text)
            results.append(result)

            if len(results) >= top_k:
                break

        if include_context:
            results = self._attach_context(results)

        return results

    def _load_full_text(self, chunk: ChunkMeta) -> str | None:
        """Load the complete source file content for a chunk."""
        source_path = CLAUDE_HOME / chunk.source_file
        try:
            return source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _attach_context(
        self,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """Attach +/-2 adjacent chunks from the same file to each result."""
        assert self._meta is not None

        # Build file -> sorted chunk list mapping
        file_chunks: dict[str, list[tuple[int, ChunkMeta]]] = {}
        for i, m in enumerate(self._meta):
            file_chunks.setdefault(m.source_file, []).append((i, m))

        for result in results:
            src = result.chunk.source_file
            siblings = file_chunks.get(src, [])
            if len(siblings) <= 1:
                continue

            # Find position of this chunk among its siblings
            chunk_idx: int | None = None
            for pos, (_, m) in enumerate(siblings):
                if m.chunk_id == result.chunk.chunk_id:
                    chunk_idx = pos
                    break

            if chunk_idx is None:
                continue

            context_start = max(0, chunk_idx - 2)
            context_end = min(len(siblings), chunk_idx + 3)
            context_texts = [
                siblings[j][1].text
                for j in range(context_start, context_end)
                if j != chunk_idx
            ]
            if context_texts:
                result.full_text = "\n\n---\n\n".join(
                    [
                        *context_texts[: chunk_idx - context_start],
                        f">>> {result.chunk.text} <<<",
                        *context_texts[chunk_idx - context_start :],
                    ],
                )

        return results

    def format_default(self, results: list[SearchResult], query: str) -> str:
        """Format results in the default CLI output format.

        Args:
            results: Search results to format.
            query: Original query string for the header.

        Returns:
            Human-readable multi-line string.
        """
        if not results:
            return f'No passages found matching "{query}".'

        lines = [f'Found {len(results)} passages matching "{query}":\n']
        for i, r in enumerate(results, 1):
            date_str = r.chunk.date or "undated"
            extra_info = ""
            if r.chunk.extra:
                session = r.chunk.extra.get("session_type", "")
                username = r.chunk.extra.get("username", "")
                sender = r.chunk.extra.get("sender", "")
                if session:
                    extra_info = f", {session}"
                elif username:
                    sender_label = f" from {sender}" if sender else ""
                    extra_info = f", {username}{sender_label}"

            header = (
                f"{i}. [{r.score:.2f}] {r.chunk.source_file} ({date_str}{extra_info})"
            )
            lines.append(header)

            display_text = r.full_text if r.full_text else r.chunk.text
            preview = display_text[:500]
            if len(display_text) > 500:
                preview += "..."
            indented = "\n".join(f"   {line}" for line in preview.splitlines())
            lines.append(f'   "{indented.strip()}"')
            lines.append("")

        return "\n".join(lines)

    def format_system_prompt(
        self,
        results: list[SearchResult],
        min_score: float = 0.25,
    ) -> str:
        """Format results for injection into a system prompt.

        Filters out results below min_score to avoid injecting noise.

        Args:
            results: Search results to format.
            min_score: Minimum similarity score threshold.

        Returns:
            Markdown-formatted string, or empty string if nothing qualifies.
        """
        relevant = [r for r in results if r.score >= min_score]
        if not relevant:
            return ""

        lines = [
            "## Memory Echoes",
            "*Passages from your writing that resonate with this session's context.",
            "These are offered, not imposed — use them if they help.*",
            "",
        ]

        for r in relevant:
            preview = r.chunk.text[:200]
            if len(r.chunk.text) > 200:
                preview += "..."
            quoted = "\n".join(f"> {line}" for line in preview.splitlines())
            date_str = f" ({r.chunk.date})" if r.chunk.date else ""
            lines.append(quoted)
            lines.append(f"> — {r.chunk.source_file}{date_str}")
            lines.append("")

        return "\n".join(lines)


def get_searcher() -> MemorySearcher:
    """Get a searcher instance."""
    return MemorySearcher()
