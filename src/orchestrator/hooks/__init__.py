"""Post-session hooks — registered and executed by the pipeline."""

from __future__ import annotations

from orchestrator.hooks import (
    conversation,
    echoes,
    git,
    memory_index,
    mood,
    resonance,
    snapshot,
    thoughts,
    transcript,
)
from orchestrator.pipeline import Hook


def build_pipeline() -> list[Hook]:
    """Return all hooks with dependency declarations.

    Dependency graph:
        transcript ─────────────┐
        thoughts ───────────────┤
        mood ───────────────────┤ (group 1: parallel)
        conversation ───────────┤
        snapshot (revalidation) ┤
                                ├─→ memory_index ─→ resonance ─→ echoes
                                └─→ revalidation (in snapshot.run)
                                                                   │
                                                    git ◄──────────┘
    """
    return [
        Hook("transcript", [], transcript.run),
        Hook("thoughts", [], thoughts.run),
        Hook("mood", [], mood.run),
        Hook("conversation", [], conversation.run),
        Hook("revalidation", [], snapshot.run),
        Hook("memory_index", ["thoughts"], memory_index.run),
        Hook("resonance", ["memory_index"], resonance.run),
        Hook("echoes", ["resonance"], echoes.run),
        Hook("git", ["revalidation", "echoes"], git.run),
    ]
