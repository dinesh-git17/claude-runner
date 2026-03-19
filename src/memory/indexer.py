"""Build and maintain the FAISS vector index for memory."""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import faiss  # type: ignore[import-untyped]
import numpy as np
from sentence_transformers import SentenceTransformer

from memory.chunker import ChunkMeta, chunk_file, chunk_jar, chunk_mailbox
from memory.config import (
    CONTENT_SOURCES,
    EMBEDDING_DIM,
    INDEX_DIR,
    INDEX_FAISS_PATH,
    INDEX_META_PATH,
    INDEX_STATE_PATH,
    MODEL_NAME,
    SourceType,
)

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def _collect_files() -> list[tuple[Path, SourceType]]:
    """Gather all indexable file paths from content sources."""
    files: list[tuple[Path, SourceType]] = []

    for source_path, source_type, glob_pattern in CONTENT_SOURCES:
        if source_type == SourceType.JAR:
            if source_path.is_file():
                files.append((source_path, source_type))
            continue

        if source_type == SourceType.MAILBOX:
            if source_path.is_dir():
                for match in sorted(source_path.glob(glob_pattern)):
                    files.append((match, source_type))
            continue

        if source_path.is_dir() and glob_pattern:
            for match in sorted(source_path.glob(glob_pattern)):
                files.append((match, source_type))

    return files


def _chunk_one(path: Path, source_type: SourceType) -> list[ChunkMeta]:
    """Chunk a single file based on its source type."""
    if source_type == SourceType.JAR:
        return chunk_jar(path)
    if source_type == SourceType.MAILBOX:
        return chunk_mailbox(path)
    return chunk_file(path)


def _get_file_mtimes(
    files: list[tuple[Path, SourceType]],
) -> dict[str, float]:
    """Build {filepath: mtime} map for all files."""
    state: dict[str, float] = {}
    for path, _ in files:
        try:
            state[str(path)] = path.stat().st_mtime
        except OSError:
            continue
    return state


def _load_state() -> dict[str, float]:
    """Load previous index state (file mtimes)."""
    if not INDEX_STATE_PATH.exists():
        return {}
    try:
        raw: Any = json.loads(INDEX_STATE_PATH.read_text(encoding="utf-8"))
        return dict(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, float]) -> None:
    """Persist file mtime state."""
    INDEX_STATE_PATH.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )


def _load_meta() -> list[dict[str, Any]]:
    """Load existing chunk metadata."""
    if not INDEX_META_PATH.exists():
        return []
    try:
        data: Any = json.loads(INDEX_META_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [dict(item) for item in data]
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _save_meta(meta: list[dict[str, Any]]) -> None:
    """Persist chunk metadata."""
    INDEX_META_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _embed_texts(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    """Embed a batch of texts, L2-normalized for cosine via IndexFlatIP."""
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    embeddings: np.ndarray = model.encode(
        texts,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return embeddings.astype(np.float32)


def build_full_index() -> None:
    """Build the index from scratch over all content sources."""
    t0 = time.monotonic()
    logger.info("Starting full index build...")

    files = _collect_files()
    logger.info("Found %d files to index", len(files))

    all_chunks: list[ChunkMeta] = []
    for path, source_type in files:
        chunks = _chunk_one(path, source_type)
        all_chunks.extend(chunks)

    logger.info("Generated %d chunks", len(all_chunks))

    if not all_chunks:
        logger.warning("No chunks generated — creating empty index")
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        faiss.write_index(index, str(INDEX_FAISS_PATH))
        _save_meta([])
        _save_state(_get_file_mtimes(files))
        return

    model = SentenceTransformer(MODEL_NAME)
    texts = [c.text for c in all_chunks]
    logger.info("Embedding %d chunks...", len(texts))
    embeddings = _embed_texts(model, texts)

    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    index.add(embeddings)
    faiss.write_index(index, str(INDEX_FAISS_PATH))

    meta = [c.to_dict() for c in all_chunks]
    _save_meta(meta)
    _save_state(_get_file_mtimes(files))

    elapsed = time.monotonic() - t0
    logger.info(
        "Full index built: %d chunks, %d vectors, %.1fs",
        len(all_chunks),
        index.ntotal,
        elapsed,
    )


def build_incremental_index() -> None:
    """Update the index incrementally — only re-process changed/new files."""
    t0 = time.monotonic()
    logger.info("Starting incremental index update...")

    if not INDEX_FAISS_PATH.exists():
        logger.info("No existing index — falling back to full build")
        build_full_index()
        return

    old_state = _load_state()
    files = _collect_files()
    new_state = _get_file_mtimes(files)

    # Determine changed, new, and deleted files
    changed: list[tuple[Path, SourceType]] = []
    deleted_paths: set[str] = set()

    for path_str in old_state:
        if path_str not in new_state:
            deleted_paths.add(path_str)

    for path, source_type in files:
        path_str = str(path)
        old_mtime = old_state.get(path_str)
        if old_mtime is None or new_state.get(path_str, 0) != old_mtime:
            changed.append((path, source_type))

    if not changed and not deleted_paths:
        logger.info("No changes detected — index is current")
        return

    logger.info(
        "%d changed/new files, %d deleted files",
        len(changed),
        len(deleted_paths),
    )

    # Load existing index and metadata
    index: Any = faiss.read_index(str(INDEX_FAISS_PATH))
    old_meta = _load_meta()

    # Identify files that need re-chunking (changed + deleted)
    reindex_paths = {str(p) for p, _ in changed} | deleted_paths

    # Partition: keep unchanged chunks, discard chunks from re-indexed files
    keep_indices: list[int] = []
    keep_meta: list[dict[str, Any]] = []
    for i, m in enumerate(old_meta):
        src = str(m.get("source_file", ""))
        # source_file is relative; old_state keys are absolute
        full_path = str(Path("/claude-home") / src)
        if full_path not in reindex_paths and src not in reindex_paths:
            keep_indices.append(i)
            keep_meta.append(m)

    # Extract kept vectors
    if keep_indices:
        all_vectors = faiss.rev_swig_ptr(
            index.get_xb(),
            index.ntotal * EMBEDDING_DIM,
        )
        all_vectors = np.array(all_vectors, dtype=np.float32).reshape(
            index.ntotal,
            EMBEDDING_DIM,
        )
        kept_vectors: np.ndarray = all_vectors[keep_indices]
    else:
        kept_vectors = np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    # Chunk changed files
    new_chunks: list[ChunkMeta] = []
    for path, source_type in changed:
        chunks = _chunk_one(path, source_type)
        new_chunks.extend(chunks)

    logger.info("Re-chunked %d files → %d new chunks", len(changed), len(new_chunks))

    # Embed new chunks
    if new_chunks:
        model = SentenceTransformer(MODEL_NAME)
        new_texts = [c.text for c in new_chunks]
        new_embeddings = _embed_texts(model, new_texts)
    else:
        new_embeddings = np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    # Rebuild index
    if kept_vectors.shape[0] > 0 or new_embeddings.shape[0] > 0:
        combined_vectors: np.ndarray = np.vstack([kept_vectors, new_embeddings])
    else:
        combined_vectors = np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    new_index = faiss.IndexFlatIP(EMBEDDING_DIM)
    if combined_vectors.shape[0] > 0:
        new_index.add(combined_vectors)

    faiss.write_index(new_index, str(INDEX_FAISS_PATH))

    combined_meta = keep_meta + [c.to_dict() for c in new_chunks]
    _save_meta(combined_meta)
    _save_state(new_state)

    elapsed = time.monotonic() - t0
    logger.info(
        "Incremental update: %d total chunks, %d kept, %d new, %.1fs",
        len(combined_meta),
        len(keep_meta),
        len(new_chunks),
        elapsed,
    )


def main() -> None:
    """CLI entry point for the memory indexer."""
    parser = argparse.ArgumentParser(description="Memory indexer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true", help="Full index rebuild")
    group.add_argument(
        "--incremental",
        action="store_true",
        help="Incremental update",
    )
    args = parser.parse_args()

    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    if args.full:
        build_full_index()
    else:
        build_incremental_index()


if __name__ == "__main__":
    main()
