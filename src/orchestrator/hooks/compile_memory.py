"""Hook: compile memory context using Haiku for the next session.

Reads all memory/*.md files (except identity.md), sends them to Haiku
for compilation into a dense context document, and writes the result
to data/compiled-memory.md for injection into the next system prompt.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import structlog

from orchestrator.config import CLAUDE_HOME, DATA_DIR, ENV_FILE, SessionResult
from orchestrator.pipeline import HookResult

logger = structlog.get_logger()

COMPILED_MEMORY_FILE = DATA_DIR / "compiled-memory.md"
COMPILE_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "compile_memory_prompt.md"
MEMORY_DIR = CLAUDE_HOME / "memory"
TOKEN_BUDGET = 8000
CHAR_BUDGET = TOKEN_BUDGET * 4
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SKIP_FILES = frozenset({"identity.md", "README.md"})


def _load_api_key() -> str:
    """Read ANTHROPIC_API_KEY from the .env file."""
    if not ENV_FILE.exists():
        raise RuntimeError(f".env not found at {ENV_FILE}")
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("ANTHROPIC_API_KEY"):
            _, _, value = line.partition("=")
            return value.strip().strip("'\"")
    raise RuntimeError("ANTHROPIC_API_KEY not found in .env")


def _compile_sync() -> str:
    """Run the Haiku compilation synchronously.

    Returns:
        The compiled memory text.

    Raises:
        RuntimeError: If compilation fails.
    """
    import anthropic

    if not COMPILE_PROMPT_FILE.exists():
        raise RuntimeError(f"Compilation prompt not found at {COMPILE_PROMPT_FILE}")

    memory_files = sorted(MEMORY_DIR.glob("*.md"))
    memory_files = [f for f in memory_files if f.name not in SKIP_FILES]

    if not memory_files:
        raise RuntimeError("No memory files to compile")

    file_sections: list[str] = []
    for f in memory_files:
        content = f.read_text(encoding="utf-8")
        file_sections.append(f"=== {f.name} ({len(content)} chars) ===\n{content}")

    user_message = (
        f"Compile these {len(file_sections)} memory files into a single context "
        f"document under {TOKEN_BUDGET} tokens (~{CHAR_BUDGET} characters).\n\n"
        + "\n\n".join(file_sections)
    )

    system_prompt = COMPILE_PROMPT_FILE.read_text(encoding="utf-8")
    api_key = _load_api_key()

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=TOKEN_BUDGET,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    compiled_text = ""
    for block in response.content:
        if block.type == "text":
            compiled_text += block.text

    if not compiled_text.strip():
        raise RuntimeError("Haiku returned empty compilation")

    return compiled_text


async def run(result: SessionResult) -> HookResult:
    """Compile memory files via Haiku into a condensed context document."""
    start = time.monotonic()

    try:
        compiled_text = await asyncio.to_thread(_compile_sync)
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.error("compile_memory_failed", error=str(exc))
        return HookResult("compile_memory", "failed", elapsed, str(exc))

    if len(compiled_text) > CHAR_BUDGET * 1.2:
        logger.warning(
            "compiled_memory_over_budget",
            chars=len(compiled_text),
            budget=CHAR_BUDGET,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COMPILED_MEMORY_FILE.write_text(compiled_text, encoding="utf-8")

    elapsed = int((time.monotonic() - start) * 1000)
    logger.info(
        "compile_memory_success",
        chars=len(compiled_text),
        duration_ms=elapsed,
    )
    return HookResult("compile_memory", "success", elapsed)
