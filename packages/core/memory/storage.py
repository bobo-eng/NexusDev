"""Database storage for memory entries."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.storage.database import Base


class MemoryEntryModel(Base):
    """Database model for memory entries."""
    
    __tablename__ = "memory_entries"
    
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(50), default="session")
    
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    stage_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), default="text/plain")
    summary: Mapped[str] = mapped_column(Text, default="")
    
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(default=0)
    
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    
    feedback_positive: Mapped[bool | None] = mapped_column(nullable=True)
    feedback_notes: Mapped[str] = mapped_column(Text, default="")


from core.memory.types import MemoryEntry


class MemoryRepository:
    """Repository for memory entries."""
    
    def __init__(self, session):
        self.session = session
    
    async def create(self, entry: MemoryEntry) -> MemoryEntry:
        """Create memory entry."""
        model = MemoryEntryModel(
            id=entry.id,
            type=entry.type.value,
            scope=entry.scope.value,
            session_id=entry.session_id,
            project_id=entry.project_id,
            agent_name=entry.agent_name,
            stage_id=entry.stage_id,
            content=entry.content,
            content_type=entry.content_type,
            summary=entry.summary,
            meta=entry.metadata,
            embedding=entry.embedding,
            tags=entry.tags,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            accessed_at=entry.accessed_at,
            access_count=entry.access_count,
            importance=entry.importance,
            confidence=entry.confidence,
            feedback_positive=entry.feedback_positive,
            feedback_notes=entry.feedback_notes,
        )
        self.session.add(model)
        await self.session.flush()
        return entry
    
    async def get_by_id(self, entry_id: UUID) -> MemoryEntry | None:
        """Get entry by ID."""
        from sqlalchemy import select
        result = await self.session.execute(
            select(MemoryEntryModel).where(MemoryEntryModel.id == entry_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entry(model) if model else None
    
    async def update(self, entry: MemoryEntry) -> MemoryEntry:
        """Update entry."""
        from sqlalchemy import select
        result = await self.session.execute(
            select(MemoryEntryModel).where(MemoryEntryModel.id == entry.id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.content = entry.content
            model.summary = entry.summary
            model.meta = entry.metadata
            model.tags = entry.tags
            model.updated_at = entry.updated_at
            model.accessed_at = entry.accessed_at
            model.access_count = entry.access_count
            model.importance = entry.importance
            model.feedback_positive = entry.feedback_positive
            model.feedback_notes = entry.feedback_notes
            await self.session.flush()
        return entry
    
    async def query(
        self,
        filters: dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        order_by: str = "recency",
    ) -> list[MemoryEntry]:
        """Query entries with filters."""
        from sqlalchemy import select
        
        query = select(MemoryEntryModel)
        
        for key, value in filters.items():
            query = query.where(getattr(MemoryEntryModel, key) == value)
        
        if order_by == "recency":
            query = query.order_by(MemoryEntryModel.created_at.desc())
        elif order_by == "importance":
            query = query.order_by(MemoryEntryModel.importance.desc())
        
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        models = result.scalars().all()
        return [self._to_entry(m) for m in models if m]
    
    def _to_entry(self, model: MemoryEntryModel) -> MemoryEntry:
        """Convert model to entry."""
        from core.memory.types import MemoryType, MemoryScope
        
        return MemoryEntry(
            id=model.id,
            type=MemoryType(model.type),
            scope=MemoryScope(model.scope),
            session_id=model.session_id,
            project_id=model.project_id,
            agent_name=model.agent_name,
            stage_id=model.stage_id,
            content=model.content,
            content_type=model.content_type,
            summary=model.summary,
            metadata=model.meta,
            embedding=model.embedding,
            tags=model.tags,
            created_at=model.created_at,
            updated_at=model.updated_at,
            accessed_at=model.accessed_at,
            access_count=model.access_count,
            importance=model.importance,
            confidence=model.confidence,
            feedback_positive=model.feedback_positive,
            feedback_notes=model.feedback_notes,
        )
