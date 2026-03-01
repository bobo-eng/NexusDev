"""SQLAlchemy models for database tables."""

from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.storage.database import Base


class SessionModel(Base):
    """Database model for Session."""
    
    __tablename__ = "sessions"
    
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="created")
    
    requirement: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    
    current_stage_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    completed_stages: Mapped[list] = mapped_column(JSON, default=list)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    created_by: Mapped[str] = mapped_column(String(100), default="anonymous")
    sop_config: Mapped[str] = mapped_column(String(100), default="default")
    model_config_name: Mapped[str] = mapped_column(String(100), default="default")
    
    # Relationships
    stages: Mapped[list["StageModel"]] = relationship(
        "StageModel",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list["ArtifactModel"]] = relationship(
        "ArtifactModel",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class StageModel(Base):
    """Database model for Stage."""
    
    __tablename__ = "stages"
    
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    session_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id"),
        nullable=False,
    )
    
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    stage_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="pending")
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    
    input_artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    output_artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    review_ids: Mapped[list] = mapped_column(JSON, default=list)
    
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approval_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Relationships
    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="stages")


class ArtifactModel(Base):
    """Database model for Artifact."""
    
    __tablename__ = "artifacts"
    
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    session_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id"),
        nullable=False,
    )
    stage_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    
    content: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(100), default="text/plain")
    
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_version_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    
    parent_artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    derived_artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_result: Mapped[dict] = mapped_column(JSON, default=dict)
    
    # Relationships
    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="artifacts")


class ReviewModel(Base):
    """Database model for Review."""
    
    __tablename__ = "reviews"
    
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    session_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    stage_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    
    comments: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    security_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    performance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maintainability_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    total_issues: Mapped[int] = mapped_column(Integer, default=0)
    critical_issues: Mapped[int] = mapped_column(Integer, default=0)
    major_issues: Mapped[int] = mapped_column(Integer, default=0)
    minor_issues: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    metadata: Mapped[dict] = mapped_column(JSON, default=dict)


class ApprovalRecordModel(Base):
    """Database model for ApprovalRecord (HITL)."""
    
    __tablename__ = "approval_records"
    
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )
    session_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    stage_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    stage_name: Mapped[str] = mapped_column(String(100), nullable=False)
    artifact_ids: Mapped[list] = mapped_column(JSON, default=list)
    
    state: Mapped[str] = mapped_column(String(50), default="pending")
    
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    request_message: Mapped[str] = mapped_column(Text, default="")
    
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approval_message: Mapped[str] = mapped_column(Text, default="")
    
    rejected_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, default="")
    
    timeout_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    comments: Mapped[list] = mapped_column(JSON, default=list)
    history: Mapped[list] = mapped_column(JSON, default=list)
    metadata: Mapped[dict] = mapped_column(JSON, default=dict)
