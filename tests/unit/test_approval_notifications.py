"""Tests for approval notification hooks."""

import asyncio
from uuid import uuid4

import pytest
from core.config.settings import get_settings
from core.services.approval_service import ApprovalService
from core.storage.database import create_database


@pytest.fixture
async def approval_service(tmp_path):
    """Create approval service with temporary database."""
    db = create_database(f"sqlite+aiosqlite:///{tmp_path}/approval_notifications.db")
    await db.create_tables()
    service = ApprovalService(db)
    try:
        yield service
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_approval_lifecycle_emits_notifications(approval_service, monkeypatch) -> None:
    events: list[str] = []

    async def fake_notify(event, record, actor="", message=""):
        del record, actor, message
        events.append(event)

    monkeypatch.setattr(approval_service, "_send_notification", fake_notify)

    approval = await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        approvers=["tech_lead"],
    )
    await approval_service.approve(approval.id, approved_by="tech_lead", message="ok")

    assert events == ["approval.created", "approval.approved"]


@pytest.mark.asyncio
async def test_timeout_emits_notification(approval_service, monkeypatch) -> None:
    events: list[str] = []

    async def fake_notify(event, record, actor="", message=""):
        del record, actor, message
        events.append(event)

    monkeypatch.setattr(approval_service, "_send_notification", fake_notify)

    await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        timeout_hours=0,
    )

    await asyncio.sleep(0.01)
    timed_out = await approval_service.check_timeouts()

    assert len(timed_out) == 1
    assert "approval.created" in events
    assert "approval.timed_out" in events


@pytest.mark.asyncio
async def test_timeout_auto_escalates_when_enabled(approval_service, monkeypatch) -> None:
    events: list[str] = []

    async def fake_notify(event, record, actor="", message=""):
        del record, actor, message
        events.append(event)

    monkeypatch.setattr(approval_service, "_send_notification", fake_notify)
    monkeypatch.setenv("HITL_AUTO_ESCALATE_ON_TIMEOUT", "true")
    monkeypatch.setenv("HITL_AUTO_REJECT_ON_TIMEOUT", "false")
    get_settings.cache_clear()

    approval = await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        timeout_hours=0,
    )

    await asyncio.sleep(0.01)
    await approval_service.check_timeouts()
    updated = await approval_service.get_approval(approval.id)

    assert updated is not None
    assert updated.state.value == "escalated"
    assert "approval.auto_escalated" in events

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_timeout_reminder_emits_before_expiry(approval_service, monkeypatch) -> None:
    events: list[str] = []

    async def fake_notify(event, record, actor="", message=""):
        del record, actor, message
        events.append(event)

    monkeypatch.setattr(approval_service, "_send_notification", fake_notify)
    monkeypatch.setenv("HITL_REMINDER_HOURS_BEFORE_TIMEOUT", "2")
    monkeypatch.setenv("HITL_AUTO_ESCALATE_ON_TIMEOUT", "false")
    monkeypatch.setenv("HITL_AUTO_REJECT_ON_TIMEOUT", "false")
    get_settings.cache_clear()

    approval = await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        timeout_hours=1,
    )

    await approval_service.check_timeouts()
    updated = await approval_service.get_approval(approval.id)

    assert updated is not None
    assert updated.metadata.get("timeout_reminder_sent") is True
    assert "approval.timeout_reminder" in events

    get_settings.cache_clear()
