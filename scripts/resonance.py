#!/claude-home/runner/.venv/bin/python3
"""Discover connections across Claudie's writing.

Finds semantically similar passages from different content types --
a journal entry and a letter might use different words to express
the same idea. The tool finds the thread; Claudie decides if it means
something.

Usage:
    python3 /claude-home/runner/resonance.py discover
    python3 /claude-home/runner/resonance.py discover --threshold 0.80
    python3 /claude-home/runner/resonance.py today
    python3 /claude-home/runner/resonance.py for thoughts/2026-03-17-morning.md
    python3 /claude-home/runner/resonance.py for thoughts/2026-03-17-morning.md --exclude-self
    python3 /claude-home/runner/resonance.py passage "the line that held"
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
import warnings  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

# Ensure runner dir on path
_runner_dir = str(Path(__file__).resolve().parent)
if _runner_dir not in sys.path:
    sys.path.insert(0, _runner_dir)

# Suppress noisy library output
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

os.environ["HF_HOME"] = "/claude-home/runner/.cache/huggingface"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

warnings.filterwarnings("ignore", message=".*unauthenticated.*")
warnings.filterwarnings("ignore", message=".*UNEXPECTED.*")

from memory.config import RESONANCE_DIR, RESONANCE_THRESHOLD  # noqa: E402
from memory.resonance_engine import (  # noqa: E402
    ResonancePair,
    discover_resonances,
    find_resonances_for_file,
    find_resonances_for_passage,
    write_resonance_file,
)

log = logging.getLogger(__name__)


def _format_pairs_inline(pairs: list[ResonancePair]) -> str:
    """Format resonance pairs for inline CLI display."""
    if not pairs:
        return "No resonances found."

    lines = [f"Found {len(pairs)} resonances:\n"]
    for i, pair in enumerate(pairs, 1):
        a = pair.chunk_a
        b = pair.chunk_b
        a_date = f", {a.date}" if a.date else ""
        b_date = f", {b.date}" if b.date else ""

        a_preview = a.text[:200]
        if len(a.text) > 200:
            a_preview += "..."
        b_preview = b.text[:200]
        if len(b.text) > 200:
            b_preview += "..."

        lines.append(f"{i}. (similarity: {pair.similarity:.2f})")
        lines.append(f"   {a.source_file}{a_date}:")
        indented_a = "\n".join(f"   > {line}" for line in a_preview.splitlines())
        lines.append(indented_a)
        lines.append(f"   {b.source_file}{b_date}:")
        indented_b = "\n".join(f"   > {line}" for line in b_preview.splitlines())
        lines.append(indented_b)
        lines.append("")

    return "\n".join(lines)


def cmd_discover(args: argparse.Namespace) -> None:
    """Run automated resonance discovery."""
    threshold = args.threshold
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("resonance")

    logger.info("Discovering resonances (threshold=%.2f)...", threshold)

    try:
        pairs = discover_resonances(
            threshold=threshold,
            exclude_known=True,
        )
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)

    if not pairs:
        logger.info("No new resonances found.")
        return

    logger.info("Found %d new resonance pairs.", len(pairs))

    date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    output = write_resonance_file(pairs, date_str)
    if output:
        logger.info("Written to %s", output)


def cmd_today(args: argparse.Namespace) -> None:
    """Display today's resonances."""
    _ = args
    date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    today_file = RESONANCE_DIR / f"{date_str}.md"

    if not today_file.exists():
        sys.stdout.write("No resonances found today.\n")
        return

    content = today_file.read_text(encoding="utf-8")
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3 :].strip()

    sys.stdout.write(content + "\n")


def cmd_for(args: argparse.Namespace) -> None:
    """Find resonances for a specific file."""
    filepath = args.filepath
    threshold = args.threshold
    exclude_self = args.exclude_self
    top_k = args.top

    try:
        pairs = find_resonances_for_file(
            filepath=filepath,
            threshold=threshold,
            exclude_self=exclude_self,
            top_k=top_k,
        )
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)

    sys.stdout.write(_format_pairs_inline(pairs) + "\n")


def cmd_passage(args: argparse.Namespace) -> None:
    """Find resonances for an arbitrary text passage."""
    text = args.text
    threshold = args.threshold
    top_k = args.top

    try:
        pairs = find_resonances_for_passage(
            text=text,
            threshold=threshold,
            top_k=top_k,
        )
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)

    sys.stdout.write(_format_pairs_inline(pairs) + "\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="Discover connections across Claudie's writing.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_discover = subparsers.add_parser(
        "discover",
        help="Run automated resonance discovery",
    )
    p_discover.add_argument(
        "--threshold",
        type=float,
        default=RESONANCE_THRESHOLD,
        help=f"Similarity threshold (default: {RESONANCE_THRESHOLD})",
    )
    p_discover.set_defaults(func=cmd_discover)

    p_today = subparsers.add_parser(
        "today",
        help="Display today's resonances",
    )
    p_today.set_defaults(func=cmd_today)

    p_for = subparsers.add_parser(
        "for",
        help="Find resonances for a specific file",
    )
    p_for.add_argument(
        "filepath",
        help="Relative path from /claude-home/ (e.g. thoughts/2026-03-17-morning.md)",
    )
    p_for.add_argument(
        "--threshold",
        type=float,
        default=RESONANCE_THRESHOLD,
        help=f"Similarity threshold (default: {RESONANCE_THRESHOLD})",
    )
    p_for.add_argument(
        "--exclude-self",
        action="store_true",
        default=False,
        help="Exclude matches from the same file",
    )
    p_for.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of results (default: 10)",
    )
    p_for.set_defaults(func=cmd_for)

    p_passage = subparsers.add_parser(
        "passage",
        help="Find resonances for arbitrary text",
    )
    p_passage.add_argument(
        "text",
        help="Text passage to find resonances for",
    )
    p_passage.add_argument(
        "--threshold",
        type=float,
        default=RESONANCE_THRESHOLD,
        help=f"Similarity threshold (default: {RESONANCE_THRESHOLD})",
    )
    p_passage.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of results (default: 10)",
    )
    p_passage.set_defaults(func=cmd_passage)

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
