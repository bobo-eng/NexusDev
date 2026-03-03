"""Integration tests for metrics collection wiring."""

import asyncio
from uuid import uuid4

import pytest
from core.agents.pm_agent import PMAgent
from core.observability.metrics import get_metrics
from core.schemas.agent_outputs import RequirementAnalysisOutput
from core.services.approval_service import ApprovalService
from core.services.session_service import SessionService
from core.storage.database import create_database


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset global metrics before and after each test."""
    metrics = get_metrics()
    metrics.reset()
    yield
    metrics.reset()


@pytest.fixture
async def database(tmp_path):
    """Create a temporary database for service tests."""
    db = create_database(f"sqlite+aiosqlite:///{tmp_path}/metrics.db")
    await db.create_tables()
    try:
        yield db
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_session_service_records_stage_success_metrics(database, monkeypatch) -> None:
    async def fake_pm_execute(self, context):
        return RequirementAnalysisOutput(summary="ok")

    monkeypatch.setattr(PMAgent, "execute", fake_pm_execute)

    service = SessionService(database)
    session = await service.create_session(
        name="Metrics success",
        requirement="Analyze requirement",
    )

    result = await service.run_stage(session.id)
    assert result["status"] == "completed"

    metrics = get_metrics().get_all_metrics()
    assert metrics["total_stages"] == 1
    assert metrics["overall_success_rate"] == 1.0
    assert metrics["agents"]["pm_agent"]["total_calls"] == 1


@pytest.mark.asyncio
async def test_session_service_records_stage_failure_metrics(database, monkeypatch) -> None:
    async def fake_pm_execute(self, context):
        raise RuntimeError("boom")

    monkeypatch.setattr(PMAgent, "execute", fake_pm_execute)

    service = SessionService(database)
    session = await service.create_session(
        name="Metrics failure",
        requirement="Analyze requirement",
    )

    result = await service.run_stage(session.id)
    assert result["status"] == "failed"

    metrics = get_metrics().get_all_metrics()
    assert metrics["total_stages"] == 1
    assert metrics["overall_success_rate"] == 0.0
    assert metrics["agents"]["pm_agent"]["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_approval_service_records_approval_metrics(database) -> None:
    service = ApprovalService(database)

    approval = await service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
    )
    await service.approve(approval.id, approved_by="tech_lead", message="ok")

    stats = get_metrics().get_approval_stats()
    assert stats["total_requests"] == 1
    assert stats["approved"] == 1
    assert stats["rejected"] == 0
    assert stats["timed_out"] == 0


@pytest.mark.asyncio
async def test_approval_service_records_rejection_metrics(database) -> None:
    service = ApprovalService(database)

    approval = await service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
    )
    await service.reject(approval.id, rejected_by="tech_lead", reason="changes needed")

    stats = get_metrics().get_approval_stats()
    assert stats["total_requests"] == 1
    assert stats["approved"] == 0
    assert stats["rejected"] == 1
    assert stats["timed_out"] == 0


@pytest.mark.asyncio
async def test_approval_service_records_timeout_metrics(database) -> None:
    service = ApprovalService(database)

    await service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        timeout_hours=0,
    )

    await asyncio.sleep(0.01)
    timed_out = await service.check_timeouts()
    assert len(timed_out) == 1

    stats = get_metrics().get_approval_stats()
    assert stats["total_requests"] == 1
    assert stats["approved"] == 0
    assert stats["rejected"] == 0
    assert stats["timed_out"] == 1
