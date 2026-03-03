"""Semantic Memory Store - Knowledge base and patterns."""

from datetime import datetime
from typing import Any
from uuid import UUID

from core.memory.types import MemoryEntry, MemoryQuery, MemoryType, MemoryScope


class SemanticMemoryStore:
    """Store for semantic memory (knowledge base)."""
    
    def __init__(self, database: "Database | None" = None, vector_store: "VectorStore | None" = None):
        self.database = database
        self.vector_store = vector_store
    
    async def add(self, entry: MemoryEntry) -> MemoryEntry:
        """Add semantic memory entry."""
        entry.type = MemoryType.SEMANTIC
        
        if not entry.embedding and self.vector_store:
            entry.embedding = await self.vector_store.embed(entry.content)
        
        if self.database:
            async with self.database.session() as db_session:
                from core.memory.storage import MemoryRepository
                repo = MemoryRepository(db_session)
                await repo.create(entry)
        
        if self.vector_store and entry.embedding:
            await self.vector_store.index(entry.id, entry.embedding, {
                "type": entry.type.value,
                "scope": entry.scope.value,
                "agent": entry.agent_name,
                "tags": entry.tags,
            })
        
        return entry
    
    async def get(self, entry_id: UUID) -> MemoryEntry | None:
        """Get entry by ID."""
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
    
    async def query(self, query: MemoryQuery) -> list[tuple[MemoryEntry, float]]:
        """Query semantic memory with similarity search."""
        results = []
        
        if self.vector_store and query.embedding:
            vector_results = await self.vector_store.search(
                query.embedding, top_k=query.limit, filters={"type": MemoryType.SEMANTIC.value}
            )
            for entry_id, score in vector_results:
                entry = await self.get(entry_id)
                if entry:
                    results.append((entry, score))
        elif self.database:
            async with self.database.session() as db_session:
                from core.memory.storage import MemoryRepository
                repo = MemoryRepository(db_session)
                filters = {"type": MemoryType.SEMANTIC.value}
                if query.project_id:
                    filters["project_id"] = query.project_id
                entries = await repo.query(filters=filters, limit=query.limit)
                for entry in entries:
                    score = 0.0
                    if query.query and query.query.lower() in entry.content.lower():
                        score = 0.5
                    results.append((entry, score))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:query.limit]
    
    async def find_similar(self, content: str, scope: MemoryScope | None = None, limit: int = 5) -> list[tuple[MemoryEntry, float]]:
        """Find memories similar to given content."""
        if not self.vector_store:
            return []
        embedding = await self.vector_store.embed(content)
        query = MemoryQuery(embedding=embedding, scopes=[scope] if scope else None, limit=limit)
        return await self.query(query)
    
    async def get_patterns(self, pattern_type: str, project_id: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        """Get stored patterns of a specific type."""
        query = MemoryQuery(project_id=project_id, tags=["pattern", pattern_type], limit=limit, order_by="importance")
        results = await self.query(query)
        return [entry for entry, _ in results]
    
    async def add_pattern(self, name: str, description: str, examples: list[str], agent_name: str,
                          project_id: str | None = None, importance: float = 0.7) -> MemoryEntry:
        """Add a new pattern to semantic memory."""
        content = f"# {name}\n\n{description}\n\n## Examples\n"
        for i, example in enumerate(examples, 1):
            content += f"\n### Example {i}\n{example}\n"
        
        entry = MemoryEntry(
            type=MemoryType.SEMANTIC,
            scope=MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL,
            project_id=project_id,
            agent_name=agent_name,
            content=content,
            summary=f"Pattern: {name}",
            tags=["pattern", name.lower().replace(" ", "_")],
            importance=importance,
            metadata={"pattern_name": name, "example_count": len(examples)},
        )
        return await self.add(entry)
