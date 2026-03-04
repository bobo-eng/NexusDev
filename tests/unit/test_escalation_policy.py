"""Tests for role/level escalation policy."""

from uuid import uuid4

import pytest
from core.config.settings import get_settings
from core.services.approval_service import ApprovalService
from core.storage.database import create_database


@pytest.fixture
async def approval_service(tmp_path):
    """Create approval service with temporary database."""
    db = create_database(f"sqlite+aiosqlite:///{tmp_path}/escalation_policy.db")
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
        "HITL_ESCALATION_POLICY_ENABLED",
        "HITL_ESCALATION_LEVELS",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_escalation_routes_to_next_role_targets(
    approval_service: ApprovalService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Escalation should route approvers to the next configured role."""
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("RBAC_DEFAULT_ROLE", "viewer")
    monkeypatch.setenv(
        "RBAC_USER_ROLES",
        "lead:tech_lead,admin_user:admin,dev_user:developer",
    )
    monkeypatch.setenv("HITL_ESCALATION_POLICY_ENABLED", "true")
    monkeypatch.setenv("HITL_ESCALATION_LEVELS", "developer,tech_lead,admin")
    get_settings.cache_clear()

    approval = await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        approvers=["lead", "admin_user"],
    )

    updated = await approval_service.escalate(
        approval_id=approval.id,
        escalated_by="lead",
        reason="Needs admin decision",
    )

    assert updated is not None
    assert updated.state.value == "escalated"
    assert updated.metadata["approvers"] == ["admin_user"]
    assert updated.metadata["escalation_level"] == 2

    policy = updated.metadata.get("escalation_policy")
    assert policy is not None
    assert policy["from_role"] == "tech_lead"
    assert policy["to_role"] == "admin"
    assert policy["targets"] == ["admin_user"]

    assert approval_service.is_approver(updated, "admin_user") is True
    assert approval_service.is_approver(updated, "lead") is False

    approved = await approval_service.approve(
        approval_id=approval.id,
        approved_by="admin_user",
        message="approved",
    )
    assert approved is not None
    assert approved.state.value == "approved"


@pytest.mark.asyncio
async def test_escalation_policy_disabled_keeps_approvers(
    approval_service: ApprovalService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabling escalation policy should preserve original approvers."""
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("RBAC_DEFAULT_ROLE", "viewer")
    monkeypatch.setenv(
        "RBAC_USER_ROLES",
        "lead:tech_lead,admin_user:admin",
    )
    monkeypatch.setenv("HITL_ESCALATION_POLICY_ENABLED", "false")
    get_settings.cache_clear()

    approval = await approval_service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        approvers=["lead", "admin_user"],
    )

    updated = await approval_service.escalate(
        approval_id=approval.id,
        escalated_by="lead",
        reason="manual",
    )

    assert updated is not None
    assert updated.state.value == "escalated"
    assert updated.metadata["approvers"] == ["lead", "admin_user"]
    assert "escalation_policy" not in updated.metadata
