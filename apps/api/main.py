"""FastAPI application for NexusDev API.

Provides REST endpoints for:
- Session management
- Stage execution
- Approval workflow
- Status queries
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import os

from core.domain.session import SessionStatus
from core.security.rbac import Permission, get_rbac
from core.services.approval_service import ApprovalService
from core.services.session_service import SessionService
from core.storage.database import Database, create_database
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

# Global database instance
_db: Database | None = None


async def get_db() -> Database:
    """Get database instance."""
    global _db
    if _db is None:
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./nexusdev.db")
        _db = create_database(database_url)
        await _db.create_tables()
    return _db


async def get_session_service() -> SessionService:
    """Get session service."""
    db = await get_db()
    return SessionService(db)


async def get_approval_service() -> ApprovalService:
    """Get approval service."""
    db = await get_db()
    return ApprovalService(db)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
ApprovalServiceDep = Annotated[ApprovalService, Depends(get_approval_service)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan manager."""
    # Startup
    db = await get_db()
    await db.create_tables()
    yield
    # Shutdown
    if _db:
        await _db.close()


def create_app() -> FastAPI:
    """Create FastAPI application."""
    app = FastAPI(
        title="NexusDev API",
        description="Multi-Agent Automated Development System",
        version="0.1.0",
        lifespan=lifespan,
    )

    def _ensure_permission(user: str, permission: Permission) -> None:
        """Ensure user has required permission."""
        if not get_rbac().check_permission(user, permission):
            raise HTTPException(
                status_code=403,
                detail=f"User '{user}' lacks permission '{permission.value}'",
            )

    def _raise_service_error(detail: str) -> None:
        """Map service error messages to HTTP responses."""
        lowered = detail.lower()
        status_code = 400
        if "permission denied" in lowered or "not allowed" in lowered:
            status_code = 403
        raise HTTPException(status_code=status_code, detail=detail)

    # Request/Response models
    class CreateSessionRequest(BaseModel):
        name: str = Field(..., min_length=1, max_length=200)
        requirement: str = Field(..., min_length=1, max_length=10000)
        description: str = Field(default="", max_length=1000)
        created_by: str = Field(default="api-user")
        context: dict = Field(default_factory=dict)

    class SessionResponse(BaseModel):
        id: str
        name: str
        status: str
        created_at: str

    class RunStageRequest(BaseModel):
        stage_type: str | None = None
        background: bool = Field(default=False, description="Run in background without waiting for completion")
    class ApprovalRequest(BaseModel):
        message: str = ""
        user: str = "api-user"

    class RejectionRequest(BaseModel):
        reason: str
        user: str = "api-user"

    class ClaimRequest(BaseModel):
        user: str = "api-user"

    class RequestChangesRequest(BaseModel):
        user: str = "api-user"
        message: str = ""

    class EscalationRequest(BaseModel):
        user: str = "api-user"
        reason: str = ""

    class CancelRequest(BaseModel):
        user: str = "api-user"
        reason: str = ""

    class RemindRequest(BaseModel):
        user: str = "api-user"
        message: str = ""

    class AddCommentRequest(BaseModel):
        author: str = "api-user"
        content: str = Field(..., min_length=1, max_length=5000)
        is_internal: bool = False

    class StatusResponse(BaseModel):
        session_id: str
        name: str
        status: str
        current_stage_id: str | None
        completed_stages: list[str]
        stages: list[dict]

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "nexusdev-api"}

    # Session endpoints
    @app.post("/sessions", response_model=SessionResponse)
    async def create_session(
        request: CreateSessionRequest,
        service: SessionServiceDep,
    ):
        """Create a new development session."""
        _ensure_permission(request.created_by, Permission.SESSION_CREATE)

        session = await service.create_session(
            name=request.name,
            requirement=request.requirement,
            description=request.description,
            created_by=request.created_by,
            context=request.context,
        )

        return SessionResponse(
            id=str(session.id),
            name=session.name,
            status=session.status.value,
            created_at=session.created_at.isoformat(),
        )

    @app.get("/sessions/{session_id}", response_model=StatusResponse)
    async def get_session(
        session_id: str,
        service: SessionServiceDep,
    ):
        """Get session status."""
        try:
            uuid = UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session ID format") from None

        status = await service.get_status(uuid)

        if "error" in status:
            raise HTTPException(status_code=404, detail=status["error"])

        return StatusResponse(
            session_id=status["session_id"],
            name=status["name"],
            status=status["status"],
            current_stage_id=status["current_stage_id"],
            completed_stages=status["completed_stages"],
            stages=status["stages"],
        )

    @app.get("/sessions")
    async def list_sessions(
        status: str | None = None,
        limit: int = 100,
        *,
        service: SessionServiceDep,
    ):
        """List sessions."""
        session_status = None
        if status:
            try:
                session_status = SessionStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid status") from None

        sessions = await service.list_sessions(
            status=session_status,
            limit=limit,
        )

        return [
            {
                "id": str(s.id),
                "name": s.name,
                "status": s.status.value,
                "created_at": s.created_at.isoformat(),
            }
            for s in sessions
        ]

    @app.post("/sessions/{session_id}/run")
    async def run_stage(
        session_id: str,
        background_tasks: BackgroundTasks,
        request: RunStageRequest | None = None,
        *,
        service: SessionServiceDep,
    ):
        """Run a workflow stage.
        
        Set background=true to run asynchronously and return immediately.
        """
        try:
            uuid = UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session ID format") from None

        # Check if background execution is requested
        is_background = request.background if request else False
        
        if is_background:
            # Run in background - schedule the task and return immediately
            background_tasks.add_task(service.run_stage, uuid, request.stage_type if request else None)
            return {
                "status": "queued",
                "message": "Stage execution started in background",
                "session_id": session_id,
            }
        
        # Synchronous execution (original behavior)
        stage_type = request.stage_type if request else None
        result = await service.run_stage(uuid, stage_type)

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    @app.post("/sessions/{session_id}/stages/{stage_id}/approve")
    async def approve_stage(
        session_id: str,
        stage_id: str,
        request: ApprovalRequest,
        service: SessionServiceDep,
    ):
        """Approve a pending stage."""
        _ensure_permission(request.user, Permission.APPROVAL_APPROVE)

        try:
            session_uuid = UUID(session_id)
            stage_uuid = UUID(stage_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ID format") from None

        result = await service.approve_stage(
            session_uuid,
            stage_uuid,
            request.user,
            request.message,
        )

        if "error" in result:
            _raise_service_error(result["error"])

        return result

    @app.post("/sessions/{session_id}/stages/{stage_id}/reject")
    async def reject_stage(
        session_id: str,
        stage_id: str,
        request: RejectionRequest,
        service: SessionServiceDep,
    ):
        """Reject a pending stage."""
        _ensure_permission(request.user, Permission.APPROVAL_REJECT)

        try:
            session_uuid = UUID(session_id)
            stage_uuid = UUID(stage_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ID format") from None

        result = await service.reject_stage(
            session_uuid,
            stage_uuid,
            request.user,
            request.reason,
        )

        if "error" in result:
            _raise_service_error(result["error"])

        return result

    # Approval endpoints
    @app.get("/approvals")
    async def list_approvals(
        session_id: str | None = None,
        user: str = "api-user",
        *,
        service: ApprovalServiceDep,
    ):
        """List pending approvals."""
        _ensure_permission(user, Permission.APPROVAL_READ)

        session_uuid = None
        if session_id:
            try:
                session_uuid = UUID(session_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid session ID format") from None

        approvals = await service.get_pending_approvals(session_uuid)

        return [
            {
                "id": str(a.id),
                "session_id": str(a.session_id),
                "stage_name": a.stage_name,
                "state": a.state.value,
                "requested_by": a.requested_by,
                "requested_at": a.requested_at.isoformat(),
            }
            for a in approvals
        ]

    @app.get("/approvals/{approval_id}")
    async def get_approval(
        approval_id: str,
        user: str = "api-user",
        *,
        service: ApprovalServiceDep,
    ):
        """Get approval details."""
        _ensure_permission(user, Permission.APPROVAL_READ)

        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        summary = await service.get_approval_summary(uuid)
        if not summary:
            raise HTTPException(status_code=404, detail="Approval not found")

        return summary

    @app.post("/approvals/{approval_id}/claim")
    async def claim_approval(
        approval_id: str,
        request: ClaimRequest,
        service: ApprovalServiceDep,
    ):
        """Claim an approval for review."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        approval = await service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        _ensure_permission(request.user, Permission.APPROVAL_APPROVE)
        if not service.is_approver(approval, request.user):
            raise HTTPException(status_code=403, detail="User is not allowed to claim this approval")

        updated = await service.claim(
            approval_id=uuid,
            claimed_by=request.user,
        )
        if not updated:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot claim approval in state '{approval.state.value}'",
            )

        return {
            "id": approval_id,
            "state": updated.state.value,
            "claimed_by": request.user,
        }

    @app.post("/approvals/{approval_id}/request-changes")
    async def request_approval_changes(
        approval_id: str,
        request: RequestChangesRequest,
        service: ApprovalServiceDep,
    ):
        """Request changes and send approval back to pending."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        approval = await service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        _ensure_permission(request.user, Permission.APPROVAL_REJECT)
        if not service.is_approver(approval, request.user):
            raise HTTPException(
                status_code=403,
                detail="User is not allowed to request changes for this approval",
            )

        updated = await service.request_changes(
            approval_id=uuid,
            requested_by=request.user,
            message=request.message,
        )
        if not updated:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot request changes in state '{approval.state.value}'",
            )

        return {
            "id": approval_id,
            "state": updated.state.value,
            "requested_by": request.user,
            "message": request.message,
        }

    @app.post("/approvals/{approval_id}/escalate")
    async def escalate_approval(
        approval_id: str,
        request: EscalationRequest,
        service: ApprovalServiceDep,
    ):
        """Escalate an approval."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        approval = await service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        _ensure_permission(request.user, Permission.APPROVAL_APPROVE)
        if not service.is_approver(approval, request.user):
            raise HTTPException(
                status_code=403,
                detail="User is not allowed to escalate this approval",
            )

        updated = await service.escalate(
            approval_id=uuid,
            escalated_by=request.user,
            reason=request.reason,
        )
        if not updated:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot escalate approval in state '{approval.state.value}'",
            )

        return {
            "id": approval_id,
            "state": updated.state.value,
            "escalated_by": request.user,
            "reason": request.reason,
        }

    @app.post("/approvals/{approval_id}/cancel")
    async def cancel_approval(
        approval_id: str,
        request: CancelRequest,
        service: ApprovalServiceDep,
    ):
        """Cancel an approval."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        approval = await service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        _ensure_permission(request.user, Permission.APPROVAL_REJECT)
        if not service.can_cancel(approval, request.user):
            raise HTTPException(
                status_code=403,
                detail="User is not allowed to cancel this approval",
            )

        updated = await service.cancel(
            approval_id=uuid,
            cancelled_by=request.user,
            reason=request.reason,
        )
        if not updated:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel approval in state '{approval.state.value}'",
            )

        return {
            "id": approval_id,
            "state": updated.state.value,
            "cancelled_by": request.user,
            "reason": request.reason,
        }

    @app.post("/approvals/{approval_id}/remind")
    async def remind_approval(
        approval_id: str,
        request: RemindRequest,
        service: ApprovalServiceDep,
    ):
        """Send reminder for a pending approval."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        approval = await service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        _ensure_permission(request.user, Permission.APPROVAL_READ)
        if not service.is_approver(approval, request.user):
            raise HTTPException(
                status_code=403,
                detail="User is not allowed to send reminders for this approval",
            )

        updated = await service.remind(
            approval_id=uuid,
            reminded_by=request.user,
            message=request.message,
        )
        if not updated:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot remind approval in state '{approval.state.value}'",
            )

        return {
            "id": approval_id,
            "state": updated.state.value,
            "reminded_by": request.user,
            "message": request.message,
        }

    @app.post("/approvals/{approval_id}/approve")
    async def approve(
        approval_id: str,
        request: ApprovalRequest,
        approval_service: ApprovalServiceDep,
        session_service: SessionServiceDep,
    ):
        """Approve a request."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        approval = await approval_service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        _ensure_permission(request.user, Permission.APPROVAL_APPROVE)
        if not approval_service.is_approver(approval, request.user):
            raise HTTPException(status_code=403, detail="User is not allowed to approve this request")

        result = await session_service.approve_stage(
            approval.session_id,
            approval.stage_id,
            request.user,
            request.message,
        )
        if "error" in result:
            _raise_service_error(result["error"])

        updated = await approval_service.get_approval(uuid)
        return {
            "id": approval_id,
            "state": updated.state.value if updated else "approved",
            "approved_by": request.user,
        }

    @app.post("/approvals/{approval_id}/reject")
    async def reject(
        approval_id: str,
        request: RejectionRequest,
        approval_service: ApprovalServiceDep,
        session_service: SessionServiceDep,
    ):
        """Reject a request."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        approval = await approval_service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        _ensure_permission(request.user, Permission.APPROVAL_REJECT)
        if not approval_service.is_approver(approval, request.user):
            raise HTTPException(status_code=403, detail="User is not allowed to reject this request")

        result = await session_service.reject_stage(
            approval.session_id,
            approval.stage_id,
            request.user,
            request.reason,
        )
        if "error" in result:
            _raise_service_error(result["error"])

        updated = await approval_service.get_approval(uuid)
        return {
            "id": approval_id,
            "state": updated.state.value if updated else "rejected",
            "rejected_by": request.user,
        }

    @app.post("/approvals/{approval_id}/comments")
    async def add_comment(
        approval_id: str,
        request: AddCommentRequest,
        service: ApprovalServiceDep,
    ):
        """Add comment to an approval."""
        _ensure_permission(request.author, Permission.APPROVAL_READ)

        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format") from None

        updated = await service.add_comment(
            approval_id=uuid,
            author=request.author,
            content=request.content,
            is_internal=request.is_internal,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Approval not found")

        return {
            "id": str(updated.id),
            "comment_count": len(updated.comments),
            "last_comment_author": request.author,
        }

    return app


# Create app instance for uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
