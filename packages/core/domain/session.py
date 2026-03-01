"""Session entity representing a development workflow instance."""

from datetime import datetime
from enum import Enum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class SessionStatus(str, Enum):
    """Session lifecycle states."""
    
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Session(BaseModel):
    """A development session orchestrating multi-agent workflow.
    
    A session represents a complete development task from requirement
    to delivery, tracking all stages, artifacts, and decisions.
    """
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    status: SessionStatus = Field(default=SessionStatus.CREATED)
    
    # Requirements
    requirement: str = Field(..., min_length=1, max_length=10000)
    context: dict[str, Any] = Field(default_factory=dict)
    
    # Current stage tracking
    current_stage_id: UUID | None = Field(default=None)
    completed_stages: list[UUID] = Field(default_factory=list)
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default=None)
    
    # User/Owner
    created_by: str = Field(default="anonymous")
    
    # Configuration
    sop_config: str = Field(default="default")
    model_config_name: str = Field(default="default")
    
    def mark_running(self) -> Self:
        """Mark session as running."""
        self.status = SessionStatus.RUNNING
        self.updated_at = datetime.utcnow()
        return self
    
    def mark_waiting_approval(self) -> Self:
        """Mark session as waiting for human approval."""
        self.status = SessionStatus.WAITING_APPROVAL
        self.updated_at = datetime.utcnow()
        return self
    
    def mark_approved(self) -> Self:
        """Mark session as approved."""
        self.status = SessionStatus.APPROVED
        self.updated_at = datetime.utcnow()
        return self
    
    def mark_rejected(self) -> Self:
        """Mark session as rejected."""
        self.status = SessionStatus.REJECTED
        self.updated_at = datetime.utcnow()
        return self
    
    def mark_completed(self) -> Self:
        """Mark session as completed."""
        self.status = SessionStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        return self
    
    def mark_failed(self) -> Self:
        """Mark session as failed."""
        self.status = SessionStatus.FAILED
        self.updated_at = datetime.utcnow()
        return self
    
    def mark_cancelled(self) -> Self:
        """Mark session as cancelled."""
        self.status = SessionStatus.CANCELLED
        self.updated_at = datetime.utcnow()
        return self
    
    def advance_stage(self, stage_id: UUID) -> Self:
        """Advance to next stage."""
        if self.current_stage_id:
            self.completed_stages.append(self.current_stage_id)
        self.current_stage_id = stage_id
        self.updated_at = datetime.utcnow()
        return self
    
    def is_active(self) -> bool:
        """Check if session is still active."""
        return self.status in {
            SessionStatus.CREATED,
            SessionStatus.RUNNING,
            SessionStatus.WAITING_APPROVAL,
            SessionStatus.APPROVED,
        }
    
    def can_approve(self) -> bool:
        """Check if session can be approved."""
        return self.status == SessionStatus.WAITING_APPROVAL
    
    def can_reject(self) -> bool:
        """Check if session can be rejected."""
        return self.status == SessionStatus.WAITING_APPROVAL
