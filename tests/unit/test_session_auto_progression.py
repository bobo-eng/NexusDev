"""Tests for approval-driven stage auto progression."""

from uuid import UUID

import pytest
from core.agents.architect_agent import ArchitectAgent
from core.agents.coder_agent import CoderAgent
from core.agents.pm_agent import PMAgent
from core.schemas.agent_outputs import CodingOutput, RequirementAnalysisOutput, SystemDesignOutput
from core.services.session_service import SessionService
from core.storage.database import create_database


@pytest.fixture
def patch_agent_execution(monkeypatch):
    """Patch agent execution to deterministic outputs for workflow tests."""

    async def fake_pm_execute(self, context):
        return RequirementAnalysisOutput(summary="Requirement analyzed")

    async def fake_architect_execute(self, context):
        return SystemDesignOutput(
            overview="System design complete",
            architecture_style="monolith",
            components=[],
        )

    async def fake_coder_execute(self, context):
        return CodingOutput(files=[])

    monkeypatch.setattr(PMAgent, "execute", fake_pm_execute)
    monkeypatch.setattr(ArchitectAgent, "execute", fake_architect_execute)
    monkeypatch.setattr(CoderAgent, "execute", fake_coder_execute)


@pytest.fixture
async def session_service(tmp_path):
    """Create a session service backed by a temporary database."""
    db = create_database(f"sqlite+aiosqlite:///{tmp_path}/auto_progression.db")
    await db.create_tables()
    service = SessionService(db)
    try:
        yield service
    finally:
        await db.close()


async def _setup_waiting_approval_session(service: SessionService) -> tuple[UUID, UUID]:
    """Create session and advance to system design waiting approval."""
    session = await service.create_session(
        name="Auto progression test",
        requirement="Build a simple REST API",
    )

    requirement_result = await service.run_stage(session.id)
    assert requirement_result["stage_type"] == "requirement_analysis"

    design_result = await service.run_stage(session.id)
    assert design_result["stage_type"] == "system_design"
    assert design_result["status"] == "waiting_approval"

    return session.id, UUID(design_result["stage_id"])


@pytest.mark.asyncio
async def test_approve_stage_does_not_auto_advance_by_default(
    session_service: SessionService,
    patch_agent_execution,
    monkeypatch,
) -> None:
    monkeypatch.delenv("HITL_AUTO_ADVANCE_AFTER_APPROVAL", raising=False)
    session_id, stage_id = await _setup_waiting_approval_session(session_service)

    result = await session_service.approve_stage(
        session_id=session_id,
        stage_id=stage_id,
        approved_by="tech_lead",
        comment="Looks good",
    )

    assert result["status"] == "approved"
    assert "next_stage" not in result
    assert "next_stage_error" not in result

    status = await session_service.get_status(session_id)
    assert len(status["stages"]) == 2
    assert status["status"] == "approved"


@pytest.mark.asyncio
async def test_approve_stage_auto_advances_when_enabled(
    session_service: SessionService,
    patch_agent_execution,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HITL_AUTO_ADVANCE_AFTER_APPROVAL", "true")
    session_id, stage_id = await _setup_waiting_approval_session(session_service)

    result = await session_service.approve_stage(
        session_id=session_id,
        stage_id=stage_id,
        approved_by="tech_lead",
        comment="Proceed",
    )

    assert result["status"] == "approved"
    assert "next_stage" in result
    assert result["next_stage"]["stage_type"] == "coding"
    assert result["next_stage"]["status"] == "completed"

    status = await session_service.get_status(session_id)
    stage_types = [stage["type"] for stage in status["stages"]]
    assert stage_types == ["requirement_analysis", "system_design", "coding"]
    assert status["status"] == "running"
