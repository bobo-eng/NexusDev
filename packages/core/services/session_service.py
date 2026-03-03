"""Session service - main orchestration interface.

This is the primary interface exposed to CLI and API layers.
"""

import logging
import os
import time
from typing import Any
from uuid import UUID

from core.agents.base import AgentConfig
from core.config.settings import get_settings, load_sop_config
from core.domain.session import Session, SessionStatus
from core.domain.stage import Stage, StageStatus, StageType
from core.observability.metrics import get_metrics
from core.security.rbac import Permission, get_rbac
from core.sop.sop_engine import SOPConfig, SOPEngine
from core.storage.database import Database
from core.storage.repository import SessionRepository, StageRepository
from core.workflow.graph import create_development_graph

logger = logging.getLogger(__name__)


def load_default_sop_config() -> SOPConfig:
    """Load SOP config from YAML with safe fallback."""
    try:
        return SOPConfig.from_dict(load_sop_config())
    except Exception as exc:
        logger.warning(f"Failed to load SOP config from YAML: {exc}. Using default MVP SOP.")
        return SOPEngine(SOPConfig()).create_default_mvp_sop()


def _parse_bool(value: str | None) -> bool | None:
    """Parse a boolean string value."""
    if value is None:
        return None

    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None


class SessionService:
    """Service for managing development sessions.

    Provides high-level operations:
    - create_session: Create new session
    - run_stage: Execute a workflow stage
    - approve_stage: Approve a pending stage
    - reject_stage: Reject a pending stage
    - get_status: Get session status
    """

    def __init__(self, database: Database, sop_config: SOPConfig | None = None):
        self.database = database
        if sop_config is None:
            sop_config = load_default_sop_config()
        self.sop_engine = SOPEngine(sop_config)
        self.workflow_graph = create_development_graph(self.sop_engine)

    async def create_session(
        self,
        name: str,
        requirement: str,
        description: str = "",
        created_by: str = "anonymous",
        context: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new development session.

        Args:
            name: Session name
            requirement: User requirement
            description: Optional description
            created_by: User creating the session
            context: Additional context

        Returns:
            Created session
        """
        session = Session(
            name=name,
            description=description,
            requirement=requirement,
            created_by=created_by,
            context=context or {},
        )

        async with self.database.session() as db_session:
            repo = SessionRepository(db_session)
            await repo.create(session)

        logger.info(f"[Session {session.id}] Created session '{name}'")
        return session

    async def get_session(self, session_id: UUID) -> Session | None:
        """Get session by ID."""
        async with self.database.session() as db_session:
            repo = SessionRepository(db_session)
            return await repo.get_by_id(session_id)

    async def get_status(self, session_id: UUID) -> dict[str, Any]:
        """Get comprehensive session status."""
        async with self.database.session() as db_session:
            session_repo = SessionRepository(db_session)
            stage_repo = StageRepository(db_session)

            session = await session_repo.get_by_id(session_id)
            if not session:
                return {"error": "Session not found"}

            stages = await stage_repo.get_by_session(session_id)

            return {
                "session_id": str(session_id),
                "name": session.name,
                "status": session.status.value,
                "current_stage_id": str(session.current_stage_id)
                if session.current_stage_id
                else None,
                "completed_stages": [str(s) for s in session.completed_stages],
                "stages": [
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "type": s.stage_type.value,
                        "status": s.status.value,
                        "agent": s.agent_name,
                    }
                    for s in stages
                ],
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
            }

    async def run_stage(
        self,
        session_id: UUID,
        stage_type: StageType | str | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow stage.

        This method is idempotent - calling it multiple times with the same
        session_id and stage_type will not create duplicate stages.

        Args:
            session_id: Session UUID
            stage_type: Specific stage type to run (auto-detected if None)

        Returns:
            Execution result
        """
        stage: Stage | None = None
        session: Session | None = None
        stage_def: Any | None = None

        async with self.database.session() as db_session:
            session_repo = SessionRepository(db_session)
            stage_repo = StageRepository(db_session)

            session = await session_repo.get_by_id(session_id)
            if not session:
                return {"error": "Session not found"}

            if not session.is_active():
                return {"error": f"Session is not active (status: {session.status.value})"}

            existing_stages = await stage_repo.get_by_session(session_id)

            # Parse explicit stage type if provided
            if stage_type is not None:
                parsed_stage_type = self._parse_stage_type(stage_type)
                if not parsed_stage_type:
                    return {"error": f"Unknown stage type: {stage_type}"}
                stage_type = parsed_stage_type

            # Determine stage to run
            if stage_type is None:
                stage_type = self._determine_next_stage_type(existing_stages)

            # Get stage definition
            stage_def = self._get_stage_definition(stage_type)
            if not stage_def:
                return {"error": f"Unknown stage type: {stage_type}"}

            # Check for existing stage (idempotency)
            for existing in existing_stages:
                if existing.stage_type == stage_type and existing.status in [
                    StageStatus.PENDING,
                    StageStatus.RUNNING,
                    StageStatus.WAITING_APPROVAL,
                ]:
                    logger.info(f"[Session {session_id}] Stage {stage_type.value} already exists with status {existing.status.value}")
                    
                    # If PENDING, execute it (may have failed before)
                    if existing.status == StageStatus.PENDING:
                        logger.info(f"[Session {session_id}] Executing pending stage {existing.name}")
                        stage = existing
                        # Execute outside the creation transaction
                        return await self._execute_workflow(session, stage, stage_def)
                    
                    # If RUNNING but no context/result (stuck), re-execute
                    if existing.status == StageStatus.RUNNING:
                        if not existing.context or not existing.result:
                            logger.warning(f"[Session {session_id}] Stage {existing.name} is stuck (no context/result), re-executing")
                            stage = existing
                            return await self._execute_workflow(session, stage, stage_def)
                    
                    # If RUNNING or WAITING_APPROVAL, just return status
                    return {
                        "session_id": str(session_id),
                        "stage_id": str(existing.id),
                        "stage_name": existing.name,
                        "stage_type": stage_type.value,
                        "status": existing.status.value,
                        "requires_approval": existing.requires_approval,
                        "message": f"Stage is {existing.status.value}",
                    }

            # Create stage
            stage = Stage(
                session_id=session_id,
                name=stage_def.name,
                stage_type=stage_type,
                description=stage_def.description,
                agent_name=stage_def.agent_name,
                sequence=len(existing_stages),
                max_retries=stage_def.max_retries,
                requires_approval=stage_def.requires_approval,
            )

            await stage_repo.create(stage)

            # Update session
            session.current_stage_id = stage.id
            session.mark_running()
            await session_repo.update(session)

            logger.info(
                f"[Session {session_id}] Created stage {stage.name} (requires_approval={stage.requires_approval})"
            )

        if not session or not stage or not stage_def:
            return {"error": "Failed to initialize stage execution"}

        # Execute the workflow outside of creation transaction to avoid DB locks
        return await self._execute_workflow(session, stage, stage_def)

    async def _execute_workflow(
        self,
        session: Session,
        stage: Stage,
        stage_def: Any,
    ) -> dict[str, Any]:
        """Execute the LangGraph workflow for a stage.

        Args:
            session: Session entity
            stage: Stage entity
            stage_def: Stage definition from SOP

        Returns:
            Execution result
        """
        from core.agents.architect_agent import ArchitectAgent
        from core.agents.coder_agent import CoderAgent
        from core.agents.pm_agent import PMAgent
        from core.agents.reviewer_agent import ReviewerAgent
        from core.agents.tester_agent import TesterAgent
        from core.services.approval_service import ApprovalService

        # Start stage
        stage.start()
        async with self.database.session() as db_session:
            await StageRepository(db_session).update(stage)

        start_time = time.perf_counter()
        metrics = get_metrics()

        try:
            # Build execution context
            context = await self._build_execution_context(session, stage)

            # Execute agent
            logger.info(
                f"[Session {session.id}] Executing {stage.agent_name} for stage {stage.name}"
            )

            agent_map = {
                "pm_agent": PMAgent,
                "architect_agent": ArchitectAgent,
                "coder_agent": CoderAgent,
                "reviewer_agent": ReviewerAgent,
                "tester_agent": TesterAgent,
            }

            agent_class = agent_map.get(stage.agent_name)
            if not agent_class:
                raise ValueError(f"Unknown agent: {stage.agent_name}")

            agent = agent_class(config=self._build_agent_config(stage.agent_name))
            result = await agent.execute(context)

            # Store result
            stage.result = result.model_dump()

            # Check if approval required
            if stage.requires_approval:
                stage.wait_for_approval()
                session.mark_waiting_approval()

                # Create approval request
                approval_service = ApprovalService(self.database)
                approval = await approval_service.create_approval(
                    session_id=session.id,
                    stage_id=stage.id,
                    stage_name=stage.name,
                    requested_by="system",
                    request_message=f"Please review {stage.name} output",
                    timeout_hours=stage_def.approval_timeout_hours if stage_def else 24,
                    approvers=stage_def.approvers if stage_def else None,
                )

                async with self.database.session() as db_session:
                    await StageRepository(db_session).update(stage)
                    await SessionRepository(db_session).update(session)

                logger.info(
                    f"[Session {session.id}] Stage {stage.name} waiting for approval (approval_id={approval.id})"
                )

                metrics.record_stage(
                    stage_type=stage.stage_type.value,
                    agent_name=stage.agent_name,
                    success=True,
                    execution_time_ms=(time.perf_counter() - start_time) * 1000,
                    retry_count=stage.retry_count,
                )

                return {
                    "session_id": str(session.id),
                    "stage_id": str(stage.id),
                    "stage_name": stage.name,
                    "stage_type": stage.stage_type.value,
                    "status": "waiting_approval",
                    "requires_approval": True,
                    "approval_id": str(approval.id),
                    "result": stage.result,
                }
            else:
                # Complete stage
                stage.complete()
                self._mark_stage_completed(session, stage.id)
                if stage.stage_type == StageType.TESTING:
                    session.mark_completed()
                else:
                    session.mark_running()

                async with self.database.session() as db_session:
                    await StageRepository(db_session).update(stage)
                    await SessionRepository(db_session).update(session)

                logger.info(f"[Session {session.id}] Stage {stage.name} completed")

                metrics.record_stage(
                    stage_type=stage.stage_type.value,
                    agent_name=stage.agent_name,
                    success=True,
                    execution_time_ms=(time.perf_counter() - start_time) * 1000,
                    retry_count=stage.retry_count,
                )

                return {
                    "session_id": str(session.id),
                    "stage_id": str(stage.id),
                    "stage_name": stage.name,
                    "stage_type": stage.stage_type.value,
                    "status": "completed",
                    "requires_approval": False,
                    "result": stage.result,
                }

        except Exception as e:
            logger.error(f"[Session {session.id}] Stage {stage.name} failed: {e}")
            stage.fail(str(e))
            session.mark_failed()

            async with self.database.session() as db_session:
                await StageRepository(db_session).update(stage)
                await SessionRepository(db_session).update(session)

            metrics.record_stage(
                stage_type=stage.stage_type.value,
                agent_name=stage.agent_name,
                success=False,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
                retry_count=stage.retry_count,
                error_type=type(e).__name__,
            )

            return {
                "session_id": str(session.id),
                "stage_id": str(stage.id),
                "stage_name": stage.name,
                "stage_type": stage.stage_type.value,
                "status": "failed",
                "error": str(e),
            }

    async def _build_execution_context(
        self,
        session: Session,
        stage: Stage,
    ) -> dict[str, Any]:
        """Build execution context for agent."""
        context: dict[str, Any] = {
            "requirement": session.requirement,
            "session_context": session.context,
        }

        # Load previous stage outputs
        async with self.database.session() as db_session:
            stage_repo = StageRepository(db_session)
            all_stages = await stage_repo.get_by_session(session.id)

            for s in all_stages:
                if s.id != stage.id and s.result:
                    if s.stage_type.value == "requirement_analysis":
                        context["requirements"] = s.result
                    elif s.stage_type.value == "system_design":
                        context["design"] = s.result
                    elif s.stage_type.value == "coding":
                        context["code"] = s.result
                    elif s.stage_type.value == "code_review":
                        context["review"] = s.result

        return context

    async def approve_stage(
        self,
        session_id: UUID,
        stage_id: UUID,
        approved_by: str,
        comment: str = "",
    ) -> dict[str, Any]:
        """Approve a pending stage."""
        if not get_rbac().check_permission(approved_by, Permission.APPROVAL_APPROVE):
            return {"error": f"Permission denied for user '{approved_by}' to approve stages"}

        from core.services.approval_service import ApprovalService

        stage_name = ""
        approval_service = ApprovalService(self.database)
        async with self.database.session() as db_session:
            session_repo = SessionRepository(db_session)
            stage_repo = StageRepository(db_session)

            session = await session_repo.get_by_id(session_id)
            if not session:
                return {"error": "Session not found"}

            if not session.can_approve():
                return {"error": f"Session cannot be approved (status: {session.status.value})"}

            stage = await stage_repo.get_by_id(stage_id)
            if not stage:
                return {"error": "Stage not found"}

            if stage.status != StageStatus.WAITING_APPROVAL:
                return {
                    "error": f"Stage is not waiting for approval (status: {stage.status.value})"
                }

            approvals = await approval_service.get_stage_approvals(stage_id)
            pending = next((approval for approval in approvals if approval.is_pending()), None)
            if pending:
                if not approval_service.is_approver(pending, approved_by):
                    return {
                        "error": f"User '{approved_by}' is not allowed to approve this stage"
                    }
                approval_result = await approval_service.approve(pending.id, approved_by, comment)
                if not approval_result:
                    return {"error": f"Approval record {pending.id} cannot be approved"}

            # Approve stage
            stage.approve(approved_by, comment)
            await stage_repo.update(stage)
            stage_name = stage.name

            # Update session
            self._mark_stage_completed(session, stage.id)
            session.mark_approved()
            await session_repo.update(session)

        logger.info(
            f"[Session {session_id}] Stage {stage_name or stage_id} approved by {approved_by}"
        )
        response: dict[str, Any] = {
            "session_id": str(session_id),
            "stage_id": str(stage_id),
            "status": "approved",
            "approved_by": approved_by,
            "message": comment,
        }

        if self._should_auto_advance_after_approval():
            next_stage_result = await self.run_stage(session_id)
            if "error" in next_stage_result:
                logger.warning(
                    f"[Session {session_id}] Auto-advance failed after approval: "
                    f"{next_stage_result['error']}"
                )
                response["next_stage_error"] = next_stage_result["error"]
            else:
                response["next_stage"] = next_stage_result

        return response

    async def reject_stage(
        self,
        session_id: UUID,
        stage_id: UUID,
        rejected_by: str,
        reason: str = "",
    ) -> dict[str, Any]:
        """Reject a pending stage."""
        if not get_rbac().check_permission(rejected_by, Permission.APPROVAL_REJECT):
            return {"error": f"Permission denied for user '{rejected_by}' to reject stages"}

        from core.services.approval_service import ApprovalService

        stage_name = ""
        approval_service = ApprovalService(self.database)
        async with self.database.session() as db_session:
            session_repo = SessionRepository(db_session)
            stage_repo = StageRepository(db_session)

            session = await session_repo.get_by_id(session_id)
            if not session:
                return {"error": "Session not found"}

            if not session.can_reject():
                return {"error": f"Session cannot be rejected (status: {session.status.value})"}

            stage = await stage_repo.get_by_id(stage_id)
            if not stage:
                return {"error": "Stage not found"}

            if stage.status != StageStatus.WAITING_APPROVAL:
                return {
                    "error": f"Stage is not waiting for approval (status: {stage.status.value})"
                }

            approvals = await approval_service.get_stage_approvals(stage_id)
            pending = next((approval for approval in approvals if approval.is_pending()), None)
            if pending:
                if not approval_service.is_approver(pending, rejected_by):
                    return {
                        "error": f"User '{rejected_by}' is not allowed to reject this stage"
                    }
                rejection_result = await approval_service.reject(pending.id, rejected_by, reason)
                if not rejection_result:
                    return {"error": f"Approval record {pending.id} cannot be rejected"}

            # Reject stage
            stage.reject(rejected_by, reason)
            await stage_repo.update(stage)
            stage_name = stage.name

            # Update session
            session.mark_rejected()
            await session_repo.update(session)

        logger.info(
            f"[Session {session_id}] Stage {stage_name or stage_id} rejected by {rejected_by}"
        )

        return {
            "session_id": str(session_id),
            "stage_id": str(stage_id),
            "status": "rejected",
            "rejected_by": rejected_by,
            "reason": reason,
        }

    async def list_sessions(
        self,
        status: SessionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Session]:
        """List sessions with optional filtering."""
        async with self.database.session() as db_session:
            repo = SessionRepository(db_session)
            if status:
                return await repo.get_by_status(status.value)
            else:
                # Get all sessions with pagination
                return await repo.get_all(limit=limit, offset=offset)

    def _determine_next_stage_type(self, stages: list[Stage]) -> StageType:
        """Determine the next stage type based on session progress."""
        if not stages:
            return StageType.REQUIREMENT_ANALYSIS

        ordered_stages = sorted(
            stages,
            key=lambda stage: (stage.sequence, stage.created_at),
        )
        latest = ordered_stages[-1]

        if latest.status == StageStatus.REJECTED:
            stage_def = self.sop_engine.config.get_stage(latest.stage_type.value)
            retry_stage = self._stage_name_to_type(stage_def.on_reject if stage_def else None)
            if retry_stage:
                return retry_stage

        if latest.status == StageStatus.FAILED:
            stage_def = self.sop_engine.config.get_stage(latest.stage_type.value)
            retry_stage = self._stage_name_to_type(stage_def.on_failure if stage_def else None)
            if retry_stage:
                return retry_stage
            return latest.stage_type

        stage_order = [
            StageType.REQUIREMENT_ANALYSIS,
            StageType.SYSTEM_DESIGN,
            StageType.CODING,
            StageType.CODE_REVIEW,
            StageType.TESTING,
        ]

        completed_types = {
            stage.stage_type
            for stage in ordered_stages
            if stage.status in {StageStatus.COMPLETED, StageStatus.APPROVED}
        }

        for candidate in stage_order:
            if candidate not in completed_types:
                return candidate

        return StageType.TESTING

    def _parse_stage_type(self, stage_type: StageType | str) -> StageType | None:
        """Parse user-provided stage type value."""
        if isinstance(stage_type, StageType):
            return stage_type

        value = stage_type.strip()
        try:
            return StageType(value)
        except ValueError:
            pass

        try:
            return StageType[value.upper()]
        except KeyError:
            return None

    def _stage_name_to_type(self, stage_name: str | None) -> StageType | None:
        """Convert SOP stage name to StageType."""
        stage_map = {
            "requirement_analysis": StageType.REQUIREMENT_ANALYSIS,
            "system_design": StageType.SYSTEM_DESIGN,
            "coding": StageType.CODING,
            "code_review": StageType.CODE_REVIEW,
            "testing": StageType.TESTING,
        }
        if not stage_name:
            return None
        return stage_map.get(stage_name)

    def _mark_stage_completed(self, session: Session, stage_id: UUID) -> None:
        """Track completed stage on session without duplicates."""
        if stage_id not in session.completed_stages:
            session.completed_stages.append(stage_id)

    def _build_agent_config(self, agent_name: str) -> AgentConfig:
        """Build runtime agent config with provider/model from environment."""
        provider = self._resolve_provider()

        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            base_url = os.getenv("ANTHROPIC_BASE_URL")
            model_name = (
                os.getenv("NEXUSDEV_LLM_MODEL")
                or os.getenv("ANTHROPIC_MODEL")
                or "claude-3-5-haiku-latest"
            )
        else:
            provider = "openai"
            api_key = os.getenv("OPENAI_API_KEY")
            base_url = os.getenv("OPENAI_BASE_URL")
            model_name = (
                os.getenv("NEXUSDEV_LLM_MODEL")
                or os.getenv("OPENAI_MODEL")
                or os.getenv("AGENT_MODEL", "MiniMax-M2.5")
            )

        temperature_map = {
            "pm_agent": 0.3,
            "architect_agent": 0.2,
            "coder_agent": 0.1,
            "reviewer_agent": 0.1,
            "tester_agent": 0.2,
        }

        return AgentConfig(
            name=agent_name,
            description=f"Runtime config for {agent_name}",
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            temperature=temperature_map.get(agent_name, 0.2),
        )

    def _should_auto_advance_after_approval(self) -> bool:
        """Check whether to auto-run the next stage after approval."""
        env_value = _parse_bool(os.getenv("HITL_AUTO_ADVANCE_AFTER_APPROVAL"))
        if env_value is not None:
            return env_value

        try:
            return bool(get_settings().hitl.auto_advance_after_approval)
        except Exception:
            return False

    def _resolve_provider(self) -> str:
        """Resolve provider in priority order: explicit -> OpenAI key -> Anthropic key."""
        explicit = os.getenv("NEXUSDEV_LLM_PROVIDER")
        if explicit:
            return explicit.strip().lower()

        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "openai"

    def _get_stage_definition(self, stage_type: StageType) -> Any:
        """Get stage definition from SOP."""
        stage_map = {
            StageType.REQUIREMENT_ANALYSIS: self.sop_engine.config.get_stage(
                "requirement_analysis"
            ),
            StageType.SYSTEM_DESIGN: self.sop_engine.config.get_stage("system_design"),
            StageType.CODING: self.sop_engine.config.get_stage("coding"),
            StageType.CODE_REVIEW: self.sop_engine.config.get_stage("code_review"),
            StageType.TESTING: self.sop_engine.config.get_stage("testing"),
        }
        return stage_map.get(stage_type)
