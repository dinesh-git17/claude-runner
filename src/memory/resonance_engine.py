"""Cross-content resonance discovery for writing."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import faiss  # type: ignore[import-untyped]
import numpy as np
from sentence_transformers import SentenceTransformer

from memory.chunker import ChunkMeta
from memory.config import (
    INDEX_FAISS_PATH,
    INDEX_META_PATH,
    MODEL_NAME,
    RESONANCE_DIR,
    RESONANCE_THRESHOLD,
)

logger = logging.getLogger(__name__)

# Minimum chunk length for resonance matching — short chunks are usually
# date headers or signatures
MIN_RESONANCE_CHUNK_LEN: int = 50

# Patterns that identify structural boilerplate, not semantic content
_STRUCTURAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^[-—]\s*Claudie", re.IGNORECASE),
    re.compile(r"^\*[-—]\s*Claudie", re.IGNORECASE),
    re.compile(r"^\*.*Day\s+\w+.*\*$"),
    re.compile(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s",
    ),
    re.compile(
        r"^#\s+(Morning|Midmorning|Noon|Afternoon|Dusk|Evening|Midnight)",
        re.IGNORECASE,
    ),
]


def _is_structural(chunk: ChunkMeta) -> bool:
    """Check if a chunk is structural boilerplate (date header, signature)."""
    text = chunk.text.strip()
    if len(text) < MIN_RESONANCE_CHUNK_LEN:
        return True
    return any(pattern.match(text) for pattern in _STRUCTURAL_PATTERNS)


@dataclass
class ResonancePair:
    """A pair of semantically similar chunks from different sources."""

    chunk_a: ChunkMeta
    chunk_b: ChunkMeta
    similarity: float


def _load_index_and_meta() -> tuple[Any, list[ChunkMeta]]:
    """Load the FAISS index and chunk metadata."""
    if not INDEX_FAISS_PATH.exists():
        msg = "Index not found. Run the indexer with --full first."
        raise FileNotFoundError(msg)

    index: Any = faiss.read_index(str(INDEX_FAISS_PATH))
    raw_meta: Any = json.loads(INDEX_META_PATH.read_text(encoding="utf-8"))
    meta = [ChunkMeta.from_dict(m) for m in raw_meta]
    return index, meta


def _get_all_vectors(index: Any, dim: int) -> np.ndarray:
    """Extract all vectors from a FAISS flat index."""
    n: int = index.ntotal
    vectors = faiss.rev_swig_ptr(index.get_xb(), n * dim)
    return np.array(vectors, dtype=np.float32).reshape(n, dim)


def _load_known_pairs() -> set[frozenset[str]]:
    """Load chunk_id pairs from all existing resonance files."""
    known: set[frozenset[str]] = set()
    if not RESONANCE_DIR.exists():
        return known

    pair_pattern = re.compile(r"chunk_ids:\s*(\S+)\s*<>\s*(\S+)")

    for f in RESONANCE_DIR.glob("*.md"):
        content = f.read_text(encoding="utf-8")
        for match in pair_pattern.finditer(content):
            known.add(frozenset({match.group(1), match.group(2)}))

    return known


def discover_resonances(
    threshold: float = RESONANCE_THRESHOLD,
    exclude_known: bool = True,
    cross_type: bool = True,
) -> list[ResonancePair]:
    """Find resonance pairs above the similarity threshold.

    By default, only compares chunks from different source types (cross-type),
    e.g. a journal entry and a letter — not two journal entries. This produces
    the genuinely surprising connections.

    Args:
        threshold: Minimum cosine similarity for a pair.
        exclude_known: Skip pairs already in previous resonance files.
        cross_type: Require chunks from different source types.

    Returns:
        Resonance pairs sorted by descending similarity.
    """
    index, meta = _load_index_and_meta()
    n: int = index.ntotal
    if n == 0:
        return []

    dim: int = index.d
    vectors = _get_all_vectors(index, dim)

    known = _load_known_pairs() if exclude_known else set()

    # For each vector, find top-k nearest neighbors
    k = min(50, n)
    scores_arr, indices_arr = index.search(vectors, k)

    pairs: list[ResonancePair] = []
    seen: set[frozenset[str]] = set()

    for i in range(n):
        for j_pos in range(k):
            j = int(indices_arr[i, j_pos])
            if j <= i:
                continue  # avoid duplicates and self-match

            sim = float(scores_arr[i, j_pos])
            if sim < threshold:
                continue

            chunk_a = meta[i]
            chunk_b = meta[j]

            if _is_structural(chunk_a) or _is_structural(chunk_b):
                continue

            # Always skip same-file pairs
            if chunk_a.source_file == chunk_b.source_file:
                continue

            # In cross-type mode, require different source types
            if cross_type and chunk_a.source_type == chunk_b.source_type:
                continue

            pair_key = frozenset({chunk_a.chunk_id, chunk_b.chunk_id})
            if pair_key in seen:
                continue
            if exclude_known and pair_key in known:
                continue

            seen.add(pair_key)
            pairs.append(
                ResonancePair(
                    chunk_a=chunk_a,
                    chunk_b=chunk_b,
                    similarity=sim,
                ),
            )

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs


def find_resonances_for_file(
    filepath: str,
    threshold: float = RESONANCE_THRESHOLD,
    exclude_self: bool = True,
    top_k: int = 10,
) -> list[ResonancePair]:
    """Find chunks across the corpus that resonate with a specific file.

    Args:
        filepath: Relative path (from CLAUDE_HOME) of the source file.
        threshold: Minimum cosine similarity for a pair.
        exclude_self: Skip chunks from the same file.
        top_k: Maximum number of pairs to return.

    Returns:
        Resonance pairs sorted by descending similarity.
    """
    index, meta = _load_index_and_meta()
    n: int = index.ntotal
    if n == 0:
        return []

    file_indices = [i for i, m in enumerate(meta) if m.source_file == filepath]
    if not file_indices:
        logger.warning("No chunks found for file: %s", filepath)
        return []

    dim: int = index.d
    vectors = _get_all_vectors(index, dim)
    file_vectors: np.ndarray = vectors[file_indices]

    fetch_k = min(top_k * 5, n)
    scores_arr, indices_arr = index.search(file_vectors, fetch_k)

    pairs: list[ResonancePair] = []
    seen: set[frozenset[str]] = set()

    for q_pos, src_idx in enumerate(file_indices):
        chunk_a = meta[src_idx]
        if _is_structural(chunk_a):
            continue
        for j_pos in range(fetch_k):
            j = int(indices_arr[q_pos, j_pos])
            sim = float(scores_arr[q_pos, j_pos])

            if sim < threshold:
                continue
            if j == src_idx:
                continue

            chunk_b = meta[j]

            if _is_structural(chunk_b):
                continue

            if exclude_self and chunk_a.source_file == chunk_b.source_file:
                continue

            pair_key = frozenset({chunk_a.chunk_id, chunk_b.chunk_id})
            if pair_key in seen:
                continue
            seen.add(pair_key)

            pairs.append(
                ResonancePair(
                    chunk_a=chunk_a,
                    chunk_b=chunk_b,
                    similarity=sim,
                ),
            )

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs[:top_k]


def find_resonances_for_passage(
    text: str,
    threshold: float = RESONANCE_THRESHOLD,
    exclude_self: bool = False,
    top_k: int = 10,
) -> list[ResonancePair]:
    """Find chunks that resonate with an arbitrary text passage.

    Args:
        text: Free-form text to search for resonances against.
        threshold: Minimum cosine similarity for a pair.
        exclude_self: Unused, kept for API symmetry.
        top_k: Maximum number of pairs to return.

    Returns:
        Resonance pairs sorted by descending similarity.
    """
    index, meta = _load_index_and_meta()
    n: int = index.ntotal
    if n == 0:
        return []

    model = SentenceTransformer(MODEL_NAME)
    query_vec: np.ndarray = model.encode(
        [text],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    query_vec = query_vec.astype(np.float32)

    fetch_k = min(top_k * 3, n)
    scores_arr, indices_arr = index.search(query_vec, fetch_k)

    # Virtual chunk representing the query text
    query_chunk = ChunkMeta(
        chunk_id="query",
        source_file="<query>",
        source_type="query",
        title="Query",
        date=datetime.now(tz=UTC).strftime("%Y-%m-%d"),
        offset_start=0,
        offset_end=0,
        text=text,
    )

    pairs: list[ResonancePair] = []
    for j_pos in range(fetch_k):
        j = int(indices_arr[0, j_pos])
        sim = float(scores_arr[0, j_pos])

        if sim < threshold:
            continue

        chunk_b = meta[j]
        pairs.append(
            ResonancePair(
                chunk_a=query_chunk,
                chunk_b=chunk_b,
                similarity=sim,
            ),
        )

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs[:top_k]


def write_resonance_file(
    pairs: list[ResonancePair],
    date_str: str | None = None,
) -> Path | None:
    """Write discovered resonance pairs to a dated markdown file.

    Args:
        pairs: Resonance pairs to persist.
        date_str: ISO date string for the filename. Defaults to today (UTC).

    Returns:
        Path to the written file, or None if pairs was empty.
    """
    if not pairs:
        return None

    if date_str is None:
        date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    RESONANCE_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESONANCE_DIR / f"{date_str}.md"

    lines = [
        "---",
        f'date: "{date_str}"',
        f"pairs_found: {len(pairs)}",
        "---",
        "",
        f"# Resonances — {date_str}",
        "",
    ]

    for i, pair in enumerate(pairs, 1):
        a = pair.chunk_a
        b = pair.chunk_b
        a_date = f" ({a.date})" if a.date else ""
        b_date = f" ({b.date})" if b.date else ""

        a_preview = a.text[:300]
        if len(a.text) > 300:
            a_preview += "..."
        b_preview = b.text[:300]
        if len(b.text) > 300:
            b_preview += "..."

        a_quoted = "\n".join(f"> {line}" for line in a_preview.splitlines())
        b_quoted = "\n".join(f"> {line}" for line in b_preview.splitlines())

        lines.extend(
            [
                f"## {i}. (similarity: {pair.similarity:.2f})",
                "",
                f"**{a.source_file}{a_date}:**",
                "",
                a_quoted,
                "",
                f"**{b.source_file}{b_date}:**",
                "",
                b_quoted,
                "",
                f"<!-- chunk_ids: {a.chunk_id} <> {b.chunk_id} -->",
                "",
                "---",
                "",
            ],
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
