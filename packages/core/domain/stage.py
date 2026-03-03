"""Stage entity representing a workflow phase."""

from datetime import datetime
from enum import Enum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class StageType(str, Enum):
    """Predefined stage types in the development workflow."""

    REQUIREMENT_ANALYSIS = "requirement_analysis"
    SYSTEM_DESIGN = "system_design"
    CODING = "coding"
    CODE_REVIEW = "code_review"
    TESTING = "testing"
    DEPLOYMENT = "deployment"


class StageStatus(str, Enum):
    """Stage lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Stage(BaseModel):
    """A workflow stage representing a specific phase of development.

    Each stage has a specific agent responsible for execution,
    produces artifacts, and may require human approval.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID

    # Stage definition
    name: str = Field(..., min_length=1, max_length=100)
    stage_type: StageType
    description: str = Field(default="", max_length=1000)

    # Execution
    status: StageStatus = Field(default=StageStatus.PENDING)
    agent_name: str = Field(..., min_length=1)

    # Ordering
    sequence: int = Field(default=0, ge=0)

    # Artifacts produced in this stage
    input_artifact_ids: list[UUID] = Field(default_factory=list)
    output_artifact_ids: list[UUID] = Field(default_factory=list)

    # Review tracking
    review_ids: list[UUID] = Field(default_factory=list)

    # Execution context and results
    context: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = Field(default=None)

    # Retry mechanism
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=3, ge=0)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    # Approval
    requires_approval: bool = Field(default=False)
    approved_by: str | None = Field(default=None)
    approved_at: datetime | None = Field(default=None)
    approval_comment: str | None = Field(default=None)

    def start(self) -> Self:
        """Mark stage as started."""
        self.status = StageStatus.RUNNING
        self.started_at = datetime.utcnow()
        return self

    def complete(self) -> Self:
        """Mark stage as completed."""
        self.status = StageStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        return self

    def fail(self, error: str) -> Self:
        """Mark stage as failed with error message."""
        self.status = StageStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.utcnow()
        return self

    def wait_for_approval(self) -> Self:
        """Mark stage as waiting for human approval."""
        self.status = StageStatus.WAITING_APPROVAL
        self.requires_approval = True
        return self

    def approve(self, by: str, comment: str | None = None) -> Self:
        """Approve the stage."""
        self.status = StageStatus.APPROVED
        self.approved_by = by
        self.approved_at = datetime.utcnow()
        self.approval_comment = comment
        return self

    def reject(self, by: str, comment: str | None = None) -> Self:
        """Reject the stage."""
        self.status = StageStatus.REJECTED
        self.approved_by = by
        self.approved_at = datetime.utcnow()
        self.approval_comment = comment
        return self

    def skip(self) -> Self:
        """Mark stage as skipped."""
        self.status = StageStatus.SKIPPED
        self.completed_at = datetime.utcnow()
        return self

    def can_retry(self) -> bool:
        """Check if stage can be retried."""
        return self.retry_count < self.max_retries and self.status == StageStatus.FAILED

    def increment_retry(self) -> Self:
        """Increment retry counter."""
        self.retry_count += 1
        return self

    def add_output_artifact(self, artifact_id: UUID) -> Self:
        """Add an output artifact to this stage."""
        if artifact_id not in self.output_artifact_ids:
            self.output_artifact_ids.append(artifact_id)
        return self

    def add_input_artifact(self, artifact_id: UUID) -> Self:
        """Add an input artifact to this stage."""
        if artifact_id not in self.input_artifact_ids:
            self.input_artifact_ids.append(artifact_id)
        return self

    def add_review(self, review_id: UUID) -> Self:
        """Add a review to this stage."""
        if review_id not in self.review_ids:
            self.review_ids.append(review_id)
        return self

    def is_terminal(self) -> bool:
        """Check if stage is in a terminal state."""
        return self.status in {
            StageStatus.COMPLETED,
            StageStatus.FAILED,
            StageStatus.SKIPPED,
            StageStatus.REJECTED,
        }
