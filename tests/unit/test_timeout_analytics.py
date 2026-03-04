"""Tests for approval timeout analytics."""

import asyncio
from uuid import uuid4

import pytest
from core.config.settings import get_settings
from core.services.approval_service import ApprovalService
from core.storage.database import create_database


@pytest.fixture
async def approval_service(tmp_path):
    """Create approval service with temporary database."""
    db = create_database(f"sqlite+aiosqlite:///{tmp_path}/timeout_analytics.db")
    await db.create_tables()
    service = ApprovalService(db)
    try:
        yield service
    finally:
        await db.close()


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch):
    """Reset env state across tests."""
    keys = [
        "RBAC_ENABLED",
        "RBAC_DEFAULT_ROLE",
        "RBAC_USER_ROLES",
        "HITL_AUTO_ESCALATE_ON_TIMEOUT",
        "HITL_AUTO_REJECT_ON_TIMEOUT",
        "HITL_ESCALATION_POLICY_ENABLED",
        "HITL_ESCALATION_LEVELS",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_timeout_analytics_aggregates_stage_and_role(
    approval_service: ApprovalService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout analytics should aggregate counts/rates by stage and role."""
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("RBAC_DEFAULT_ROLE", "viewer")
    monkeypatch.setenv(
        "RBAC_USER_ROLES",
        "system:admin,lead:tech_lead,admin_user:admin",
    )
    monkeypatch.setenv("HITL_ESCALATION_POLICY_ENABLED", "true")
    monkeypatch.setenv("HITL_ESCALATION_LEVELS", "developer,tech_lead,admin")
    monkeypatch.setenv("HITL_AUTO_ESCALATE_ON_TIMEOUT", "false")
    monkeypatch.setenv("HITL_AUTO_REJECT_ON_TIMEOUT", "false")
    get_settings.cache_clear()

    # Not timed out (control sample)
    await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        timeout_hours=24,
        approvers=["lead"],
    )

    # Timed out directly
    await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        timeout_hours=0,
        approvers=["lead"],
    )
    await asyncio.sleep(0.01)
    await approval_service.check_timeouts()

    # Timed out then auto-escalated
    monkeypatch.setenv("HITL_AUTO_ESCALATE_ON_TIMEOUT", "true")
    monkeypatch.setenv("HITL_AUTO_REJECT_ON_TIMEOUT", "false")
    get_settings.cache_clear()
    await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="code_review",
        requested_by="system",
        timeout_hours=0,
        approvers=["lead", "admin_user"],
    )
    await asyncio.sleep(0.01)
    await approval_service.check_timeouts()

    analytics = await approval_service.get_timeout_analytics(days=1)

    assert analytics["total_records"] == 3
    assert analytics["timeout_related_count"] == 2
    assert analytics["auto_escalated_count"] == 1
    assert analytics["timeout_rate"] == pytest.approx(2 / 3)
    assert analytics["avg_wait_hours_before_timeout"] >= 0.0

    stage_map = {item["stage_name"]: item for item in analytics["by_stage"]}
    assert stage_map["system_design"]["total"] == 2
    assert stage_map["system_design"]["timeout_related"] == 1
    assert stage_map["code_review"]["total"] == 1
    assert stage_map["code_review"]["timeout_related"] == 1

    role_map = {item["role"]: item for item in analytics["by_role"]}
    assert "tech_lead" in role_map
    assert role_map["tech_lead"]["timeout_related"] == 2
