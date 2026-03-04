"""Tests for runtime workflow mode switching."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core.domain.session import SessionStatus
from core.domain.stage import StageStatus
from core.services.session_service import SessionService
from core.storage.database import create_database
from core.workflow.graph import DevelopmentState


@pytest.fixture
async def session_service(tmp_path):
    """Create a session service with temporary database."""
    db = create_database(f"sqlite+aiosqlite:///{tmp_path}/workflow_mode.db")
    await db.create_tables()
    service = SessionService(db)
    try:
        yield service
    finally:
        await db.close()


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
