"""Tests for workflow wait-for-approval node behavior."""

import asyncio
from uuid import uuid4

import core.workflow.nodes as workflow_nodes
import pytest
from core.domain.session import SessionStatus
from core.domain.stage import StageStatus
from core.services.approval_service import ApprovalService
from core.storage.database import create_database
from core.workflow.graph import DevelopmentState
from core.workflow.nodes import wait_for_approval_node


@pytest.fixture
async def approval_service(tmp_path, monkeypatch):
    """Create approval service and align workflow node DB to the same sqlite file."""
    db_path = tmp_path / "workflow_wait_node.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("HITL_AUTO_ESCALATE_ON_TIMEOUT", "false")
    monkeypatch.setenv("HITL_AUTO_REJECT_ON_TIMEOUT", "false")

    if workflow_nodes._workflow_db is not None:
        await workflow_nodes._workflow_db.close()
    workflow_nodes._workflow_db = None

    db = create_database(database_url)
    await db.create_tables()

    try:
        yield ApprovalService(db)
    finally:
        await db.close()
        if workflow_nodes._workflow_db is not None:
            await workflow_nodes._workflow_db.close()
        workflow_nodes._workflow_db = None


@pytest.mark.asyncio
async def test_wait_node_keeps_waiting_when_pending(approval_service: ApprovalService) -> None:
    approval = await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
    )

    state = DevelopmentState(
        session_id=approval.session_id,
        approval_record_id=approval.id,
        stage_status=StageStatus.WAITING_APPROVAL,
        session_status=SessionStatus.WAITING_APPROVAL,
    )

    updated = await wait_for_approval_node(state)

    assert updated.stage_status == StageStatus.WAITING_APPROVAL
    assert updated.session_status == SessionStatus.WAITING_APPROVAL
    assert updated.approval_decision is None


@pytest.mark.asyncio
async def test_wait_node_proceeds_when_approved(approval_service: ApprovalService) -> None:
    approval = await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
    )
    await approval_service.approve(approval.id, approved_by="tech_lead", message="ok")

    state = DevelopmentState(
        session_id=approval.session_id,
        approval_record_id=approval.id,
        stage_status=StageStatus.WAITING_APPROVAL,
        session_status=SessionStatus.WAITING_APPROVAL,
    )

    updated = await wait_for_approval_node(state)

    assert updated.stage_status == StageStatus.APPROVED
    assert updated.session_status == SessionStatus.APPROVED
    assert updated.approval_decision == "approved"


@pytest.mark.asyncio
async def test_wait_node_fails_when_timed_out(approval_service: ApprovalService) -> None:
    approval = await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        timeout_hours=0,
    )

    await asyncio.sleep(0.01)
    await approval_service.check_timeouts()

    state = DevelopmentState(
        session_id=approval.session_id,
        approval_record_id=approval.id,
        stage_status=StageStatus.WAITING_APPROVAL,
        session_status=SessionStatus.WAITING_APPROVAL,
    )

    updated = await wait_for_approval_node(state)

    assert updated.stage_status == StageStatus.FAILED
    assert updated.session_status == SessionStatus.FAILED
    assert "timed_out" in updated.error_message
