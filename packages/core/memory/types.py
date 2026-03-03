"""Memory type definitions for NexusDev.

Defines:
- MemoryType: Categories of memory (working, episodic, semantic, procedural)
- MemoryScope: Isolation levels (session, project, global)
- MemoryEntry: Individual memory record
- AgentMemoryProfile: Per-agent memory configuration
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class MemoryType(str, Enum):
    """Types of memory in the system."""

    # Working memory - current session context (short-term)
    WORKING = "working"

    # Episodic memory - agent interaction history (event-based)
    EPISODIC = "episodic"

    # Semantic memory - knowledge base (facts, patterns)
    SEMANTIC = "semantic"

    # Procedural memory - SOP patterns and workflows
    PROCEDURAL = "procedural"


class MemoryScope(str, Enum):
    """Scope levels for memory isolation."""

    # Session-level: Only visible within current session
    SESSION = "session"

    # Project-level: Shared across sessions in same project
    PROJECT = "project"

    # Global-level: System-wide knowledge
    GLOBAL = "global"


class MemoryEntry(BaseModel):
    """A single memory entry.

    Attributes:
        id: Unique identifier
        type: Memory category
        scope: Visibility scope
        session_id: Associated session (if session-scoped)
        project_id: Associated project (if project-scoped)
        agent_name: Agent that created/owns this memory
        content: The actual memory content
        metadata: Additional context (timestamps, importance, etc.)
        embedding: Vector embedding for semantic search
        tags: Searchable tags
        created_at: Creation timestamp
        accessed_at: Last access timestamp
        access_count: Number of times accessed
        importance: Importance score (0-1)
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    type: MemoryType
    scope: MemoryScope = MemoryScope.SESSION

    # Context
    session_id: UUID | None = None
    project_id: str | None = None
    agent_name: str
    stage_id: UUID | None = None

    # Content
    content: str
    content_type: str = "text/plain"  # text/plain, json, code, etc.
    summary: str = ""  # Compressed summary for quick retrieval

    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float] | None = None
    tags: list[str] = Field(default_factory=list)

    # Lifecycle
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    accessed_at: datetime | None = None
    access_count: int = 0

    # Quality
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # Human feedback
    feedback_positive: bool | None = None
    feedback_notes: str = ""

    def touch(self) -> "MemoryEntry":
        """Update access statistics."""
        self.accessed_at = datetime.utcnow()
        self.access_count += 1
        return self

    def update_importance(self, delta: float) -> "MemoryEntry":
        """Adjust importance score."""
        self.importance = max(0.0, min(1.0, self.importance + delta))
        self.updated_at = datetime.utcnow()
        return self

    def add_feedback(self, positive: bool, notes: str = "") -> "MemoryEntry":
        """Add human feedback."""
        self.feedback_positive = positive
        self.feedback_notes = notes
        self.updated_at = datetime.utcnow()
        return self


class AgentMemoryProfile(BaseModel):
    """Memory configuration for a specific agent.

    Defines what each agent remembers and how it retrieves memories.
    """

    agent_name: str

    # Input memory types this agent uses
    input_memory_types: list[MemoryType] = Field(default_factory=list)

    # Output memory types this agent produces
    output_memory_types: list[MemoryType] = Field(default_factory=list)

    # Special memory requirements
    special_requirements: list[str] = Field(default_factory=list)

    # Retrieval configuration
    retrieval_config: dict[str, Any] = Field(default_factory=dict)

    # Working memory capacity (number of recent entries to keep)
    working_memory_capacity: int = 10

    # Whether to compress old memories
    enable_compression: bool = True

    # Compression threshold (compress memories older than this many hours)
    compression_threshold_hours: int = 24

    @classmethod
    def for_agent(cls, agent_name: str) -> "AgentMemoryProfile":
        """Get default memory profile for an agent."""
        profiles = {
            "pm_agent": cls(
                agent_name="pm_agent",
                input_memory_types=[MemoryType.WORKING, MemoryType.EPISODIC],
                output_memory_types=[MemoryType.EPISODIC, MemoryType.SEMANTIC],
                special_requirements=["requirement_history", "user_preferences"],
                working_memory_capacity=20,
            ),
            "architect_agent": cls(
                agent_name="architect_agent",
                input_memory_types=[MemoryType.WORKING, MemoryType.SEMANTIC],
                output_memory_types=[
                    MemoryType.EPISODIC,
                    MemoryType.SEMANTIC,
                    MemoryType.PROCEDURAL,
                ],
                special_requirements=["design_decisions", "tech_constraints"],
                working_memory_capacity=15,
            ),
            "coder_agent": cls(
                agent_name="coder_agent",
                input_memory_types=[MemoryType.WORKING, MemoryType.SEMANTIC, MemoryType.PROCEDURAL],
                output_memory_types=[MemoryType.EPISODIC],
                special_requirements=["code_dependencies", "coding_patterns"],
                working_memory_capacity=30,
            ),
            "reviewer_agent": cls(
                agent_name="reviewer_agent",
                input_memory_types=[MemoryType.WORKING, MemoryType.EPISODIC, MemoryType.SEMANTIC],
                output_memory_types=[MemoryType.EPISODIC, MemoryType.SEMANTIC],
                special_requirements=["common_error_patterns", "review_history"],
                working_memory_capacity=25,
            ),
            "tester_agent": cls(
                agent_name="tester_agent",
                input_memory_types=[MemoryType.WORKING, MemoryType.SEMANTIC, MemoryType.PROCEDURAL],
                output_memory_types=[MemoryType.EPISODIC, MemoryType.SEMANTIC],
                special_requirements=["boundary_cases", "test_patterns"],
                working_memory_capacity=20,
            ),
        }
        return profiles.get(agent_name, cls(agent_name=agent_name))


class MemoryQuery(BaseModel):
    """Query for memory retrieval."""

    # Search parameters
    query: str = ""  # Text query
    embedding: list[float] | None = None  # Vector query

    # Filters
    memory_types: list[MemoryType] | None = None
    scopes: list[MemoryScope] | None = None
    session_id: UUID | None = None
    project_id: str | None = None
    agent_name: str | None = None
    stage_id: UUID | None = None
    tags: list[str] | None = None

    # Time range
    created_after: datetime | None = None
    created_before: datetime | None = None

    # Quality filters
    min_importance: float = 0.0
    min_confidence: float = 0.0
    only_with_feedback: bool = False
    feedback_positive: bool | None = None

    # Retrieval options
    limit: int = 10
    offset: int = 0
    order_by: Literal["relevance", "recency", "importance", "access_count"] = "relevance"

    # Hybrid search weights
    vector_weight: float = 0.7
    keyword_weight: float = 0.3


class MemoryCompressionResult(BaseModel):
    """Result of memory compression."""

    original_entry: MemoryEntry
    compressed_summary: str
    compression_ratio: float
    preserved_keys: list[str]


class MemoryStats(BaseModel):
    """Statistics for memory system."""

    total_entries: int = 0
    by_type: dict[MemoryType, int] = Field(default_factory=dict)
    by_scope: dict[MemoryScope, int] = Field(default_factory=dict)
    by_agent: dict[str, int] = Field(default_factory=dict)

    avg_importance: float = 0.0
    avg_access_count: float = 0.0

    oldest_entry: datetime | None = None
    newest_entry: datetime | None = None
