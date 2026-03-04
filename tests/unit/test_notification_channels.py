"""Tests for multi-channel approval notifications."""

from uuid import uuid4

import pytest
from core.config.settings import get_settings
from core.hitl.approval_sm import ApprovalStateMachine
from core.services.approval_service import ApprovalService
from core.storage.database import create_database


@pytest.fixture
async def approval_service(tmp_path):
    """Create approval service with temporary database."""
    db = create_database(f"sqlite+aiosqlite:///{tmp_path}/notification_channels.db")
    await db.create_tables()
    service = ApprovalService(db)
    try:
        yield service
    finally:
        await db.close()


@pytest.fixture(autouse=True)
def clear_notification_env(monkeypatch: pytest.MonkeyPatch):
    """Reset notification-related environment per test."""
    keys = [
        "HITL_ENABLE_NOTIFICATIONS",
        "HITL_WEBHOOK_URL",
        "HITL_DASHBOARD_WEBHOOK_URL",
        "HITL_SMTP_URL",
        "HITL_EMAIL_TO",
        "HITL_NOTIFICATION_CHANNELS",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_record():
    """Build a minimal approval record."""
    return ApprovalStateMachine.create(
        session_id=uuid4(),
        stage_id=uuid4(),
        stage_name="system_design",
        requested_by="system",
        request_message="review",
    ).record


@pytest.mark.asyncio
async def test_send_notification_dispatches_all_channels(
    approval_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When configured, all channels should be invoked."""
    monkeypatch.setenv("HITL_ENABLE_NOTIFICATIONS", "true")
    monkeypatch.setenv("HITL_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("HITL_DASHBOARD_WEBHOOK_URL", "https://example.com/dashboard")
    monkeypatch.setenv("HITL_SMTP_URL", "smtp://user:pass@example.com:587")
    monkeypatch.setenv("HITL_EMAIL_TO", "dev@example.com")
    get_settings.cache_clear()

    called: list[str] = []

    async def fake_log(payload):
        del payload
        called.append("log")

    async def fake_webhook(url, payload):
        del url, payload
        called.append("webhook")

    async def fake_dashboard(url, payload):
        del url, payload
        called.append("dashboard")

    async def fake_email(smtp_url, email_to, payload):
        del smtp_url, email_to, payload
        called.append("email")

    monkeypatch.setattr(approval_service, "_notify_log", fake_log)
    monkeypatch.setattr(approval_service, "_notify_webhook", fake_webhook)
    monkeypatch.setattr(approval_service, "_notify_dashboard", fake_dashboard)
    monkeypatch.setattr(approval_service, "_notify_email", fake_email)

    await approval_service._send_notification(
        event="approval.created",
        record=_make_record(),
        actor="system",
        message="created",
    )

    assert set(called) == {"log", "webhook", "dashboard", "email"}


@pytest.mark.asyncio
async def test_send_notification_skips_when_disabled_without_targets(
    approval_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled notifications with no targets should no-op."""
    monkeypatch.setenv("HITL_ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    called: list[str] = []

    async def fake_log(payload):
        del payload
        called.append("log")

    monkeypatch.setattr(approval_service, "_notify_log", fake_log)

    await approval_service._send_notification(
        event="approval.created",
        record=_make_record(),
        actor="system",
        message="created",
    )

    assert called == []


@pytest.mark.asyncio
async def test_send_notification_respects_channel_filter(
    approval_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit channel list should filter dispatch targets."""
    monkeypatch.setenv("HITL_ENABLE_NOTIFICATIONS", "true")
    monkeypatch.setenv("HITL_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("HITL_DASHBOARD_WEBHOOK_URL", "https://example.com/dashboard")
    monkeypatch.setenv("HITL_SMTP_URL", "smtp://user:pass@example.com:587")
    monkeypatch.setenv("HITL_EMAIL_TO", "dev@example.com")
    monkeypatch.setenv("HITL_NOTIFICATION_CHANNELS", "log,email")
    get_settings.cache_clear()

    called: list[str] = []

    async def fake_log(payload):
        del payload
        called.append("log")

    async def fake_webhook(url, payload):
        del url, payload
        called.append("webhook")

    async def fake_dashboard(url, payload):
        del url, payload
        called.append("dashboard")

    async def fake_email(smtp_url, email_to, payload):
        del smtp_url, email_to, payload
        called.append("email")

    monkeypatch.setattr(approval_service, "_notify_log", fake_log)
    monkeypatch.setattr(approval_service, "_notify_webhook", fake_webhook)
    monkeypatch.setattr(approval_service, "_notify_dashboard", fake_dashboard)
    monkeypatch.setattr(approval_service, "_notify_email", fake_email)

    await approval_service._send_notification(
        event="approval.created",
        record=_make_record(),
        actor="system",
        message="created",
    )

    assert set(called) == {"log", "email"}
