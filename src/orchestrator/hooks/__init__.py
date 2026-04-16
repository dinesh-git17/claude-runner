"""Post-session hooks — registered and executed by the pipeline."""

# isort: skip_file
from __future__ import annotations

from orchestrator.hooks import (
    compile_memory,
    conversation,
    drift,
    echoes,
    git,
    graph_update,
    memory_index,
    mirror as mirror_hook,
    mood,
    resonance,
    snapshot,
    thoughts,
    transcript,
    visitors_archive,
)
from orchestrator.pipeline import Hook


def build_pipeline() -> list[Hook]:
    """Return all hooks with dependency declarations.

    Dependency graph:
        transcript ─────────────┐
        thoughts ───────────────┤
        mood ───────────────────┤ (group 1: parallel, no deps)
        conversation ───────────┤
        snapshot (revalidation) ┤
        visitors_archive ───────┤
                                │
                                ├─→ memory_index ─┬─→ compile_memory
                                │                 ├─→ graph_update
                                │                 ├─→ resonance ──┐
                                │                 ├─→ drift ──────┼─→ echoes
                                │                 └─→ mirror_snapshot
                                └─→ revalidation
                                                              │
                                              git ◄───────────┘
    """
    return [
        Hook("transcript", [], transcript.run),
        Hook("thoughts", [], thoughts.run),
        Hook("mood", [], mood.run),
        Hook("conversation", [], conversation.run),
        Hook("revalidation", [], snapshot.run),
        Hook("visitors_archive", [], visitors_archive.run),
        Hook("memory_index", ["thoughts"], memory_index.run),
        Hook("compile_memory", ["memory_index"], compile_memory.run),
        Hook("graph_update", ["memory_index"], graph_update.run),
        Hook("resonance", ["memory_index"], resonance.run),
        Hook("drift", ["memory_index"], drift.run),
        Hook("mirror_snapshot", ["memory_index"], mirror_hook.run),
        Hook("echoes", ["resonance", "drift"], echoes.run),
        Hook("git", ["revalidation", "echoes"], git.run),
    ]
