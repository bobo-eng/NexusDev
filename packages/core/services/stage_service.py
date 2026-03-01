"""Stage service for stage execution and management."""

from typing import Any
from uuid import UUID

from core.domain.stage import Stage, StageStatus
from core.storage.database import Database
from core.storage.repository import StageRepository, ArtifactRepository


class StageService:
    """Service for managing individual stages."""
    
    def __init__(self, database: Database):
        self.database = database
    
    async def get_stage(self, stage_id: UUID) -> Stage | None:
        """Get stage by ID."""
        async with self.database.session() as db_session:
            repo = StageRepository(db_session)
            return await repo.get_by_id(stage_id)
    
    async def get_session_stages(self, session_id: UUID) -> list[Stage]:
        """Get all stages for a session."""
        async with self.database.session() as db_session:
            repo = StageRepository(db_session)
            return await repo.get_by_session(session_id)
    
    async def update_stage_status(
        self,
        stage_id: UUID,
        status: StageStatus,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> Stage | None:
        """Update stage status and result."""
        async with self.database.session() as db_session:
            repo = StageRepository(db_session)
            stage = await repo.get_by_id(stage_id)
            
            if not stage:
                return None
            
            # Update status
            if status == StageStatus.RUNNING:
                stage.start()
            elif status == StageStatus.COMPLETED:
                stage.complete()
            elif status == StageStatus.FAILED and error_message:
                stage.fail(error_message)
            
            if result:
                stage.result = result
            
            await repo.update(stage)
            return stage
    
    async def add_stage_artifact(
        self,
        stage_id: UUID,
        artifact_id: UUID,
    ) -> bool:
        """Add artifact to stage outputs."""
        async with self.database.session() as db_session:
            repo = StageRepository(db_session)
            stage = await repo.get_by_id(stage_id)
            
            if not stage:
                return False
            
            stage.add_output_artifact(artifact_id)
            await repo.update(stage)
            return True
    
    async def retry_stage(self, stage_id: UUID) -> Stage | None:
        """Retry a failed stage."""
        async with self.database.session() as db_session:
            repo = StageRepository(db_session)
            stage = await repo.get_by_id(stage_id)
            
            if not stage:
                return None
            
            if not stage.can_retry():
                return None
            
            stage.increment_retry()
            stage.status = StageStatus.PENDING
            stage.error_message = None
            
            await repo.update(stage)
            return stage
    
    async def get_stage_outputs(
        self,
        stage_id: UUID,
    ) -> dict[str, Any]:
        """Get stage outputs including artifacts."""
        async with self.database.session() as db_session:
            stage_repo = StageRepository(db_session)
            artifact_repo = ArtifactRepository(db_session)
            
            stage = await stage_repo.get_by_id(stage_id)
            if not stage:
                return {"error": "Stage not found"}
            
            artifacts = []
            for artifact_id in stage.output_artifact_ids:
                artifact = await artifact_repo.get_by_id(artifact_id)
                if artifact:
                    artifacts.append({
                        "id": str(artifact.id),
                        "name": artifact.name,
                        "type": artifact.artifact_type.value,
                        "summary": artifact.get_summary(200),
                    })
            
            return {
                "stage_id": str(stage_id),
                "stage_name": stage.name,
                "status": stage.status.value,
                "result": stage.result,
                "artifacts": artifacts,
            }
