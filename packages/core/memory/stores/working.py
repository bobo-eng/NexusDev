"""Working Memory Store - Short-term context for current session.

Working memory holds the immediate context that agents need to perform
their current task. It's limited in capacity and time.

Key characteristics:
- Session-scoped only
- Limited capacity (configurable, default 10-30 entries)
- Fast access (in-memory)
- Auto-eviction when full (LRU or importance-based)
"""

from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from core.memory.types import MemoryEntry, MemoryQuery, MemoryType, MemoryScope


class WorkingMemoryStore:
    """In-memory store for working memory.
    
    Uses OrderedDict for LRU eviction and fast access.
    """
    
    def __init__(self, capacity: int = 30):
        """Initialize working memory store.
        
        Args:
            capacity: Maximum number of entries to keep
        """
        self.capacity = capacity
        self._entries: OrderedDict[UUID, MemoryEntry] = OrderedDict()
        self._session_index: dict[UUID, set[UUID]] = {}  # session_id -> entry_ids
    
    async def add(self, entry: MemoryEntry) -> MemoryEntry:
        """Add entry to working memory.
        
        If at capacity, evicts least recently used entry.
        
        Args:
            entry: Memory entry to add
            
        Returns:
            Added entry
        """
        # Ensure it's session-scoped
        entry.scope = MemoryScope.SESSION
        entry.type = MemoryType.WORKING
        
        # Evict if at capacity
        while len(self._entries) >= self.capacity:
            self._evict_lru()
        
        # Add to storage
        self._entries[entry.id] = entry
        self._entries.move_to_end(entry.id)  # Mark as recently used
        
        # Index by session
        if entry.session_id:
            if entry.session_id not in self._session_index:
                self._session_index[entry.session_id] = set()
            self._session_index[entry.session_id].add(entry.id)
        
        return entry
    
    async def get(self, entry_id: UUID) -> MemoryEntry | None:
        """Get entry by ID.
        
        Args:
            entry_id: Entry ID
            
        Returns:
            Entry or None if not found
        """
        entry = self._entries.get(entry_id)
        if entry:
            entry.touch()
            self._entries.move_to_end(entry_id)  # Mark as recently used
        return entry
    
    async def query(self, query: MemoryQuery) -> list[MemoryEntry]:
        """Query working memory.
        
        Args:
            query: Query parameters
            
        Returns:
            Matching entries
        """
        results = []
        
        for entry in self._entries.values():
            # Filter by session
            if query.session_id and entry.session_id != query.session_id:
                continue
            
            # Filter by agent
            if query.agent_name and entry.agent_name != query.agent_name:
                continue
            
            # Filter by stage
            if query.stage_id and entry.stage_id != query.stage_id:
                continue
            
            # Filter by tags
            if query.tags and not any(t in entry.tags for t in query.tags):
                continue
            
            # Filter by importance
            if entry.importance < query.min_importance:
                continue
            
            # Filter by confidence
            if entry.confidence < query.min_confidence:
                continue
            
            # Text search (simple substring match for working memory)
            if query.query and query.query.lower() not in entry.content.lower():
                continue
            
            results.append(entry)
        
        # Sort
        if query.order_by == "recency":
            results.sort(key=lambda e: e.created_at, reverse=True)
        elif query.order_by == "importance":
            results.sort(key=lambda e: e.importance, reverse=True)
        elif query.order_by == "access_count":
            results.sort(key=lambda e: e.access_count, reverse=True)
        else:  # relevance - use access recency
            results.sort(key=lambda e: e.accessed_at or e.created_at, reverse=True)
        
        # Apply limit
        return results[query.offset:query.offset + query.limit]
    
    async def update(self, entry: MemoryEntry) -> MemoryEntry | None:
        """Update an entry.
        
        Args:
            entry: Entry to update
            
        Returns:
            Updated entry or None
        """
        if entry.id not in self._entries:
            return None
        
        entry.updated_at = datetime.utcnow()
        self._entries[entry.id] = entry
        self._entries.move_to_end(entry.id)
        
        return entry
    
    async def delete(self, entry_id: UUID) -> bool:
        """Delete an entry.
        
        Args:
            entry_id: Entry ID to delete
            
        Returns:
            True if deleted
        """
        entry = self._entries.pop(entry_id, None)
        if entry and entry.session_id:
            self._session_index.get(entry.session_id, set()).discard(entry_id)
        return entry is not None
    
    async def clear_session(self, session_id: UUID) -> int:
        """Clear all entries for a session.
        
        Args:
            session_id: Session ID
            
        Returns:
            Number of entries cleared
        """
        entry_ids = self._session_index.get(session_id, set()).copy()
        count = 0
        
        for entry_id in entry_ids:
            if await self.delete(entry_id):
                count += 1
        
        self._session_index.pop(session_id, None)
        return count
    
    async def get_session_context(
        self,
        session_id: UUID,
        agent_name: str | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Get recent context for a session.
        
        Args:
            session_id: Session ID
            agent_name: Optional agent filter
            limit: Maximum entries
            
        Returns:
            Recent context entries
        """
        query = MemoryQuery(
            session_id=session_id,
            agent_name=agent_name,
            limit=limit,
            order_by="recency",
        )
        return await self.query(query)
    
    async def get_shared_context(
        self,
        session_id: UUID,
        agent_names: list[str],
    ) -> dict[str, list[MemoryEntry]]:
        """Get context shared between agents.
        
        Args:
            session_id: Session ID
            agent_names: List of agent names
            
        Returns:
            Dict of agent_name -> entries
        """
        result = {}
        
        for agent_name in agent_names:
            entries = await self.get_session_context(session_id, agent_name)
            result[agent_name] = entries
        
        return result
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._entries:
            return
        
        # Get oldest entry
        oldest_id, oldest_entry = self._entries.popitem(last=False)
        
        # Update index
        if oldest_entry.session_id:
            self._session_index.get(oldest_entry.session_id, set()).discard(oldest_id)
    
    async def get_stats(self) -> dict[str, Any]:
        """Get store statistics."""
        return {
            "total_entries": len(self._entries),
            "capacity": self.capacity,
            "utilization": len(self._entries) / self.capacity if self.capacity > 0 else 0,
            "session_count": len(self._session_index),
        }
