"""Memory Manager - Unified entry point for NexusDev memory system.

The MemoryManager provides a single interface for all memory operations:
- Store and retrieve memories
- Query across memory types
- Manage memory lifecycle
- Handle agent-specific memory profiles
"""

from typing import Any
from uuid import UUID

from core.memory.types import (
    MemoryEntry,
    MemoryQuery,
    MemoryType,
    MemoryScope,
    AgentMemoryProfile,
)
from core.memory.stores.working import WorkingMemoryStore
from core.memory.stores.episodic import EpisodicMemoryStore
from core.memory.stores.semantic import SemanticMemoryStore
from core.memory.stores.procedural import ProceduralMemoryStore
from core.memory.retrieval.vector import VectorStore, SimpleVectorStore
from core.memory.retrieval.graph import GraphStore, SimpleGraphStore
from core.memory.compression import MemoryCompressor, MemoryPruner


class MemoryManager:
    """Unified memory manager for NexusDev.
    
    Provides:
    - Multi-type memory storage (working, episodic, semantic, procedural)
    - Vector and graph-based retrieval
    - Memory compression and pruning
    - Agent-specific memory profiles
    """
    
    def __init__(
        self,
        database: "Database | None" = None,
        vector_store: VectorStore | None = None,
        graph_store: GraphStore | None = None,
    ):
        """Initialize memory manager.
        
        Args:
            database: Database for persistence
            vector_store: Vector store for embeddings
            graph_store: Graph store for relationships
        """
        self.database = database

        # Initialize retrieval backends first
        self.vector_store = vector_store or SimpleVectorStore()
        self.graph_store = graph_store or SimpleGraphStore()
        
        # Initialize stores
        self.working = WorkingMemoryStore(capacity=50)
        self.episodic = EpisodicMemoryStore(database)
        self.semantic = SemanticMemoryStore(database, self.vector_store)
        self.procedural = ProceduralMemoryStore(database)
        
        # Initialize compression
        self.compressor = MemoryCompressor()
        self.pruner = MemoryPruner()
        
        # Agent profiles cache
        self._agent_profiles: dict[str, AgentMemoryProfile] = {}
    
    # ============ Core Operations ============
    
    async def remember(
        self,
        content: str,
        agent_name: str,
        memory_type: MemoryType,
        scope: MemoryScope = MemoryScope.SESSION,
        session_id: UUID | None = None,
        stage_id: UUID | None = None,
        project_id: str | None = None,
        tags: list[str] | None = None,
        importance: float = 0.5,
        metadata: dict | None = None,
    ) -> MemoryEntry:
        """Store a memory.
        
        Args:
            content: Memory content
            agent_name: Agent that created this memory
            memory_type: Type of memory
            scope: Visibility scope
            session_id: Associated session
            stage_id: Associated stage
            project_id: Associated project
            tags: Searchable tags
            importance: Importance score (0-1)
            metadata: Additional metadata
            
        Returns:
            Created memory entry
        """
        entry = MemoryEntry(
            type=memory_type,
            scope=scope,
            session_id=session_id,
            stage_id=stage_id,
            project_id=project_id,
            agent_name=agent_name,
            content=content,
            tags=tags or [],
            importance=importance,
            metadata=metadata or {},
        )
        
        # Store in appropriate store
        if memory_type == MemoryType.WORKING:
            await self.working.add(entry)
        elif memory_type == MemoryType.EPISODIC:
            await self.episodic.add(entry)
        elif memory_type == MemoryType.SEMANTIC:
            await self.semantic.add(entry)
        elif memory_type == MemoryType.PROCEDURAL:
            await self.procedural.add(entry)
        
        return entry
    
    async def recall(
        self,
        query: str = "",
        agent_name: str | None = None,
        memory_types: list[MemoryType] | None = None,
        session_id: UUID | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Recall memories matching query.
        
        Args:
            query: Search query
            agent_name: Filter by agent
            memory_types: Filter by memory types
            session_id: Filter by session
            limit: Maximum results
            
        Returns:
            Matching memories
        """
        memory_query = MemoryQuery(
            query=query,
            agent_name=agent_name,
            memory_types=memory_types,
            session_id=session_id,
            limit=limit,
        )
        
        results = []
        
        # Query each memory type
        types_to_query = memory_types or list(MemoryType)
        
        for mem_type in types_to_query:
            memory_query.memory_types = [mem_type]
            
            if mem_type == MemoryType.WORKING:
                entries = await self.working.query(memory_query)
                results.extend(entries)
            elif mem_type == MemoryType.EPISODIC:
                entries = await self.episodic.query(memory_query)
                results.extend(entries)
            elif mem_type == MemoryType.SEMANTIC:
                entries_with_scores = await self.semantic.query(memory_query)
                results.extend([e for e, _ in entries_with_scores])
            elif mem_type == MemoryType.PROCEDURAL:
                # Procedural memories are retrieved by name
                pass
        
        # Sort by importance and recency
        results.sort(key=lambda e: (e.importance, e.created_at), reverse=True)
        
        return results[:limit]
    
    async def get_context(
        self,
        session_id: UUID,
        agent_name: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Get working context for an agent in a session.
        
        Args:
            session_id: Session ID
            agent_name: Agent name
            limit: Maximum context items
            
        Returns:
            Context memories
        """
        return await self.working.get_session_context(session_id, agent_name, limit)
    
    async def get_agent_profile(self, agent_name: str) -> AgentMemoryProfile:
        """Get memory profile for an agent.
        
        Args:
            agent_name: Agent name
            
        Returns:
            Agent memory profile
        """
        if agent_name not in self._agent_profiles:
            self._agent_profiles[agent_name] = AgentMemoryProfile.for_agent(agent_name)
        
        return self._agent_profiles[agent_name]
    
    # ============ Agent-Specific Operations ============
    
    async def get_agent_input_memories(
        self,
        agent_name: str,
        session_id: UUID,
    ) -> dict[MemoryType, list[MemoryEntry]]:
        """Get input memories for an agent.
        
        Args:
            agent_name: Agent name
            session_id: Session ID
            
        Returns:
            Dict of memory type -> entries
        """
        profile = await self.get_agent_profile(agent_name)
        
        result = {}
        
        for mem_type in profile.input_memory_types:
            query = MemoryQuery(
                session_id=session_id,
                memory_types=[mem_type],
                limit=profile.working_memory_capacity,
            )
            
            if mem_type == MemoryType.WORKING:
                result[mem_type] = await self.working.query(query)
            elif mem_type == MemoryType.EPISODIC:
                result[mem_type] = await self.episodic.query(query)
            elif mem_type == MemoryType.SEMANTIC:
                entries = await self.semantic.query(query)
                result[mem_type] = [e for e, _ in entries]
        
        return result
    
    async def store_agent_output(
        self,
        agent_name: str,
        content: str,
        session_id: UUID,
        stage_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> list[MemoryEntry]:
        """Store agent output to appropriate memory types.
        
        Args:
            agent_name: Agent name
            content: Output content
            session_id: Session ID
            stage_id: Stage ID
            metadata: Additional metadata
            
        Returns:
            Created memory entries
        """
        profile = await self.get_agent_profile(agent_name)
        
        entries = []
        
        for mem_type in profile.output_memory_types:
            entry = await self.remember(
                content=content,
                agent_name=agent_name,
                memory_type=mem_type,
                session_id=session_id,
                stage_id=stage_id,
                metadata=metadata,
            )
            entries.append(entry)
        
        return entries
    
    # ============ Semantic Search ============
    
    async def find_similar_memories(
        self,
        content: str,
        scope: MemoryScope | None = None,
        limit: int = 5,
    ) -> list[tuple[MemoryEntry, float]]:
        """Find memories similar to given content.
        
        Args:
            content: Content to compare
            scope: Optional scope filter
            limit: Maximum results
            
        Returns:
            List of (entry, similarity) tuples
        """
        return await self.semantic.find_similar(content, scope, limit)
    
    async def get_patterns(
        self,
        pattern_type: str,
        project_id: str | None = None,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Get stored patterns.
        
        Args:
            pattern_type: Type of pattern
            project_id: Optional project filter
            limit: Maximum results
            
        Returns:
            Pattern entries
        """
        return await self.semantic.get_patterns(pattern_type, project_id, limit)
    
    # ============ Graph Operations ============
    
    async def add_code_dependency(
        self,
        source_file: str,
        target_file: str,
        dep_type: str = "imports",
    ) -> None:
        """Add code dependency to graph.
        
        Args:
            source_file: Source file ID
            target_file: Target file ID
            dep_type: Dependency type (imports, calls, inherits)
        """
        from core.memory.retrieval.graph import GraphNode, GraphEdge
        
        # Add nodes
        await self.graph_store.add_node(GraphNode(
            id=source_file,
            label=source_file,
            type="file",
        ))
        await self.graph_store.add_node(GraphNode(
            id=target_file,
            label=target_file,
            type="file",
        ))
        
        # Add edge
        await self.graph_store.add_edge(GraphEdge(
            source=source_file,
            target=target_file,
            type=dep_type,
        ))
    
    async def get_code_dependencies(
        self,
        file_id: str,
    ) -> dict[str, list[str]]:
        """Get code dependencies for a file.
        
        Args:
            file_id: File ID
            
        Returns:
            Dict of {dependency_type: [file_ids]}
        """
        return await self.graph_store.get_code_dependencies(file_id)
    
    # ============ Lifecycle Management ============
    
    async def compress_old_memories(
        self,
        session_id: UUID | None = None,
    ) -> int:
        """Compress old memories.
        
        Args:
            session_id: Optional session filter
            
        Returns:
            Number of memories compressed
        """
        # Get all working memories for session
        if session_id:
            entries = await self.working.query(MemoryQuery(
                session_id=session_id,
                limit=1000,
            ))
        else:
            entries = []
        
        compressed = 0
        for entry in entries:
            if await self.compressor.should_compress(entry):
                result = await self.compressor.compress(entry)
                entry.summary = result.compressed_summary
                compressed += 1
        
        return compressed
    
    async def clear_session(self, session_id: UUID) -> int:
        """Clear all memories for a session.
        
        Args:
            session_id: Session ID
            
        Returns:
            Number of memories cleared
        """
        count = await self.working.clear_session(session_id)
        return count
    
    async def get_stats(self) -> dict[str, Any]:
        """Get memory system statistics."""
        return {
            "working": await self.working.get_stats(),
            "vector": await self.vector_store.get_stats() if self.vector_store else None,
            "graph": await self.graph_store.get_stats() if self.graph_store else None,
        }


# Global memory manager instance
_memory_manager: MemoryManager | None = None


def get_memory_manager(
    database: "Database | None" = None,
    vector_store: VectorStore | None = None,
    graph_store: GraphStore | None = None,
) -> MemoryManager:
    """Get or create global memory manager.
    
    Args:
        database: Database for persistence
        vector_store: Vector store for embeddings
        graph_store: Graph store for relationships
        
    Returns:
        MemoryManager instance
    """
    global _memory_manager
    
    if _memory_manager is None:
        _memory_manager = MemoryManager(database, vector_store, graph_store)
    
    return _memory_manager
