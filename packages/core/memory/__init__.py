"""NexusDev Memory System - Contextual Awareness & Knowledge Accumulation.

Memory Types:
- Working: Current session context (short-term)
- Episodic: Agent interaction history (event-based)
- Semantic: Knowledge base (facts, patterns)
- Procedural: SOP patterns and workflows

Retrieval:
- Vector: Semantic similarity search
- Graph: Relationship-based navigation
"""

from core.memory.manager import MemoryManager, get_memory_manager
from core.memory.types import (
    AgentMemoryProfile,
    MemoryEntry,
    MemoryQuery,
    MemoryScope,
    MemoryType,
)

__all__ = [
    "MemoryType",
    "MemoryScope",
    "MemoryEntry",
    "AgentMemoryProfile",
    "MemoryQuery",
    "MemoryManager",
    "get_memory_manager",
]
