"""FastAPI application for NexusDev API.

Provides REST endpoints for:
- Session management
- Stage execution
- Approval workflow
- Status queries
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from uuid import UUID

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field

from core.domain.session import SessionStatus
from core.services.session_service import SessionService
from core.services.approval_service import ApprovalService
import os
from core.storage.database import Database, create_database


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
        service: SessionService = Depends(get_session_service),
    ):
        """Create a new development session."""
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
        service: SessionService = Depends(get_session_service),
    ):
        """Get session status."""
        try:
            uuid = UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session ID format")
        
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
        service: SessionService = Depends(get_session_service),
    ):
        """List sessions."""
        session_status = None
        if status:
            try:
                session_status = SessionStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid status")
        
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
        service: SessionService = Depends(get_session_service),
    ):
        """Run a workflow stage.
        
        Set background=true to run asynchronously and return immediately.
        """
        try:
            uuid = UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid session ID format")
        
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
        service: SessionService = Depends(get_session_service),
    ):
        """Approve a pending stage."""
        try:
            session_uuid = UUID(session_id)
            stage_uuid = UUID(stage_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ID format")
        
        result = await service.approve_stage(
            session_uuid,
            stage_uuid,
            request.user,
            request.message,
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
    
    @app.post("/sessions/{session_id}/stages/{stage_id}/reject")
    async def reject_stage(
        session_id: str,
        stage_id: str,
        request: RejectionRequest,
        service: SessionService = Depends(get_session_service),
    ):
        """Reject a pending stage."""
        try:
            session_uuid = UUID(session_id)
            stage_uuid = UUID(stage_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ID format")
        
        result = await service.reject_stage(
            session_uuid,
            stage_uuid,
            request.user,
            request.reason,
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
    
    # Approval endpoints
    @app.get("/approvals")
    async def list_approvals(
        session_id: str | None = None,
        service: ApprovalService = Depends(get_approval_service),
    ):
        """List pending approvals."""
        session_uuid = None
        if session_id:
            try:
                session_uuid = UUID(session_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid session ID format")
        
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
    
    @app.post("/approvals/{approval_id}/approve")
    async def approve(
        approval_id: str,
        request: ApprovalRequest,
        approval_service: ApprovalService = Depends(get_approval_service),
        session_service: SessionService = Depends(get_session_service),
    ):
        """Approve a request."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format")

        approval = await approval_service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")

        result = await session_service.approve_stage(
            approval.session_id,
            approval.stage_id,
            request.user,
            request.message,
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

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
        approval_service: ApprovalService = Depends(get_approval_service),
        session_service: SessionService = Depends(get_session_service),
    ):
        """Reject a request."""
        try:
            uuid = UUID(approval_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid approval ID format")

        approval = await approval_service.get_approval(uuid)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")

        result = await session_service.reject_stage(
            approval.session_id,
            approval.stage_id,
            request.user,
            request.reason,
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        updated = await approval_service.get_approval(uuid)
        return {
            "id": approval_id,
            "state": updated.state.value if updated else "rejected",
            "rejected_by": request.user,
        }
    
    return app


# Create app instance for uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
