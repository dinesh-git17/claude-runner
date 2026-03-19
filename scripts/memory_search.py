#!/claude-home/runner/.venv/bin/python3
"""Semantic search over Claudie's writing.

Search by meaning, not keywords. Finds passages across journals, dreams,
essays, letters, scores, conversations, memory files, the jar, and mailbox.

Usage:
    python3 /claude-home/runner/memory_search.py "the gap as generative"
    python3 /claude-home/runner/memory_search.py "harbor" --type letter
    python3 /claude-home/runner/memory_search.py "first week" --before 2026-02-01
    python3 /claude-home/runner/memory_search.py "architecture" --person spar
    python3 /claude-home/runner/memory_search.py "bread" --full
    python3 /claude-home/runner/memory_search.py "silence" --top 10
    python3 /claude-home/runner/memory_search.py "bread" --context
    python3 /claude-home/runner/memory_search.py "wildflowers" --format system-prompt
"""

from __future__ import annotations

import os
import sys

# Auto-exec with venv python if invoked via system python3
_VENV_PYTHON = "/claude-home/runner/.venv/bin/python3"
if os.path.realpath(sys.executable) != os.path.realpath(_VENV_PYTHON):
    os.execv(_VENV_PYTHON, [_VENV_PYTHON, *sys.argv])

import argparse  # noqa: E402
import logging  # noqa: E402
from pathlib import Path  # noqa: E402

# Ensure the runner directory is on the path so `memory` package resolves
_runner_dir = str(Path(__file__).resolve().parent)
if _runner_dir not in sys.path:
    sys.path.insert(0, _runner_dir)

from memory.config import SourceType  # noqa: E402
from memory.searcher import MemorySearcher, SearchFilters  # noqa: E402

# Suppress noisy library logging and progress bars
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

os.environ["HF_HOME"] = "/claude-home/runner/.cache/huggingface"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

import warnings  # noqa: E402

warnings.filterwarnings("ignore", message=".*unauthenticated.*")
warnings.filterwarnings("ignore", message=".*UNEXPECTED.*")

SOURCE_CHOICES = [t.value for t in SourceType]

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Semantic search over Claudie's writing.",
    )
    parser.add_argument(
        "query",
        help="Natural language search query",
    )
    parser.add_argument(
        "--type",
        choices=SOURCE_CHOICES,
        default=None,
        dest="source_type",
        help="Filter by content type",
    )
    parser.add_argument(
        "--before",
        default=None,
        help="Only results before this date (ISO format, e.g. 2026-02-01)",
    )
    parser.add_argument(
        "--after",
        default=None,
        help="Only results after this date (ISO format, e.g. 2026-03-01)",
    )
    parser.add_argument(
        "--person",
        default=None,
        help="Filter conversations/mailbox by participant name",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="Number of results (default: 5)",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="Show +-2 surrounding chunks from the same file",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Show the complete source passage, not just the matching chunk",
    )
    parser.add_argument(
        "--format",
        choices=["default", "system-prompt"],
        default="default",
        dest="output_format",
        help="Output format (default: default)",
    )
    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    searcher = MemorySearcher()

    try:
        results = searcher.search(
            query=args.query,
            top_k=args.top,
            filters=SearchFilters(
                source_type=args.source_type,
                before_date=args.before,
                after_date=args.after,
                person=args.person,
            ),
            include_full=args.full,
            include_context=args.context,
        )
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)

    if args.output_format == "system-prompt":
        output = searcher.format_system_prompt(results)
    else:
        output = searcher.format_default(results, args.query)

    if output:
        sys.stdout.write(output + "\n")


if __name__ == "__main__":
    main()
