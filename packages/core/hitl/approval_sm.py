"""HITL Approval State Machine.

Manages human approval workflow:
- PENDING -> APPROVED/REJECTED
- Timeout handling
- Approval delegation
- Audit trail
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class ApprovalState(str, Enum):
    """States in the approval state machine."""
    
    PENDING = "pending"           # Waiting for approval
    IN_REVIEW = "in_review"       # Someone is reviewing
    APPROVED = "approved"         # Approved
    REJECTED = "rejected"         # Rejected
    ESCALATED = "escalated"       # Escalated to higher authority
    TIMED_OUT = "timed_out"       # Approval timeout
    CANCELLED = "cancelled"       # Approval request cancelled


class ApprovalAction(str, Enum):
    """Actions that can be taken on an approval."""
    
    SUBMIT = "submit"             # Submit for approval
    CLAIM = "claim"               # Claim for review
    APPROVE = "approve"           # Approve
    REJECT = "reject"             # Reject
    REQUEST_CHANGES = "request_changes"  # Request changes
    ESCALATE = "escalate"         # Escalate to higher authority
    CANCEL = "cancel"             # Cancel approval request
    REMIND = "remind"             # Send reminder


@dataclass
class ApprovalComment:
    """A comment on an approval."""
    
    id: UUID = field(default_factory=uuid4)
    author: str = ""
    content: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_internal: bool = False  # Internal note vs visible to all


@dataclass
class ApprovalRecord:
    """Record of an approval request and outcome.
    
    This is the audit trail for all approval actions.
    """
    
    id: UUID = field(default_factory=uuid4)
    
    # What is being approved
    session_id: UUID = None
    stage_id: UUID = None
    stage_name: str = ""
    artifact_ids: list[UUID] = field(default_factory=list)
    
    # Current state
    state: ApprovalState = ApprovalState.PENDING
    
    # Request details
    requested_by: str = ""
    requested_at: datetime = field(default_factory=datetime.utcnow)
    request_message: str = ""
    
    # Approval details
    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_message: str = ""
    
    # Rejection details
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str = ""
    
    # Timeout
    timeout_at: datetime | None = None
    
    # Comments
    comments: list[ApprovalComment] = field(default_factory=list)
    
    # History
    history: list[dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def add_comment(self, author: str, content: str, is_internal: bool = False) -> "ApprovalRecord":
        """Add a comment."""
        comment = ApprovalComment(
            author=author,
            content=content,
            is_internal=is_internal,
        )
        self.comments.append(comment)
        return self
    
    def add_history(self, action: str, actor: str, details: dict[str, Any] | None = None) -> "ApprovalRecord":
        """Add history entry."""
        entry = {
            "action": action,
            "actor": actor,
            "timestamp": datetime.utcnow().isoformat(),
            "state": self.state.value,
        }
        if details:
            entry["details"] = details
        self.history.append(entry)
        return self
    
    def is_pending(self) -> bool:
        """Check if approval is still pending."""
        return self.state in [ApprovalState.PENDING, ApprovalState.IN_REVIEW]
    
    def is_resolved(self) -> bool:
        """Check if approval is resolved (approved or rejected)."""
        return self.state in [ApprovalState.APPROVED, ApprovalState.REJECTED]
    
    def is_timed_out(self) -> bool:
        """Check if approval has timed out."""
        if self.timeout_at and datetime.utcnow() > self.timeout_at:
            return True
        return self.state == ApprovalState.TIMED_OUT
    
    def time_remaining(self) -> timedelta | None:
        """Get time remaining for approval."""
        if self.timeout_at:
            remaining = self.timeout_at - datetime.utcnow()
            return max(remaining, timedelta(0))
        return None


class ApprovalStateMachine:
    """State machine for managing approval workflow.
    
    States: PENDING -> IN_REVIEW -> [APPROVED | REJECTED | ESCALATED]
                    -> TIMED_OUT
                    -> CANCELLED
    """
    
    # Valid state transitions
    TRANSITIONS: dict[tuple[ApprovalState, ApprovalAction], ApprovalState] = {
        # From PENDING
        (ApprovalState.PENDING, ApprovalAction.CLAIM): ApprovalState.IN_REVIEW,
        (ApprovalState.PENDING, ApprovalAction.APPROVE): ApprovalState.APPROVED,
        (ApprovalState.PENDING, ApprovalAction.REJECT): ApprovalState.REJECTED,
        (ApprovalState.PENDING, ApprovalAction.ESCALATE): ApprovalState.ESCALATED,
        (ApprovalState.PENDING, ApprovalAction.CANCEL): ApprovalState.CANCELLED,
        
        # From IN_REVIEW
        (ApprovalState.IN_REVIEW, ApprovalAction.APPROVE): ApprovalState.APPROVED,
        (ApprovalState.IN_REVIEW, ApprovalAction.REJECT): ApprovalState.REJECTED,
        (ApprovalState.IN_REVIEW, ApprovalAction.REQUEST_CHANGES): ApprovalState.PENDING,
        (ApprovalState.IN_REVIEW, ApprovalAction.ESCALATE): ApprovalState.ESCALATED,
        (ApprovalState.IN_REVIEW, ApprovalAction.CANCEL): ApprovalState.CANCELLED,
        
        # From ESCALATED
        (ApprovalState.ESCALATED, ApprovalAction.APPROVE): ApprovalState.APPROVED,
        (ApprovalState.ESCALATED, ApprovalAction.REJECT): ApprovalState.REJECTED,
        (ApprovalState.ESCALATED, ApprovalAction.CANCEL): ApprovalState.CANCELLED,
    }
    
    def __init__(self, record: ApprovalRecord | None = None):
        self.record = record or ApprovalRecord()
    
    def can_transition(self, action: ApprovalAction) -> bool:
        """Check if an action is valid in current state."""
        key = (self.record.state, action)
        return key in self.TRANSITIONS
    
    def transition(
        self,
        action: ApprovalAction,
        actor: str,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRecord:
        """Execute a state transition.
        
        Args:
            action: The action to take
            actor: Who is taking the action
            message: Optional message
            metadata: Optional metadata
            
        Returns:
            Updated approval record
            
        Raises:
            ValueError: If transition is invalid
        """
        if not self.can_transition(action):
            raise ValueError(
                f"Cannot {action.value} from {self.record.state.value}"
            )
        
        # Get new state
        new_state = self.TRANSITIONS[(self.record.state, action)]
        old_state = self.record.state
        
        # Update record
        self.record.state = new_state
        
        # Record specific action details
        if action == ApprovalAction.APPROVE:
            self.record.approved_by = actor
            self.record.approved_at = datetime.utcnow()
            self.record.approval_message = message
        
        elif action == ApprovalAction.REJECT:
            self.record.rejected_by = actor
            self.record.rejected_at = datetime.utcnow()
            self.record.rejection_reason = message
        
        elif action == ApprovalAction.CLAIM:
            # Add comment that someone claimed it
            self.record.add_comment(actor, "Claimed for review", is_internal=True)
        
        # Add history
        self.record.add_history(
            action=action.value,
            actor=actor,
            details={
                "from_state": old_state.value,
                "to_state": new_state.value,
                "message": message,
                **(metadata or {}),
            },
        )
        
        return self.record
    
    def approve(self, by: str, message: str = "") -> ApprovalRecord:
        """Approve the request."""
        return self.transition(ApprovalAction.APPROVE, by, message)
    
    def reject(self, by: str, reason: str = "") -> ApprovalRecord:
        """Reject the request."""
        return self.transition(ApprovalAction.REJECT, by, reason)
    
    def claim(self, by: str) -> ApprovalRecord:
        """Claim the approval for review."""
        return self.transition(ApprovalAction.CLAIM, by)
    
    def request_changes(self, by: str, message: str = "") -> ApprovalRecord:
        """Request changes and return to pending."""
        return self.transition(ApprovalAction.REQUEST_CHANGES, by, message)
    
    def escalate(self, by: str, reason: str = "") -> ApprovalRecord:
        """Escalate to higher authority."""
        return self.transition(ApprovalAction.ESCALATE, by, reason)
    
    def cancel(self, by: str, reason: str = "") -> ApprovalRecord:
        """Cancel the approval request."""
        return self.transition(ApprovalAction.CANCEL, by, reason)
    
    def check_timeout(self) -> bool:
        """Check and handle timeout.
        
        Returns:
            True if timed out
        """
        if self.record.is_timed_out() and self.record.is_pending():
            self.record.state = ApprovalState.TIMED_OUT
            self.record.add_history(
                action="timeout",
                actor="system",
                details={"timeout_at": self.record.timeout_at.isoformat() if self.record.timeout_at else None},
            )
            return True
        return False
    
    @classmethod
    def create(
        cls,
        session_id: UUID,
        stage_id: UUID,
        stage_name: str,
        requested_by: str,
        request_message: str = "",
        timeout_hours: int = 24,
        artifact_ids: list[UUID] | None = None,
    ) -> "ApprovalStateMachine":
        """Create a new approval state machine.
        
        Args:
            session_id: Session ID
            stage_id: Stage ID
            stage_name: Stage name
            requested_by: Who requested approval
            request_message: Request message
            timeout_hours: Approval timeout in hours
            artifact_ids: Related artifact IDs
            
        Returns:
            New approval state machine
        """
        timeout_at = datetime.utcnow() + timedelta(hours=timeout_hours)
        
        record = ApprovalRecord(
            session_id=session_id,
            stage_id=stage_id,
            stage_name=stage_name,
            requested_by=requested_by,
            request_message=request_message,
            timeout_at=timeout_at,
            artifact_ids=artifact_ids or [],
        )
        
        record.add_history(
            action="create",
            actor=requested_by,
            details={"timeout_at": timeout_at.isoformat()},
        )
        
        return cls(record)
