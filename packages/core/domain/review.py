"""Review entity representing code/design review outcomes."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ReviewType(StrEnum):
    """Types of reviews in the workflow."""

    DESIGN_REVIEW = "design_review"
    CODE_REVIEW = "code_review"
    TEST_REVIEW = "test_review"
    SECURITY_REVIEW = "security_review"
    PERFORMANCE_REVIEW = "performance_review"


class ReviewStatus(StrEnum):
    """Review outcome states."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    APPROVED_WITH_COMMENTS = "approved_with_comments"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"


class ReviewComment(BaseModel):
    """A single review comment."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    file_path: str | None = Field(default=None)
    line_number: int | None = Field(default=None)
    severity: str = Field(default="suggestion")  # critical, major, minor, suggestion
    message: str = Field(..., min_length=1)
    suggestion: str | None = Field(default=None)

    # Resolution
    is_resolved: bool = Field(default=False)
    resolved_by: str | None = Field(default=None)
    resolved_at: datetime | None = Field(default=None)
    resolution_note: str | None = Field(default=None)


class Review(BaseModel):
    """A review of artifacts produced in a stage.

    Reviews can be performed by agents (automated) or humans,
    and track issues, suggestions, and approval status.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    stage_id: UUID
    artifact_ids: list[UUID] = Field(default_factory=list)

    # Review definition
    review_type: ReviewType
    reviewer: str = Field(..., min_length=1)  # Agent name or user

    # Status
    status: ReviewStatus = Field(default=ReviewStatus.PENDING)

    # Comments and issues
    comments: list[ReviewComment] = Field(default_factory=list)
    summary: str = Field(default="", max_length=2000)

    # Scores (0-100)
    quality_score: int | None = Field(default=None, ge=0, le=100)
    security_score: int | None = Field(default=None, ge=0, le=100)
    performance_score: int | None = Field(default=None, ge=0, le=100)
    maintainability_score: int | None = Field(default=None, ge=0, le=100)

    # Metrics
    total_issues: int = Field(default=0)
    critical_issues: int = Field(default=0)
    major_issues: int = Field(default=0)
    minor_issues: int = Field(default=0)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

    # Additional data
    metadata: dict[str, Any] = Field(default_factory=dict)

    def start(self) -> "Review":
        """Mark review as started."""
        self.status = ReviewStatus.IN_PROGRESS
        self.started_at = datetime.utcnow()
        return self

    def approve(self, summary: str = "") -> "Review":
        """Approve the review."""
        self.status = ReviewStatus.APPROVED
        self.summary = summary
        self.completed_at = datetime.utcnow()
        return self

    def approve_with_comments(self, summary: str = "") -> "Review":
        """Approve with comments."""
        self.status = ReviewStatus.APPROVED_WITH_COMMENTS
        self.summary = summary
        self.completed_at = datetime.utcnow()
        return self

    def request_changes(self, summary: str = "") -> "Review":
        """Request changes."""
        self.status = ReviewStatus.CHANGES_REQUESTED
        self.summary = summary
        self.completed_at = datetime.utcnow()
        return self

    def reject(self, summary: str = "") -> "Review":
        """Reject the review."""
        self.status = ReviewStatus.REJECTED
        self.summary = summary
        self.completed_at = datetime.utcnow()
        return self

    def add_comment(
        self,
        message: str,
        severity: str = "suggestion",
        file_path: str | None = None,
        line_number: int | None = None,
        suggestion: str | None = None,
    ) -> "Review":
        """Add a comment to the review."""
        comment = ReviewComment(
            message=message,
            severity=severity,
            file_path=file_path,
            line_number=line_number,
            suggestion=suggestion,
        )
        self.comments.append(comment)
        self._update_issue_counts()
        return self

    def _update_issue_counts(self) -> None:
        """Update issue counts from comments."""
        self.total_issues = len(self.comments)
        self.critical_issues = sum(1 for c in self.comments if c.severity == "critical")
        self.major_issues = sum(1 for c in self.comments if c.severity == "major")
        self.minor_issues = sum(1 for c in self.comments if c.severity == "minor")

    def set_scores(
        self,
        quality: int | None = None,
        security: int | None = None,
        performance: int | None = None,
        maintainability: int | None = None,
    ) -> "Review":
        """Set review scores."""
        if quality is not None:
            self.quality_score = quality
        if security is not None:
            self.security_score = security
        if performance is not None:
            self.performance_score = performance
        if maintainability is not None:
            self.maintainability_score = maintainability
        return self

    def has_blocking_issues(self) -> bool:
        """Check if review has blocking issues."""
        return self.critical_issues > 0 or self.status == ReviewStatus.CHANGES_REQUESTED

    def is_approved(self) -> bool:
        """Check if review is approved."""
        return self.status in {ReviewStatus.APPROVED, ReviewStatus.APPROVED_WITH_COMMENTS}

    def get_unresolved_comments(self) -> list[ReviewComment]:
        """Get all unresolved comments."""
        return [c for c in self.comments if not c.is_resolved]
