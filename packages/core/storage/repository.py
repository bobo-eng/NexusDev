"""Repository pattern for data access.

Provides clean abstraction over database operations.
"""

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.artifact import Artifact
from core.domain.review import Review
from core.domain.session import Session
from core.domain.stage import Stage
from core.hitl.approval_sm import ApprovalComment, ApprovalRecord, ApprovalState
from core.storage.models import (
    ApprovalRecordModel,
    ArtifactModel,
    ReviewModel,
    SessionModel,
    StageModel,
)

T = TypeVar("T")
M = TypeVar("M")


class BaseRepository(Generic[T, M]):
    """Base repository with common CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, id: UUID) -> T | None:
        """Get entity by ID."""
        raise NotImplementedError

    async def create(self, entity: T) -> T:
        """Create new entity."""
        raise NotImplementedError

    async def update(self, entity: T) -> T:
        """Update existing entity."""
        raise NotImplementedError

    async def delete(self, id: UUID) -> bool:
        """Delete entity by ID."""
        raise NotImplementedError


class SessionRepository(BaseRepository[Session, SessionModel]):
    """Repository for Session entities."""

    async def get_by_id(self, id: UUID) -> Session | None:
        """Get session by ID."""
        result = await self.session.execute(select(SessionModel).where(SessionModel.id == id))
        model = result.scalar_one_or_none()
        return Session.model_validate(model) if model else None

    async def get_by_status(self, status: str) -> list[Session]:
        """Get sessions by status."""
        result = await self.session.execute(
            select(SessionModel).where(SessionModel.status == status)
        )
        models = result.scalars().all()
        return [Session.model_validate(m) for m in models]

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[Session]:
        """Get all sessions with pagination."""
        result = await self.session.execute(
            select(SessionModel)
            .order_by(SessionModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        models = result.scalars().all()
        return [Session.model_validate(m) for m in models]

    async def create(self, entity: Session) -> Session:
        """Create new session."""
        model = SessionModel(
            id=entity.id,
            name=entity.name,
            description=entity.description,
            status=entity.status.value,
            requirement=entity.requirement,
            context=entity.context,
            current_stage_id=entity.current_stage_id,
            completed_stages=[str(stage_id) for stage_id in entity.completed_stages],
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            completed_at=entity.completed_at,
            created_by=entity.created_by,
            sop_config=entity.sop_config,
            model_config_name=entity.model_config_name,
        )
        self.session.add(model)
        await self.session.flush()
        return entity

    async def update(self, entity: Session) -> Session:
        """Update existing session."""
        result = await self.session.execute(
            select(SessionModel).where(SessionModel.id == entity.id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.name = entity.name
            model.description = entity.description
            model.status = entity.status.value
            model.context = entity.context
            model.current_stage_id = entity.current_stage_id
            model.completed_stages = [str(stage_id) for stage_id in entity.completed_stages]
            model.updated_at = entity.updated_at
            model.completed_at = entity.completed_at
            await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        """Delete session by ID."""
        result = await self.session.execute(select(SessionModel).where(SessionModel.id == id))
        model = result.scalar_one_or_none()
        if model:
            await self.session.delete(model)
            await self.session.flush()
            return True
        return False


class StageRepository(BaseRepository[Stage, StageModel]):
    """Repository for Stage entities."""

    async def get_by_id(self, id: UUID) -> Stage | None:
        """Get stage by ID."""
        result = await self.session.execute(select(StageModel).where(StageModel.id == id))
        model = result.scalar_one_or_none()
        return Stage.model_validate(model) if model else None

    async def get_by_session(self, session_id: UUID) -> list[Stage]:
        """Get all stages for a session."""
        result = await self.session.execute(
            select(StageModel)
            .where(StageModel.session_id == session_id)
            .order_by(StageModel.sequence)
        )
        models = result.scalars().all()
        return [Stage.model_validate(m) for m in models]

    async def create(self, entity: Stage) -> Stage:
        """Create new stage."""
        model = StageModel(
            id=entity.id,
            session_id=entity.session_id,
            name=entity.name,
            stage_type=entity.stage_type.value,
            description=entity.description,
            status=entity.status.value,
            agent_name=entity.agent_name,
            sequence=entity.sequence,
            input_artifact_ids=[str(artifact_id) for artifact_id in entity.input_artifact_ids],
            output_artifact_ids=[str(artifact_id) for artifact_id in entity.output_artifact_ids],
            review_ids=[str(review_id) for review_id in entity.review_ids],
            context=entity.context,
            result=entity.result,
            error_message=entity.error_message,
            retry_count=entity.retry_count,
            max_retries=entity.max_retries,
            created_at=entity.created_at,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            requires_approval=entity.requires_approval,
            approved_by=entity.approved_by,
            approved_at=entity.approved_at,
            approval_comment=entity.approval_comment,
        )
        self.session.add(model)
        await self.session.flush()
        return entity

    async def update(self, entity: Stage) -> Stage:
        """Update existing stage."""
        result = await self.session.execute(select(StageModel).where(StageModel.id == entity.id))
        model = result.scalar_one_or_none()
        if model:
            model.name = entity.name
            model.status = entity.status.value
            model.output_artifact_ids = [
                str(artifact_id) for artifact_id in entity.output_artifact_ids
            ]
            model.review_ids = [str(review_id) for review_id in entity.review_ids]
            model.context = entity.context
            model.result = entity.result
            model.error_message = entity.error_message
            model.retry_count = entity.retry_count
            model.started_at = entity.started_at
            model.completed_at = entity.completed_at
            model.approved_by = entity.approved_by
            model.approved_at = entity.approved_at
            model.approval_comment = entity.approval_comment
            await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        """Delete stage by ID."""
        result = await self.session.execute(select(StageModel).where(StageModel.id == id))
        model = result.scalar_one_or_none()
        if model:
            await self.session.delete(model)
            await self.session.flush()
            return True
        return False


class ArtifactRepository(BaseRepository[Artifact, ArtifactModel]):
    """Repository for Artifact entities."""

    async def get_by_id(self, id: UUID) -> Artifact | None:
        """Get artifact by ID."""
        result = await self.session.execute(select(ArtifactModel).where(ArtifactModel.id == id))
        model = result.scalar_one_or_none()
        return Artifact.model_validate(model) if model else None

    async def get_by_session(self, session_id: UUID) -> list[Artifact]:
        """Get all artifacts for a session."""
        result = await self.session.execute(
            select(ArtifactModel)
            .where(ArtifactModel.session_id == session_id)
            .order_by(ArtifactModel.created_at)
        )
        models = result.scalars().all()
        return [Artifact.model_validate(m) for m in models]

    async def get_by_stage(self, stage_id: UUID) -> list[Artifact]:
        """Get all artifacts for a stage."""
        result = await self.session.execute(
            select(ArtifactModel)
            .where(ArtifactModel.stage_id == stage_id)
            .order_by(ArtifactModel.created_at)
        )
        models = result.scalars().all()
        return [Artifact.model_validate(m) for m in models]

    async def create(self, entity: Artifact) -> Artifact:
        """Create new artifact."""
        model = ArtifactModel(
            id=entity.id,
            session_id=entity.session_id,
            stage_id=entity.stage_id,
            name=entity.name,
            artifact_type=entity.artifact_type.value,
            description=entity.description,
            content=entity.content,
            content_type=entity.content_type,
            file_path=entity.file_path,
            file_size=entity.file_size,
            checksum=entity.checksum,
            language=entity.language,
            meta=entity.metadata,
            version=entity.version,
            previous_version_id=entity.previous_version_id,
            parent_artifact_ids=entity.parent_artifact_ids,
            derived_artifact_ids=entity.derived_artifact_ids,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            created_by=entity.created_by,
            is_validated=entity.is_validated,
            validation_result=entity.validation_result,
        )
        self.session.add(model)
        await self.session.flush()
        return entity

    async def update(self, entity: Artifact) -> Artifact:
        """Update existing artifact."""
        result = await self.session.execute(
            select(ArtifactModel).where(ArtifactModel.id == entity.id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.name = entity.name
            model.content = entity.content
            model.file_path = entity.file_path
            model.file_size = entity.file_size
            model.checksum = entity.checksum
            model.meta = entity.metadata
            model.version = entity.version
            model.updated_at = entity.updated_at
            model.is_validated = entity.is_validated
            model.validation_result = entity.validation_result
            await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        """Delete artifact by ID."""
        result = await self.session.execute(select(ArtifactModel).where(ArtifactModel.id == id))
        model = result.scalar_one_or_none()
        if model:
            await self.session.delete(model)
            await self.session.flush()
            return True
        return False


class ReviewRepository(BaseRepository[Review, ReviewModel]):
    """Repository for Review entities."""

    async def get_by_id(self, id: UUID) -> Review | None:
        """Get review by ID."""
        result = await self.session.execute(select(ReviewModel).where(ReviewModel.id == id))
        model = result.scalar_one_or_none()
        return Review.model_validate(model) if model else None

    async def get_by_session(self, session_id: UUID) -> list[Review]:
        """Get all reviews for a session."""
        result = await self.session.execute(
            select(ReviewModel)
            .where(ReviewModel.session_id == session_id)
            .order_by(ReviewModel.created_at)
        )
        models = result.scalars().all()
        return [Review.model_validate(m) for m in models]

    async def get_by_stage(self, stage_id: UUID) -> list[Review]:
        """Get all reviews for a stage."""
        result = await self.session.execute(
            select(ReviewModel)
            .where(ReviewModel.stage_id == stage_id)
            .order_by(ReviewModel.created_at)
        )
        models = result.scalars().all()
        return [Review.model_validate(m) for m in models]

    async def create(self, entity: Review) -> Review:
        """Create new review."""
        model = ReviewModel(
            id=entity.id,
            session_id=entity.session_id,
            stage_id=entity.stage_id,
            artifact_ids=entity.artifact_ids,
            review_type=entity.review_type.value,
            reviewer=entity.reviewer,
            status=entity.status.value,
            comments=[c.model_dump() for c in entity.comments],
            summary=entity.summary,
            quality_score=entity.quality_score,
            security_score=entity.security_score,
            performance_score=entity.performance_score,
            maintainability_score=entity.maintainability_score,
            total_issues=entity.total_issues,
            critical_issues=entity.critical_issues,
            major_issues=entity.major_issues,
            minor_issues=entity.minor_issues,
            created_at=entity.created_at,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            meta=entity.metadata,
        )
        self.session.add(model)
        await self.session.flush()
        return entity

    async def update(self, entity: Review) -> Review:
        """Update existing review."""
        result = await self.session.execute(select(ReviewModel).where(ReviewModel.id == entity.id))
        model = result.scalar_one_or_none()
        if model:
            model.status = entity.status.value
            model.comments = [c.model_dump() for c in entity.comments]
            model.summary = entity.summary
            model.quality_score = entity.quality_score
            model.security_score = entity.security_score
            model.performance_score = entity.performance_score
            model.maintainability_score = entity.maintainability_score
            model.total_issues = entity.total_issues
            model.critical_issues = entity.critical_issues
            model.major_issues = entity.major_issues
            model.minor_issues = entity.minor_issues
            model.completed_at = entity.completed_at
            await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        """Delete review by ID."""
        result = await self.session.execute(select(ReviewModel).where(ReviewModel.id == id))
        model = result.scalar_one_or_none()
        if model:
            await self.session.delete(model)
            await self.session.flush()
            return True
        return False


class ApprovalRepository(BaseRepository[ApprovalRecord, ApprovalRecordModel]):
    """Repository for ApprovalRecord entities."""

    async def get_by_id(self, id: UUID) -> ApprovalRecord | None:
        """Get approval record by ID."""
        result = await self.session.execute(
            select(ApprovalRecordModel).where(ApprovalRecordModel.id == id)
        )
        model = result.scalar_one_or_none()
        return self._model_to_record(model) if model else None

    async def get_by_session(self, session_id: UUID) -> list[ApprovalRecord]:
        """Get all approval records for a session."""
        result = await self.session.execute(
            select(ApprovalRecordModel)
            .where(ApprovalRecordModel.session_id == session_id)
            .order_by(ApprovalRecordModel.requested_at)
        )
        models = result.scalars().all()
        return [self._model_to_record(m) for m in models if m]

    async def get_by_stage(self, stage_id: UUID) -> list[ApprovalRecord]:
        """Get all approval records for a stage."""
        result = await self.session.execute(
            select(ApprovalRecordModel)
            .where(ApprovalRecordModel.stage_id == stage_id)
            .order_by(ApprovalRecordModel.requested_at)
        )
        models = result.scalars().all()
        return [self._model_to_record(m) for m in models if m]

    async def get_by_state(
        self,
        state: str,
        session_id: UUID | None = None,
    ) -> list[ApprovalRecord]:
        """Get approval records by state."""
        query = select(ApprovalRecordModel).where(ApprovalRecordModel.state == state)
        if session_id:
            query = query.where(ApprovalRecordModel.session_id == session_id)

        result = await self.session.execute(query)
        models = result.scalars().all()
        return [self._model_to_record(m) for m in models if m]

    async def list_records(
        self,
        state: str | None = None,
        session_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApprovalRecord]:
        """List approval records with optional filtering and pagination."""
        query = select(ApprovalRecordModel)
        if state:
            query = query.where(ApprovalRecordModel.state == state)
        if session_id:
            query = query.where(ApprovalRecordModel.session_id == session_id)

        query = query.order_by(ApprovalRecordModel.requested_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(query)
        models = result.scalars().all()
        return [self._model_to_record(m) for m in models if m]

    async def create(self, entity: ApprovalRecord) -> ApprovalRecord:
        """Create new approval record."""
        model = ApprovalRecordModel(
            id=entity.id,
            session_id=entity.session_id,
            stage_id=entity.stage_id,
            stage_name=entity.stage_name,
            artifact_ids=entity.artifact_ids,
            state=entity.state.value,
            requested_by=entity.requested_by,
            requested_at=entity.requested_at,
            request_message=entity.request_message,
            approved_by=entity.approved_by,
            approved_at=entity.approved_at,
            approval_message=entity.approval_message,
            rejected_by=entity.rejected_by,
            rejected_at=entity.rejected_at,
            rejection_reason=entity.rejection_reason,
            timeout_at=entity.timeout_at,
            comments=self._serialize_comments(entity.comments),
            history=entity.history,
            meta=entity.metadata,
        )
        self.session.add(model)
        await self.session.flush()
        return entity

    async def update(self, entity: ApprovalRecord) -> ApprovalRecord:
        """Update existing approval record."""
        result = await self.session.execute(
            select(ApprovalRecordModel).where(ApprovalRecordModel.id == entity.id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.state = entity.state.value
            model.approved_by = entity.approved_by
            model.approved_at = entity.approved_at
            model.approval_message = entity.approval_message
            model.rejected_by = entity.rejected_by
            model.rejected_at = entity.rejected_at
            model.rejection_reason = entity.rejection_reason
            model.comments = self._serialize_comments(entity.comments)
            model.history = entity.history
            model.meta = entity.metadata
            await self.session.flush()
        return entity

    async def delete(self, id: UUID) -> bool:
        """Delete approval record by ID."""
        result = await self.session.execute(
            select(ApprovalRecordModel).where(ApprovalRecordModel.id == id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self.session.delete(model)
            await self.session.flush()
            return True
        return False

    def _model_to_record(self, model: ApprovalRecordModel | None) -> ApprovalRecord | None:
        """Convert database model to domain entity."""
        if not model:
            return None

        state = (
            ApprovalState(model.state)
            if model.state in ApprovalState._value2member_map_
            else ApprovalState.PENDING
        )

        record = ApprovalRecord(
            id=UUID(str(model.id)),
            session_id=UUID(str(model.session_id)),
            stage_id=UUID(str(model.stage_id)),
            stage_name=model.stage_name,
            artifact_ids=[UUID(str(a)) for a in model.artifact_ids],
            state=state,
            requested_by=model.requested_by,
            requested_at=model.requested_at,
            request_message=model.request_message,
            approved_by=model.approved_by,
            approved_at=model.approved_at,
            approval_message=model.approval_message,
            rejected_by=model.rejected_by,
            rejected_at=model.rejected_at,
            rejection_reason=model.rejection_reason,
            timeout_at=model.timeout_at,
            comments=self._deserialize_comments(model.comments or []),
            history=model.history or [],
            metadata=model.meta or {},
        )
        return record

    def _serialize_comments(
        self,
        comments: list[ApprovalComment | dict],
    ) -> list[dict]:
        """Serialize approval comments for database storage."""
        serialized: list[dict] = []
        for comment in comments:
            if isinstance(comment, ApprovalComment):
                serialized.append(
                    {
                        "id": str(comment.id),
                        "author": comment.author,
                        "content": comment.content,
                        "created_at": comment.created_at.isoformat(),
                        "is_internal": comment.is_internal,
                    }
                )
                continue
            if isinstance(comment, dict):
                item = dict(comment)
                if "id" in item:
                    item["id"] = str(item["id"])
                if "created_at" in item and hasattr(item["created_at"], "isoformat"):
                    item["created_at"] = item["created_at"].isoformat()
                serialized.append(item)
        return serialized

    def _deserialize_comments(self, comments: list[dict]) -> list[ApprovalComment]:
        """Deserialize approval comments from database format."""
        from datetime import datetime
        from uuid import uuid4

        deserialized: list[ApprovalComment] = []
        for comment in comments:
            if isinstance(comment, ApprovalComment):
                deserialized.append(comment)
                continue
            if not isinstance(comment, dict):
                continue

            created_at_raw = comment.get("created_at")
            created_at = datetime.utcnow()
            if isinstance(created_at_raw, str):
                try:
                    created_at = datetime.fromisoformat(created_at_raw)
                except ValueError:
                    created_at = datetime.utcnow()

            comment_id = comment.get("id")
            parsed_id = UUID(str(comment_id)) if comment_id else uuid4()

            deserialized.append(
                ApprovalComment(
                    id=parsed_id,
                    author=comment.get("author", ""),
                    content=comment.get("content", ""),
                    created_at=created_at,
                    is_internal=bool(comment.get("is_internal", False)),
                )
            )
        return deserialized
