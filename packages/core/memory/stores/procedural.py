"""Procedural Memory Store - SOP patterns and workflows.

Procedural memory stores reusable procedures, workflows, and patterns
that agents can follow. It includes:
- SOP definitions
- Workflow templates
- Common task procedures
"""

from typing import Any
from uuid import UUID

from core.memory.types import MemoryEntry, MemoryQuery, MemoryType, MemoryScope


class ProceduralMemoryStore:
    """Store for procedural memory (SOPs and workflows)."""
    
    def __init__(self, database: "Database | None" = None):
        self.database = database
        self._sop_cache: dict[str, dict] = {}  # name -> SOP definition
    
    async def add(self, entry: MemoryEntry) -> MemoryEntry:
        """Add procedural memory entry."""
        entry.type = MemoryType.PROCEDURAL
        
        if self.database:
            async with self.database.session() as db_session:
                from core.memory.storage import MemoryRepository
                repo = MemoryRepository(db_session)
                await repo.create(entry)
        
        # Cache SOP definitions
        if entry.metadata.get("sop_name"):
            self._sop_cache[entry.metadata["sop_name"]] = entry.metadata.get("sop_definition", {})
        
        return entry
    
    async def get(self, entry_id: UUID) -> MemoryEntry | None:
        """Get entry by ID."""
        if not self.database:
            return None
        
        async with self.database.session() as db_session:
            from core.memory.storage import MemoryRepository
            repo = MemoryRepository(db_session)
            return await repo.get_by_id(entry_id)
    
    async def get_sop(self, sop_name: str) -> dict | None:
        """Get SOP definition by name."""
        # Check cache first
        if sop_name in self._sop_cache:
            return self._sop_cache[sop_name]
        
        # Query from storage
        query = MemoryQuery(
            tags=["sop", sop_name],
            limit=1,
        )
        
        if self.database:
            async with self.database.session() as db_session:
                from core.memory.storage import MemoryRepository
                repo = MemoryRepository(db_session)
                entries = await repo.query(filters={"type": MemoryType.PROCEDURAL.value}, limit=10)
                for entry in entries:
                    if sop_name in entry.tags or entry.metadata.get("sop_name") == sop_name:
                        self._sop_cache[sop_name] = entry.metadata.get("sop_definition", {})
                        return self._sop_cache[sop_name]
        
        return None
    
    async def list_sops(self) -> list[dict]:
        """List all available SOPs."""
        query = MemoryQuery(
            tags=["sop"],
            limit=100,
        )
        
        results = []
        if self.database:
            async with self.database.session() as db_session:
                from core.memory.storage import MemoryRepository
                repo = MemoryRepository(db_session)
                entries = await repo.query(filters={"type": MemoryType.PROCEDURAL.value}, limit=100)
                for entry in entries:
                    if "sop" in entry.tags:
                        results.append({
                            "name": entry.metadata.get("sop_name", "unknown"),
                            "description": entry.summary,
                            "version": entry.metadata.get("version", "1.0"),
                        })
        
        return results
    
    async def add_sop(
        self,
        name: str,
        definition: dict,
        description: str = "",
        agent_name: str = "system",
    ) -> MemoryEntry:
        """Add a new SOP definition."""
        import json
        
        entry = MemoryEntry(
            type=MemoryType.PROCEDURAL,
            scope=MemoryScope.GLOBAL,
            agent_name=agent_name,
            content=json.dumps(definition, indent=2),
            summary=description or f"SOP: {name}",
            tags=["sop", name],
            importance=0.9,
            metadata={
                "sop_name": name,
                "sop_definition": definition,
                "version": definition.get("version", "1.0"),
            },
        )
        
        return await self.add(entry)
    
    async def get_workflow_template(self, template_name: str) -> dict | None:
        """Get workflow template by name."""
        query = MemoryQuery(
            tags=["workflow_template", template_name],
            limit=1,
        )
        
        if self.database:
            async with self.database.session() as db_session:
                from core.memory.storage import MemoryRepository
                repo = MemoryRepository(db_session)
                entries = await repo.query(filters={"type": MemoryType.PROCEDURAL.value}, limit=10)
                for entry in entries:
                    if template_name in entry.tags:
                        import json
                        return json.loads(entry.content)
        
        return None
