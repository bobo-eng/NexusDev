"""API tests for approval detail and comments endpoints."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import apps.api.main as api_main
from core.services.approval_service import ApprovalService


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


async def _seed_approval() -> str:
    db = await api_main.get_db()
    service = ApprovalService(db)
    approval = await service.create_approval(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        request_message="Please review design output",
        timeout_hours=24,
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
