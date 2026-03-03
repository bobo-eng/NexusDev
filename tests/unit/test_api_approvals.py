"""API tests for approval endpoints."""

from uuid import uuid4

import pytest
from core.services.approval_service import ApprovalService
from httpx import ASGITransport, AsyncClient

import apps.api.main as api_main


@pytest.fixture
async def api_client(tmp_path, monkeypatch):
    """Create isolated API client with a temporary SQLite database."""
    db_path = tmp_path / "api_approvals.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    if api_main._db is not None:
        await api_main._db.close()
    api_main._db = None

    transport = ASGITransport(app=api_main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    if api_main._db is not None:
        await api_main._db.close()
    api_main._db = None


async def _seed_approval(approvers: list[str] | None = None) -> str:
    db = await api_main.get_db()
    service = ApprovalService(db)
    approval = await service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        request_message="Please review design output",
        timeout_hours=24,
        approvers=approvers,
    )
    return str(approval.id)


@pytest.mark.asyncio
async def test_get_approval_detail(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval()

    response = await api_client.get(f"/approvals/{approval_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == approval_id
    assert data["stage_name"] == "system_design"
    assert data["state"] == "pending"


@pytest.mark.asyncio
async def test_get_approval_detail_not_found(api_client: AsyncClient) -> None:
    response = await api_client.get(f"/approvals/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Approval not found"


@pytest.mark.asyncio
async def test_add_approval_comment(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval()

    response = await api_client.post(
        f"/approvals/{approval_id}/comments",
        json={
            "author": "tech_lead",
            "content": "Please add cache invalidation notes.",
            "is_internal": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == approval_id
    assert payload["comment_count"] == 1
    assert payload["last_comment_author"] == "tech_lead"

    detail = await api_client.get(f"/approvals/{approval_id}")
    assert detail.status_code == 200
    assert detail.json()["comment_count"] == 1


@pytest.mark.asyncio
async def test_claim_approval(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval()

    response = await api_client.post(
        f"/approvals/{approval_id}/claim",
        json={"user": "tech_lead"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == approval_id
    assert payload["state"] == "in_review"
    assert payload["claimed_by"] == "tech_lead"

    detail = await api_client.get(f"/approvals/{approval_id}")
    assert detail.status_code == 200
    assert detail.json()["state"] == "in_review"


@pytest.mark.asyncio
async def test_request_changes_requires_claimed_state(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval()

    not_claimed = await api_client.post(
        f"/approvals/{approval_id}/request-changes",
        json={"user": "tech_lead", "message": "Needs updates"},
    )
    assert not_claimed.status_code == 400
    assert "Cannot request changes" in not_claimed.json()["detail"]

    claim_response = await api_client.post(
        f"/approvals/{approval_id}/claim",
        json={"user": "tech_lead"},
    )
    assert claim_response.status_code == 200

    response = await api_client.post(
        f"/approvals/{approval_id}/request-changes",
        json={"user": "tech_lead", "message": "Needs updates"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "pending"
    assert payload["requested_by"] == "tech_lead"


@pytest.mark.asyncio
async def test_escalate_approval(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval()

    response = await api_client.post(
        f"/approvals/{approval_id}/escalate",
        json={"user": "tech_lead", "reason": "Cross-team impact"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "escalated"
    assert payload["escalated_by"] == "tech_lead"


@pytest.mark.asyncio
async def test_cancel_approval(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval()

    response = await api_client.post(
        f"/approvals/{approval_id}/cancel",
        json={"user": "requester", "reason": "Superseded request"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "cancelled"
    assert payload["cancelled_by"] == "requester"


@pytest.mark.asyncio
async def test_remind_approval(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval()

    response = await api_client.post(
        f"/approvals/{approval_id}/remind",
        json={"user": "pm", "message": "Please review today."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "pending"
    assert payload["reminded_by"] == "pm"

    detail = await api_client.get(f"/approvals/{approval_id}")
    assert detail.status_code == 200
    assert detail.json()["comment_count"] == 1


@pytest.mark.asyncio
async def test_approval_action_forbidden_for_non_approver(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval(approvers=["tech_lead"])

    claim = await api_client.post(
        f"/approvals/{approval_id}/claim",
        json={"user": "outsider"},
    )
    assert claim.status_code == 403
    assert claim.json()["detail"] == "User is not allowed to claim this approval"

    remind = await api_client.post(
        f"/approvals/{approval_id}/remind",
        json={"user": "outsider", "message": "ping"},
    )
    assert remind.status_code == 403
    assert remind.json()["detail"] == "User is not allowed to send reminders for this approval"


@pytest.mark.asyncio
async def test_cancel_allowed_for_requester(api_client: AsyncClient) -> None:
    approval_id = await _seed_approval(approvers=["tech_lead"])

    response = await api_client.post(
        f"/approvals/{approval_id}/cancel",
        json={"user": "system", "reason": "No longer needed"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "cancelled"
    assert payload["cancelled_by"] == "system"


@pytest.mark.asyncio
async def test_approve_forbidden_without_rbac_permission(api_client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("RBAC_DEFAULT_ROLE", "viewer")
    monkeypatch.setenv(
        "RBAC_USER_ROLES",
        "system:admin,api-user:tech_lead,developer:developer",
    )

    approval_id = await _seed_approval(approvers=["developer"])

    response = await api_client.post(
        f"/approvals/{approval_id}/approve",
        json={"user": "developer", "message": "approved"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User 'developer' lacks permission 'approval:approve'"
