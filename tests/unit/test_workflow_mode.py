"""Tests for runtime workflow mode switching."""

from unittest.mock import AsyncMock
from uuid import uuid4

import core.workflow.nodes as workflow_nodes
import pytest
from core.agents.architect_agent import ArchitectAgent
from core.agents.pm_agent import PMAgent
from core.domain.session import SessionStatus
from core.domain.stage import StageStatus
from core.schemas.agent_outputs import RequirementAnalysisOutput, SystemDesignOutput
from core.services.approval_service import ApprovalService
from core.services.session_service import SessionService
from core.storage.database import create_database
from core.workflow.graph import DevelopmentState


@pytest.fixture
async def session_service(tmp_path):
    """Create a session service with temporary database."""
    db_path = tmp_path / "workflow_mode.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    db = create_database(database_url)
    await db.create_tables()
    if workflow_nodes._workflow_db is not None:
        await workflow_nodes._workflow_db.close()
    workflow_nodes._workflow_db = None
    service = SessionService(db)
    try:
        yield service
    finally:
        await db.close()
        if workflow_nodes._workflow_db is not None:
            await workflow_nodes._workflow_db.close()
        workflow_nodes._workflow_db = None


@pytest.mark.asyncio
async def test_run_stage_defaults_to_single_stage_mode(session_service: SessionService) -> None:
    session_id = uuid4()
    run_single_stage = AsyncMock(return_value={"status": "completed"})
    run_full_graph = AsyncMock(return_value={"status": "running"})

    session_service._run_single_stage = run_single_stage
    session_service._run_full_graph = run_full_graph

    result = await session_service.run_stage(session_id)

    run_single_stage.assert_awaited_once_with(session_id, None)
    run_full_graph.assert_not_awaited()
    assert result["mode"] == "single_stage"


@pytest.mark.asyncio
async def test_run_stage_uses_full_graph_from_env(
    session_service: SessionService, monkeypatch
) -> None:
    monkeypatch.setenv("NEXUSDEV_WORKFLOW_MODE", "full_graph")
    session_id = uuid4()
    run_single_stage = AsyncMock(return_value={"status": "completed"})
    run_full_graph = AsyncMock(return_value={"status": "running"})

    session_service._run_single_stage = run_single_stage
    session_service._run_full_graph = run_full_graph

    result = await session_service.run_stage(session_id)

    run_full_graph.assert_awaited_once_with(session_id)
    run_single_stage.assert_not_awaited()
    assert result["mode"] == "full_graph"


@pytest.mark.asyncio
async def test_run_stage_rejects_invalid_mode(session_service: SessionService) -> None:
    result = await session_service.run_stage(uuid4(), mode="invalid")

    assert "error" in result
    assert "Unknown workflow mode" in result["error"]


@pytest.mark.asyncio
async def test_run_stage_rejects_stage_type_with_full_graph(
    session_service: SessionService,
) -> None:
    result = await session_service.run_stage(
        uuid4(),
        stage_type="coding",
        mode="full_graph",
    )

    assert "error" in result
    assert "stage_type is only supported in single_stage mode" in result["error"]


@pytest.mark.asyncio
async def test_full_graph_mode_updates_session_status(session_service: SessionService) -> None:
    session = await session_service.create_session(
        name="Full graph mode",
        requirement="Build a TODO API",
    )

    class DummyGraph:
        async def ainvoke(self, state):
            del state
            return DevelopmentState(
                session_id=session.id,
                current_stage="testing",
                stage_status=StageStatus.COMPLETED,
                session_status=SessionStatus.COMPLETED,
                requirements={"summary": "done"},
                tests={"recommendation": "PASS"},
            ).model_dump()

    session_service.workflow_graph = DummyGraph()

    result = await session_service.run_stage(session.id, mode="full_graph")

    assert result["mode"] == "full_graph"
    assert result["status"] == "completed"
    assert result["stage_status"] == "completed"
    assert result["outputs"]["requirements"]["summary"] == "done"

    status = await session_service.get_status(session.id)
    assert status["status"] == "completed"
    assert [stage["type"] for stage in status["stages"]] == [
        "requirement_analysis",
        "testing",
    ]


@pytest.mark.asyncio
async def test_full_graph_mode_persists_waiting_approval_and_creates_approval(
    session_service: SessionService,
    monkeypatch,
) -> None:
    async def fake_pm_execute(self, context):
        del context
        return RequirementAnalysisOutput(summary="Requirement analyzed")

    async def fake_architect_execute(self, context):
        del context
        return SystemDesignOutput(
            overview="System design complete",
            architecture_style="monolith",
            components=[],
        )

    monkeypatch.setattr(PMAgent, "execute", fake_pm_execute)
    monkeypatch.setattr(ArchitectAgent, "execute", fake_architect_execute)

    session = await session_service.create_session(
        name="Full graph waiting approval",
        requirement="Build a task system",
    )

    result = await session_service.run_stage(session.id, mode="full_graph")

    assert result["mode"] == "full_graph"
    assert result["status"] == "waiting_approval"
    assert result["requires_approval"] is True
    assert result["stage_status"] == "waiting_approval"
    assert "approval_id" in result

    status = await session_service.get_status(session.id)
    assert status["status"] == "waiting_approval"
    assert [stage["type"] for stage in status["stages"]] == [
        "requirement_analysis",
        "system_design",
    ]
    assert [stage["status"] for stage in status["stages"]] == [
        "completed",
        "waiting_approval",
    ]

    approval_service = ApprovalService(session_service.database)
    approvals = await approval_service.get_session_approvals(session.id)
    assert len(approvals) == 1
    assert str(approvals[0].id) == result["approval_id"]
