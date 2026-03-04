"""Approval service for HITL workflow."""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from core.config.settings import get_settings
from core.hitl.approval_sm import (
    ApprovalAction,
    ApprovalRecord,
    ApprovalState,
    ApprovalStateMachine,
)
from core.observability.metrics import get_metrics
from core.security.rbac import Permission, get_rbac
from core.storage.database import Database
from core.storage.repository import ApprovalRepository

logger = logging.getLogger(__name__)


class ApprovalService:
    """Service for managing human approvals.

    Provides:
    - Create approval requests
    - Process approvals/rejections
    - Query approval status
    - Handle timeouts

    All approval records are persisted to the database.
    """

    def __init__(self, database: Database):
        self.database = database
        # Cache for in-memory access (still needed for quick lookups)
        self._approval_cache: dict[UUID, ApprovalStateMachine] = {}

    def _calculate_wait_hours(self, requested_at: datetime) -> float:
        """Calculate elapsed wait time in hours."""
        delta = datetime.utcnow() - requested_at
        return max(delta.total_seconds(), 0.0) / 3600.0

    def _normalize_actor(self, actor: str) -> str:
        """Normalize actor identifier for comparisons."""
        return actor.strip().lower()

    def _get_approvers(self, record: ApprovalRecord) -> list[str]:
        """Get normalized approvers configured on an approval."""
        raw = record.metadata.get("approvers", [])
        if not isinstance(raw, list):
            return []
        return [self._normalize_actor(item) for item in raw if isinstance(item, str) and item]

    def is_approver(self, record: ApprovalRecord, actor: str) -> bool:
        """Check if actor is in approval allowlist (or no allowlist configured)."""
        approvers = self._get_approvers(record)
        if not approvers:
            return True
        return self._normalize_actor(actor) in approvers

    def can_cancel(self, record: ApprovalRecord, actor: str) -> bool:
        """Check whether actor can cancel approval."""
        if self.is_approver(record, actor):
            return True
        return self._normalize_actor(record.requested_by) == self._normalize_actor(actor)

    def _has_permission(self, actor: str, permission: Permission) -> bool:
        """Check RBAC permission for actor."""
        return get_rbac().check_permission(actor, permission)

    def _remaining_timeout_hours(self, record: ApprovalRecord) -> float | None:
        """Get remaining timeout hours for a record."""
        if not record.timeout_at:
            return None
        return (record.timeout_at - datetime.utcnow()).total_seconds() / 3600.0

    def _parse_notification_channels(self) -> set[str]:
        """Parse notification channels from environment."""
        raw = os.getenv("HITL_NOTIFICATION_CHANNELS", "").strip()
        if not raw:
            return set()
        return {item.strip().lower() for item in raw.split(",") if item.strip()}

    async def _notify_log(self, payload: dict[str, Any]) -> None:
        """Write notification payload to structured log."""
        logger.info(
            f"Approval notification event={payload['event']} "
            f"approval_id={payload['approval_id']} actor={payload['actor']}"
        )

    async def _notify_webhook(self, webhook_url: str, payload: dict[str, Any]) -> None:
        """Send notification to generic webhook endpoint."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(webhook_url, json=payload)
        except Exception as exc:
            logger.warning(f"Failed to deliver approval webhook notification: {exc}")

    async def _notify_dashboard(self, dashboard_url: str, payload: dict[str, Any]) -> None:
        """Send notification to dashboard ingestion webhook."""
        dashboard_payload = payload.copy()
        dashboard_payload["channel"] = "dashboard"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(dashboard_url, json=dashboard_payload)
        except Exception as exc:
            logger.warning(f"Failed to deliver approval dashboard notification: {exc}")

    def _send_email_sync(self, smtp_url: str, email_to: str, payload: dict[str, Any]) -> None:
        """Send notification email via SMTP URL."""
        import smtplib
        from email.message import EmailMessage
        from urllib.parse import unquote, urlparse

        parsed = urlparse(smtp_url)
        host = parsed.hostname
        if not host:
            raise ValueError("HITL_SMTP_URL must include hostname")

        scheme = (parsed.scheme or "smtp").lower()
        use_ssl = scheme == "smtps"
        port = parsed.port or (465 if use_ssl else 587)
        username = unquote(parsed.username) if parsed.username else ""
        password = unquote(parsed.password) if parsed.password else ""
        recipients = [item.strip() for item in email_to.split(",") if item.strip()]
        if not recipients:
            return

        sender = os.getenv("HITL_EMAIL_FROM", "noreply@nexusdev.local")
        starttls_enabled = os.getenv("HITL_SMTP_STARTTLS", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        message = EmailMessage()
        message["Subject"] = f"[NexusDev] {payload['event']} ({payload['stage_name']})"
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message.set_content(
            "\n".join(
                [
                    f"event: {payload['event']}",
                    f"approval_id: {payload['approval_id']}",
                    f"session_id: {payload['session_id']}",
                    f"stage: {payload['stage_name']}",
                    f"state: {payload['state']}",
                    f"actor: {payload['actor']}",
                    f"message: {payload['message']}",
                    f"timestamp: {payload['timestamp']}",
                ]
            )
        )

        if use_ssl:
            smtp_client = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            smtp_client = smtplib.SMTP(host, port, timeout=10)

        with smtp_client as client:
            if not use_ssl and starttls_enabled:
                client.starttls()
            if username:
                client.login(username, password)
            client.send_message(message)

    async def _notify_email(self, smtp_url: str, email_to: str, payload: dict[str, Any]) -> None:
        """Send notification email asynchronously."""
        try:
            await asyncio.to_thread(self._send_email_sync, smtp_url, email_to, payload)
        except Exception as exc:
            logger.warning(f"Failed to deliver approval email notification: {exc}")

    async def _send_notification(
        self,
        event: str,
        record: ApprovalRecord,
        actor: str = "",
        message: str = "",
    ) -> None:
        """Send approval notifications across configured channels."""
        webhook_url = os.getenv("HITL_WEBHOOK_URL", "").strip()
        dashboard_url = os.getenv("HITL_DASHBOARD_WEBHOOK_URL", "").strip()
        smtp_url = os.getenv("HITL_SMTP_URL", "").strip()
        email_to = os.getenv("HITL_EMAIL_TO", "").strip()
        notifications_enabled = False
        try:
            notifications_enabled = bool(get_settings().hitl.enable_notifications)
        except Exception:
            notifications_enabled = False

        has_external_target = bool(
            webhook_url
            or dashboard_url
            or (smtp_url and email_to)
        )
        if not notifications_enabled and not has_external_target:
            return

        channels = self._parse_notification_channels()
        if not channels:
            channels = {"log"}
            if webhook_url:
                channels.add("webhook")
            if dashboard_url:
                channels.add("dashboard")
            if smtp_url and email_to:
                channels.add("email")

        payload = {
            "event": event,
            "approval_id": str(record.id),
            "session_id": str(record.session_id),
            "stage_id": str(record.stage_id),
            "stage_name": record.stage_name,
            "state": record.state.value,
            "actor": actor,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }

        tasks: list[asyncio.Task[None]] = []

        for channel in channels:
            if channel == "log":
                await self._notify_log(payload)
            elif channel == "webhook":
                if webhook_url:
                    tasks.append(asyncio.create_task(self._notify_webhook(webhook_url, payload)))
            elif channel == "dashboard":
                if dashboard_url:
                    tasks.append(asyncio.create_task(self._notify_dashboard(dashboard_url, payload)))
            elif channel == "email" and smtp_url and email_to:
                tasks.append(asyncio.create_task(self._notify_email(smtp_url, email_to, payload)))

        if tasks:
            await asyncio.gather(*tasks)

    async def _load_to_cache(self, approval_id: UUID) -> ApprovalStateMachine | None:
        """Load approval from DB to cache."""
        if approval_id in self._approval_cache:
            return self._approval_cache[approval_id]

        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            record = await repo.get_by_id(approval_id)
            if record:
                sm = ApprovalStateMachine(record)
                self._approval_cache[approval_id] = sm
                return sm
        return None

    async def _save_to_db(self, sm: ApprovalStateMachine) -> None:
        """Save approval state machine to DB."""
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            # Check if exists
            existing = await repo.get_by_id(sm.record.id)
            if existing:
                await repo.update(sm.record)
            else:
                await repo.create(sm.record)
        self._approval_cache[sm.record.id] = sm

    async def create_approval(
        self,
        session_id: UUID,
        stage_id: UUID,
        stage_name: str,
        requested_by: str,
        request_message: str = "",
        timeout_hours: int = 24,
        artifact_ids: list[UUID] | None = None,
        approvers: list[str] | None = None,
    ) -> ApprovalRecord:
        """Create a new approval request.

        Args:
            session_id: Session ID
            stage_id: Stage ID
            stage_name: Stage name
            requested_by: Who requested approval
            request_message: Request message
            timeout_hours: Timeout in hours
            artifact_ids: Related artifact IDs
            approvers: Optional explicit list of approver identifiers

        Returns:
            Created approval record
        """
        sm = ApprovalStateMachine.create(
            session_id=session_id,
            stage_id=stage_id,
            stage_name=stage_name,
            requested_by=requested_by,
            request_message=request_message,
            timeout_hours=timeout_hours,
            artifact_ids=artifact_ids or [],
        )
        if approvers:
            sm.record.metadata["approvers"] = [
                self._normalize_actor(item) for item in approvers if item
            ]

        # Persist to database
        await self._save_to_db(sm)

        # Cache in memory
        self._approval_cache[sm.record.id] = sm

        logger.info(
            f"[Session {session_id}] Created approval {sm.record.id} for stage {stage_name}"
        )

        await self._send_notification(
            event="approval.created",
            record=sm.record,
            actor=requested_by,
            message=request_message,
        )

        return sm.record

    async def approve(
        self,
        approval_id: UUID,
        approved_by: str,
        message: str = "",
    ) -> ApprovalRecord | None:
        """Approve a request.

        Args:
            approval_id: Approval record ID
            approved_by: Who is approving
            message: Approval message

        Returns:
            Updated record or None
        """
        sm = await self._load_to_cache(approval_id)
        if not sm:
            logger.error(f"Approval {approval_id} not found")
            return None

        if not self._has_permission(approved_by, Permission.APPROVAL_APPROVE):
            logger.error(f"User {approved_by} lacks permission {Permission.APPROVAL_APPROVE.value}")
            return None

        if not self.is_approver(sm.record, approved_by):
            logger.error(f"User {approved_by} cannot approve approval {approval_id}")
            return None

        if not sm.can_transition(ApprovalAction.APPROVE):
            logger.error(f"Cannot approve approval {approval_id} in state {sm.record.state.value}")
            return None

        sm.approve(approved_by, message)

        # Persist to database
        await self._save_to_db(sm)

        get_metrics().record_approval(
            approved=True,
            wait_time_hours=self._calculate_wait_hours(sm.record.requested_at),
        )

        logger.info(f"Approval {approval_id} approved by {approved_by}")

        await self._send_notification(
            event="approval.approved",
            record=sm.record,
            actor=approved_by,
            message=message,
        )

        return sm.record

    async def reject(
        self,
        approval_id: UUID,
        rejected_by: str,
        reason: str = "",
    ) -> ApprovalRecord | None:
        """Reject a request.

        Args:
            approval_id: Approval record ID
            rejected_by: Who is rejecting
            reason: Rejection reason

        Returns:
            Updated record or None
        """
        sm = await self._load_to_cache(approval_id)
        if not sm:
            logger.error(f"Approval {approval_id} not found")
            return None

        if not self._has_permission(rejected_by, Permission.APPROVAL_REJECT):
            logger.error(f"User {rejected_by} lacks permission {Permission.APPROVAL_REJECT.value}")
            return None

        if not self.is_approver(sm.record, rejected_by):
            logger.error(f"User {rejected_by} cannot reject approval {approval_id}")
            return None

        if not sm.can_transition(ApprovalAction.REJECT):
            logger.error(f"Cannot reject approval {approval_id} in state {sm.record.state.value}")
            return None

        sm.reject(rejected_by, reason)

        # Persist to database
        await self._save_to_db(sm)

        get_metrics().record_approval(
            approved=False,
            rejected=True,
            wait_time_hours=self._calculate_wait_hours(sm.record.requested_at),
        )

        logger.info(f"Approval {approval_id} rejected by {rejected_by}")

        await self._send_notification(
            event="approval.rejected",
            record=sm.record,
            actor=rejected_by,
            message=reason,
        )

        return sm.record

    async def request_changes(
        self,
        approval_id: UUID,
        requested_by: str,
        message: str = "",
    ) -> ApprovalRecord | None:
        """Request changes without full rejection.

        Args:
            approval_id: Approval record ID
            requested_by: Who is requesting changes
            message: Change request message

        Returns:
            Updated record or None
        """
        sm = await self._load_to_cache(approval_id)
        if not sm:
            return None

        if not self._has_permission(requested_by, Permission.APPROVAL_REJECT):
            logger.error(f"User {requested_by} lacks permission {Permission.APPROVAL_REJECT.value}")
            return None

        if not self.is_approver(sm.record, requested_by):
            logger.error(f"User {requested_by} cannot request changes for approval {approval_id}")
            return None

        if not sm.can_transition(ApprovalAction.REQUEST_CHANGES):
            logger.error(
                f"Cannot request changes for approval {approval_id} in state {sm.record.state.value}"
            )
            return None

        sm.request_changes(requested_by, message)

        # Persist to database
        await self._save_to_db(sm)

        logger.info(f"Approval {approval_id} requested changes by {requested_by}")
        await self._send_notification(
            event="approval.changes_requested",
            record=sm.record,
            actor=requested_by,
            message=message,
        )

        return sm.record

    async def claim(
        self,
        approval_id: UUID,
        claimed_by: str,
    ) -> ApprovalRecord | None:
        """Claim an approval for review."""
        sm = await self._load_to_cache(approval_id)
        if not sm:
            return None

        if not self._has_permission(claimed_by, Permission.APPROVAL_APPROVE):
            logger.error(f"User {claimed_by} lacks permission {Permission.APPROVAL_APPROVE.value}")
            return None

        if not self.is_approver(sm.record, claimed_by):
            logger.error(f"User {claimed_by} cannot claim approval {approval_id}")
            return None

        if not sm.can_transition(ApprovalAction.CLAIM):
            logger.error(f"Cannot claim approval {approval_id} in state {sm.record.state.value}")
            return None

        sm.claim(claimed_by)
        await self._save_to_db(sm)
        logger.info(f"Approval {approval_id} claimed by {claimed_by}")
        await self._send_notification(
            event="approval.claimed",
            record=sm.record,
            actor=claimed_by,
        )
        return sm.record

    async def escalate(
        self,
        approval_id: UUID,
        escalated_by: str,
        reason: str = "",
    ) -> ApprovalRecord | None:
        """Escalate an approval request."""
        sm = await self._load_to_cache(approval_id)
        if not sm:
            return None

        if not self._has_permission(escalated_by, Permission.APPROVAL_APPROVE):
            logger.error(f"User {escalated_by} lacks permission {Permission.APPROVAL_APPROVE.value}")
            return None

        if not self.is_approver(sm.record, escalated_by):
            logger.error(f"User {escalated_by} cannot escalate approval {approval_id}")
            return None

        if not sm.can_transition(ApprovalAction.ESCALATE):
            logger.error(f"Cannot escalate approval {approval_id} in state {sm.record.state.value}")
            return None

        sm.escalate(escalated_by, reason)
        await self._save_to_db(sm)
        logger.info(f"Approval {approval_id} escalated by {escalated_by}")
        await self._send_notification(
            event="approval.escalated",
            record=sm.record,
            actor=escalated_by,
            message=reason,
        )
        return sm.record

    async def cancel(
        self,
        approval_id: UUID,
        cancelled_by: str,
        reason: str = "",
    ) -> ApprovalRecord | None:
        """Cancel an approval request."""
        sm = await self._load_to_cache(approval_id)
        if not sm:
            return None

        if not self._has_permission(cancelled_by, Permission.APPROVAL_REJECT):
            logger.error(f"User {cancelled_by} lacks permission {Permission.APPROVAL_REJECT.value}")
            return None

        if not self.can_cancel(sm.record, cancelled_by):
            logger.error(f"User {cancelled_by} cannot cancel approval {approval_id}")
            return None

        if not sm.can_transition(ApprovalAction.CANCEL):
            logger.error(f"Cannot cancel approval {approval_id} in state {sm.record.state.value}")
            return None

        sm.cancel(cancelled_by, reason)
        await self._save_to_db(sm)
        logger.info(f"Approval {approval_id} cancelled by {cancelled_by}")
        await self._send_notification(
            event="approval.cancelled",
            record=sm.record,
            actor=cancelled_by,
            message=reason,
        )
        return sm.record

    async def remind(
        self,
        approval_id: UUID,
        reminded_by: str,
        message: str = "",
    ) -> ApprovalRecord | None:
        """Send a reminder for a pending approval."""
        sm = await self._load_to_cache(approval_id)
        if not sm:
            return None

        if not self._has_permission(reminded_by, Permission.APPROVAL_READ):
            logger.error(f"User {reminded_by} lacks permission {Permission.APPROVAL_READ.value}")
            return None

        if not self.is_approver(sm.record, reminded_by):
            logger.error(f"User {reminded_by} cannot remind approval {approval_id}")
            return None

        if not sm.record.is_pending():
            logger.error(f"Cannot remind approval {approval_id} in state {sm.record.state.value}")
            return None

        sm.record.add_history(
            action=ApprovalAction.REMIND.value,
            actor=reminded_by,
            details={"message": message},
        )
        if message:
            sm.record.add_comment(reminded_by, message, is_internal=True)
        await self._save_to_db(sm)
        logger.info(f"Approval {approval_id} reminder sent by {reminded_by}")
        await self._send_notification(
            event="approval.reminded",
            record=sm.record,
            actor=reminded_by,
            message=message,
        )
        return sm.record

    async def get_approval(self, approval_id: UUID) -> ApprovalRecord | None:
        """Get approval record by ID."""
        # Try cache first
        if approval_id in self._approval_cache:
            return self._approval_cache[approval_id].record

        # Load from DB
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            return await repo.get_by_id(approval_id)

    async def get_pending_approvals(
        self,
        session_id: UUID | None = None,
    ) -> list[ApprovalRecord]:
        """Get all pending approvals.

        Args:
            session_id: Filter by session (optional)

        Returns:
            List of pending approval records
        """
        return await self.list_approvals(
            state=ApprovalState.PENDING.value,
            session_id=session_id,
            limit=100,
            offset=0,
        )

    async def list_approvals(
        self,
        state: str | None = None,
        session_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApprovalRecord]:
        """List approvals with optional filters and pagination."""
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            return await repo.list_records(
                state=state,
                session_id=session_id,
                limit=limit,
                offset=offset,
            )

    async def get_session_approvals(
        self,
        session_id: UUID,
    ) -> list[ApprovalRecord]:
        """Get all approvals for a session."""
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            return await repo.get_by_session(session_id)

    async def get_stage_approvals(
        self,
        stage_id: UUID,
    ) -> list[ApprovalRecord]:
        """Get all approvals for a stage."""
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            return await repo.get_by_stage(stage_id)

    async def check_timeouts(self) -> list[ApprovalRecord]:
        """Check and process timed out approvals.

        Returns:
            List of timed out records
        """
        timed_out = []
        reminder_threshold_hours = 0.0
        auto_escalate = False
        auto_reject = False
        try:
            hitl_settings = get_settings().hitl
            reminder_threshold_hours = max(float(hitl_settings.reminder_hours_before_timeout), 0.0)
            auto_escalate = bool(hitl_settings.auto_escalate_on_timeout)
            auto_reject = bool(hitl_settings.auto_reject_on_timeout)
        except Exception:
            reminder_threshold_hours = 0.0
            auto_escalate = False
            auto_reject = False

        # Get all pending approvals from DB
        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            pending = await repo.get_by_state(ApprovalState.PENDING.value)

        for record in pending:
            sm = ApprovalStateMachine(record)

            remaining_hours = self._remaining_timeout_hours(sm.record)
            reminder_sent = bool(sm.record.metadata.get("timeout_reminder_sent"))
            if (
                remaining_hours is not None
                and 0 < remaining_hours <= reminder_threshold_hours
                and not reminder_sent
            ):
                sm.record.metadata["timeout_reminder_sent"] = True
                sm.record.add_history(
                    action=ApprovalAction.REMIND.value,
                    actor="system",
                    details={
                        "reason": "timeout_threshold",
                        "hours_remaining": remaining_hours,
                    },
                )
                await self._save_to_db(sm)
                await self._send_notification(
                    event="approval.timeout_reminder",
                    record=sm.record,
                    actor="system",
                    message=f"Timeout in {remaining_hours:.2f} hours",
                )

            should_timeout = (
                sm.record.timeout_at is not None
                and datetime.utcnow() > sm.record.timeout_at
                and sm.record.is_pending()
            )
            if not should_timeout:
                continue

            if auto_escalate and sm.can_transition(ApprovalAction.ESCALATE):
                sm.escalate("system", "Timed out; auto-escalated")
                timed_out.append(sm.record)
                await self._save_to_db(sm)
                get_metrics().record_approval(
                    approved=False,
                    timed_out=True,
                    wait_time_hours=self._calculate_wait_hours(sm.record.requested_at),
                )
                logger.warning(f"Approval {record.id} timed out and auto-escalated")
                await self._send_notification(
                    event="approval.auto_escalated",
                    record=sm.record,
                    actor="system",
                    message="Timed out; auto-escalated",
                )
                continue

            if auto_reject and sm.can_transition(ApprovalAction.REJECT):
                sm.reject("system", "Timed out; auto-rejected")
                timed_out.append(sm.record)
                await self._save_to_db(sm)
                get_metrics().record_approval(
                    approved=False,
                    timed_out=True,
                    wait_time_hours=self._calculate_wait_hours(sm.record.requested_at),
                )
                logger.warning(f"Approval {record.id} timed out and auto-rejected")
                await self._send_notification(
                    event="approval.auto_rejected",
                    record=sm.record,
                    actor="system",
                    message="Timed out; auto-rejected",
                )
                continue

            if sm.check_timeout():
                timed_out.append(sm.record)
                await self._save_to_db(sm)
                get_metrics().record_approval(
                    approved=False,
                    timed_out=True,
                    wait_time_hours=self._calculate_wait_hours(sm.record.requested_at),
                )
                logger.warning(f"Approval {record.id} timed out")
                await self._send_notification(
                    event="approval.timed_out",
                    record=sm.record,
                    actor="system",
                )

        return timed_out

    async def add_comment(
        self,
        approval_id: UUID,
        author: str,
        content: str,
        is_internal: bool = False,
    ) -> ApprovalRecord | None:
        """Add comment to approval.

        Args:
            approval_id: Approval record ID
            author: Comment author
            content: Comment content
            is_internal: Internal note flag

        Returns:
            Updated record or None
        """
        sm = await self._load_to_cache(approval_id)
        if not sm:
            return None

        if not self._has_permission(author, Permission.APPROVAL_READ):
            logger.error(f"User {author} lacks permission {Permission.APPROVAL_READ.value}")
            return None

        sm.record.add_comment(author, content, is_internal)

        # Persist to database
        await self._save_to_db(sm)
        await self._send_notification(
            event="approval.comment_added",
            record=sm.record,
            actor=author,
            message=content,
        )

        return sm.record

    async def get_approval_summary(self, approval_id: UUID) -> dict[str, Any] | None:
        """Get human-readable approval summary."""
        record = await self.get_approval(approval_id)
        if not record:
            return None

        return {
            "id": str(record.id),
            "session_id": str(record.session_id),
            "stage_name": record.stage_name,
            "state": record.state.value,
            "approvers": record.metadata.get("approvers", []),
            "requested_by": record.requested_by,
            "requested_at": record.requested_at.isoformat(),
            "approved_by": record.approved_by,
            "approved_at": record.approved_at.isoformat() if record.approved_at else None,
            "rejected_by": record.rejected_by,
            "rejected_at": record.rejected_at.isoformat() if record.rejected_at else None,
            "timeout_at": record.timeout_at.isoformat() if record.timeout_at else None,
            "time_remaining": str(record.time_remaining()) if record.time_remaining() else None,
            "is_pending": record.is_pending(),
            "is_resolved": record.is_resolved(),
            "comment_count": len(record.comments),
        }
