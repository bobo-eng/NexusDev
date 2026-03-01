"""Approval service for HITL workflow."""

import logging
from typing import Any
from uuid import UUID

from core.hitl.approval_sm import ApprovalStateMachine, ApprovalState, ApprovalRecord
from core.storage.database import Database
from core.storage.repository import ApprovalRepository

logger = logging.getLogger(__name__)


class ApprovalService:
    """Service for managing human approvals.
    
    Provides:
    - Create approval requests
    - Process approvals/rejections
    - Query approval status
    - Handle timeouts
    
    All approval records are persisted to the database.
    """
    
    def __init__(self, database: Database):
        self.database = database
        # Cache for in-memory access (still needed for quick lookups)
        self._approval_cache: dict[UUID, ApprovalStateMachine] = {}
    
    async def _load_to_cache(self, approval_id: UUID) -> ApprovalStateMachine | None:
        """Load approval from DB to cache."""
        if approval_id in self._approval_cache:
            return self._approval_cache[approval_id]
        
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            record = await repo.get_by_id(approval_id)
            if record:
                sm = ApprovalStateMachine(record)
                self._approval_cache[approval_id] = sm
                return sm
        return None
    
    async def _save_to_db(self, sm: ApprovalStateMachine) -> None:
        """Save approval state machine to DB."""
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            # Check if exists
            existing = await repo.get_by_id(sm.record.id)
            if existing:
                await repo.update(sm.record)
            else:
                await repo.create(sm.record)
    
    async def create_approval(
        self,
        session_id: UUID,
        stage_id: UUID,
        stage_name: str,
        requested_by: str,
        request_message: str = "",
        timeout_hours: int = 24,
        artifact_ids: list[UUID] | None = None,
    ) -> ApprovalRecord:
        """Create a new approval request.
        
        Args:
            session_id: Session ID
            stage_id: Stage ID
            stage_name: Stage name
            requested_by: Who requested approval
            request_message: Request message
            timeout_hours: Timeout in hours
            artifact_ids: Related artifact IDs
            
        Returns:
            Created approval record
        """
        sm = ApprovalStateMachine.create(
            session_id=session_id,
            stage_id=stage_id,
            stage_name=stage_name,
            requested_by=requested_by,
            request_message=request_message,
            timeout_hours=timeout_hours,
            artifact_ids=artifact_ids or [],
        )
        
        # Persist to database
        await self._save_to_db(sm)
        
        # Cache in memory
        self._approval_cache[sm.record.id] = sm
        
        logger.info(
            f"[Session {session_id}] Created approval {sm.record.id} for stage {stage_name}"
        )
        
        # TODO: Send notification to approvers
        
        return sm.record
    
    async def approve(
        self,
        approval_id: UUID,
        approved_by: str,
        message: str = "",
    ) -> ApprovalRecord | None:
        """Approve a request.
        
        Args:
            approval_id: Approval record ID
            approved_by: Who is approving
            message: Approval message
            
        Returns:
            Updated record or None
        """
        sm = await self._load_to_cache(approval_id)
        if not sm:
            logger.error(f"Approval {approval_id} not found")
            return None
        
        if not sm.can_transition("approve"):
            logger.error(f"Cannot approve approval {approval_id} in state {sm.record.state.value}")
            return None
        
        sm.approve(approved_by, message)
        
        # Persist to database
        await self._save_to_db(sm)
        
        logger.info(f"Approval {approval_id} approved by {approved_by}")
        
        # TODO: Notify session service
        
        return sm.record
    
    async def reject(
        self,
        approval_id: UUID,
        rejected_by: str,
        reason: str = "",
    ) -> ApprovalRecord | None:
        """Reject a request.
        
        Args:
            approval_id: Approval record ID
            rejected_by: Who is rejecting
            reason: Rejection reason
            
        Returns:
            Updated record or None
        """
        sm = await self._load_to_cache(approval_id)
        if not sm:
            logger.error(f"Approval {approval_id} not found")
            return None
        
        if not sm.can_transition("reject"):
            logger.error(f"Cannot reject approval {approval_id} in state {sm.record.state.value}")
            return None
        
        sm.reject(rejected_by, reason)
        
        # Persist to database
        await self._save_to_db(sm)
        
        logger.info(f"Approval {approval_id} rejected by {rejected_by}")
        
        # TODO: Notify session service
        
        return sm.record
    
    async def request_changes(
        self,
        approval_id: UUID,
        requested_by: str,
        message: str = "",
    ) -> ApprovalRecord | None:
        """Request changes without full rejection.
        
        Args:
            approval_id: Approval record ID
            requested_by: Who is requesting changes
            message: Change request message
            
        Returns:
            Updated record or None
        """
        sm = await self._load_to_cache(approval_id)
        if not sm:
            return None
        
        sm.request_changes(requested_by, message)
        
        # Persist to database
        await self._save_to_db(sm)
        
        return sm.record
    
    async def get_approval(self, approval_id: UUID) -> ApprovalRecord | None:
        """Get approval record by ID."""
        # Try cache first
        if approval_id in self._approval_cache:
            return self._approval_cache[approval_id].record
        
        # Load from DB
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            return await repo.get_by_id(approval_id)
    
    async def get_pending_approvals(
        self,
        session_id: UUID | None = None,
    ) -> list[ApprovalRecord]:
        """Get all pending approvals.
        
        Args:
            session_id: Filter by session (optional)
            
        Returns:
            List of pending approval records
        """
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            return await repo.get_by_state(
                ApprovalState.PENDING.value,
                session_id=session_id,
            )
    
    async def get_session_approvals(
        self,
        session_id: UUID,
    ) -> list[ApprovalRecord]:
        """Get all approvals for a session."""
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            return await repo.get_by_session(session_id)
    
    async def check_timeouts(self) -> list[ApprovalRecord]:
        """Check and process timed out approvals.
        
        Returns:
            List of timed out records
        """
        timed_out = []
        
        # Get all pending approvals from DB
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            pending = await repo.get_by_state(ApprovalState.PENDING.value)
        
        for record in pending:
            sm = ApprovalStateMachine(record)
            if sm.check_timeout():
                timed_out.append(record)
                # Persist timeout
                await self._save_to_db(sm)
                logger.warning(f"Approval {record.id} timed out")
        
        return timed_out
    
    async def add_comment(
        self,
        approval_id: UUID,
        author: str,
        content: str,
        is_internal: bool = False,
    ) -> ApprovalRecord | None:
        """Add comment to approval.
        
        Args:
            approval_id: Approval record ID
            author: Comment author
            content: Comment content
            is_internal: Internal note flag
            
        Returns:
            Updated record or None
        """
        sm = await self._load_to_cache(approval_id)
        if not sm:
            return None
        
        sm.record.add_comment(author, content, is_internal)
        
        # Persist to database
        await self._save_to_db(sm)
        
        return sm.record
    
    async def get_approval_summary(self, approval_id: UUID) -> dict[str, Any] | None:
        """Get human-readable approval summary."""
        record = await self.get_approval(approval_id)
        if not record:
            return None
        
        return {
            "id": str(record.id),
            "session_id": str(record.session_id),
            "stage_name": record.stage_name,
            "state": record.state.value,
            "requested_by": record.requested_by,
            "requested_at": record.requested_at.isoformat(),
            "approved_by": record.approved_by,
            "approved_at": record.approved_at.isoformat() if record.approved_at else None,
            "rejected_by": record.rejected_by,
            "rejected_at": record.rejected_at.isoformat() if record.rejected_at else None,
            "timeout_at": record.timeout_at.isoformat() if record.timeout_at else None,
            "time_remaining": str(record.time_remaining()) if record.time_remaining() else None,
            "is_pending": record.is_pending(),
            "is_resolved": record.is_resolved(),
            "comment_count": len(record.comments),
        }
