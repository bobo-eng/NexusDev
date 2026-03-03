"""Episodic Memory Store - Agent interaction history.

Episodic memory records the sequence of events and interactions between
agents. It provides temporal context and enables learning from past
experiences.

Key characteristics:
- Event-based storage
- Temporal ordering
- Supports replay and analysis
- Human feedback integration
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from core.memory.types import MemoryEntry, MemoryQuery, MemoryType


class EpisodicMemoryStore:
    """Store for episodic memory (event history).
    
    Persists to database for durability.
    """
    
    def __init__(self, database: "Database | None" = None):
        """Initialize episodic memory store.
        
        Args:
            database: Database for persistence
        """
        self.database = database
    
    async def add(self, entry: MemoryEntry) -> MemoryEntry:
        """Add episodic memory entry.
        
        Args:
            entry: Memory entry
            
        Returns:
            Added entry
        """
        entry.type = MemoryType.EPISODIC
        
        # Persist to database if available
        if self.database:
            async with self.database.session() as db_session:
                from core.memory.storage import MemoryRepository
                repo = MemoryRepository(db_session)
                await repo.create(entry)
        
        return entry
    
    async def get(self, entry_id: UUID) -> MemoryEntry | None:
        """Get entry by ID.
        
        Args:
            entry_id: Entry ID
            
        Returns:
            Entry or None
        """
        if not self.database:
            return None
        
        async with self.database.session() as db_session:
            from core.memory.storage import MemoryRepository
            repo = MemoryRepository(db_session)
            entry = await repo.get_by_id(entry_id)
            if entry:
                entry.touch()
                await repo.update(entry)
            return entry
    
    async def query(self, query: MemoryQuery) -> list[MemoryEntry]:
        """Query episodic memory.
        
        Args:
            query: Query parameters
            
        Returns:
            Matching entries
        """
        if not self.database:
            return []
        
        async with self.database.session() as db_session:
            from core.memory.storage import MemoryRepository
            repo = MemoryRepository(db_session)
            
            # Build query filters
            filters = {"type": MemoryType.EPISODIC.value}
            
            if query.session_id:
                filters["session_id"] = query.session_id
            if query.agent_name:
                filters["agent_name"] = query.agent_name
            if query.stage_id:
                filters["stage_id"] = query.stage_id
            if query.project_id:
                filters["project_id"] = query.project_id
            
            entries = await repo.query(
                filters=filters,
                limit=query.limit,
                offset=query.offset,
                order_by=query.order_by,
            )
            
            # Post-filter for text search
            if query.query:
                entries = [
                    e for e in entries
                    if query.query.lower() in e.content.lower()
                    or query.query.lower() in e.summary.lower()
                ]
            
            return entries
    
    async def get_session_history(
        self,
        session_id: UUID,
        agent_name: str | None = None,
    ) -> list[MemoryEntry]:
        """Get complete event history for a session.
        
        Args:
            session_id: Session ID
            agent_name: Optional agent filter
            
        Returns:
            Chronological event list
        """
        query = MemoryQuery(
            session_id=session_id,
            agent_name=agent_name,
            limit=1000,
            order_by="recency",
        )
        entries = await self.query(query)
        entries.reverse()  # Oldest first
        return entries
    
    async def get_agent_interactions(
        self,
        session_id: UUID,
        from_agent: str,
        to_agent: str,
    ) -> list[MemoryEntry]:
        """Get interactions between two agents.
        
        Args:
            session_id: Session ID
            from_agent: Source agent
            to_agent: Target agent
            
        Returns:
            Interaction events
        """
        # Get all entries for session
        entries = await self.get_session_history(session_id)
        
        # Filter for interactions
        interactions = []
        for entry in entries:
            if entry.agent_name == from_agent:
                # Check if this entry references to_agent
                if to_agent in entry.content or to_agent in entry.tags:
                    interactions.append(entry)
        
        return interactions
    
    async def get_decision_rationale(
        self,
        session_id: UUID,
        stage_id: UUID,
    ) -> MemoryEntry | None:
        """Get the rationale for a design decision.
        
        Args:
            session_id: Session ID
            stage_id: Stage ID
            
        Returns:
            Decision entry or None
        """
        query = MemoryQuery(
            session_id=session_id,
            stage_id=stage_id,
            tags=["decision", "rationale"],
            limit=1,
        )
        entries = await self.query(query)
        return entries[0] if entries else None
    
    async def add_feedback(
        self,
        entry_id: UUID,
        positive: bool,
        notes: str = "",
    ) -> MemoryEntry | None:
        """Add human feedback to an episodic memory.
        
        Args:
            entry_id: Entry ID
            positive: Whether feedback is positive
            notes: Feedback notes
            
        Returns:
            Updated entry or None
        """
        entry = await self.get(entry_id)
        if not entry:
            return None
        
        entry.add_feedback(positive, notes)
        
        if self.database:
            async with self.database.session() as db_session:
                from core.memory.storage import MemoryRepository
                repo = MemoryRepository(db_session)
                await repo.update(entry)
        
        return entry
    
    async def get_feedback_stats(
        self,
        session_id: UUID | None = None,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Get feedback statistics.
        
        Args:
            session_id: Optional session filter
            agent_name: Optional agent filter
            
        Returns:
            Feedback stats
        """
        query = MemoryQuery(
            session_id=session_id,
            agent_name=agent_name,
            only_with_feedback=True,
            limit=10000,
        )
        entries = await self.query(query)
        
        positive = sum(1 for e in entries if e.feedback_positive)
        negative = sum(1 for e in entries if e.feedback_positive is False)
        
        return {
            "total_with_feedback": len(entries),
            "positive": positive,
            "negative": negative,
            "positive_rate": positive / len(entries) if entries else 0,
        }
    
    async def replay_session(
        self,
        session_id: UUID,
    ) -> list[dict[str, Any]]:
        """Replay a session's event history.
        
        Args:
            session_id: Session ID
            
        Returns:
            Replay events with context
        """
        entries = await self.get_session_history(session_id)
        
        replay = []
        for entry in entries:
            replay.append({
                "timestamp": entry.created_at.isoformat(),
                "agent": entry.agent_name,
                "stage": entry.stage_id,
                "action": entry.metadata.get("action", "unknown"),
                "content_summary": entry.summary or entry.content[:200],
                "importance": entry.importance,
                "feedback": entry.feedback_positive,
            })
        
        return replay
