"""Approval service for HITL workflow."""

import asyncio
import logging
import os
from datetime import datetime, timedelta
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
from core.security.rbac import ROLES, Permission, get_rbac
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

    @staticmethod
    def _parse_history_time(entry: dict[str, Any]) -> datetime | None:
        """Parse history timestamp entry."""
        raw = entry.get("timestamp")
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @staticmethod
    def _history_message(entry: dict[str, Any]) -> str:
        """Get normalized history message."""
        details = entry.get("details", {})
        if not isinstance(details, dict):
            return ""
        return str(details.get("message", "")).strip()

    def _is_timeout_related(self, record: ApprovalRecord) -> bool:
        """Check whether approval finished due to timeout path."""
        if record.state == ApprovalState.TIMED_OUT:
            return True

        for entry in record.history:
            if not isinstance(entry, dict):
                continue
            action = str(entry.get("action", "")).lower()
            message = self._history_message(entry).lower()
            if action == "timeout":
                return True
            if action in {"escalate", "reject"} and "timed out" in message:
                return True

        return False

    def _is_auto_escalated(self, record: ApprovalRecord) -> bool:
        """Check if approval was auto-escalated due to timeout."""
        for entry in record.history:
            if not isinstance(entry, dict):
                continue
            action = str(entry.get("action", "")).lower()
            message = self._history_message(entry).lower()
            if action == "escalate" and "auto-escalated" in message:
                return True
        return False

    def _is_auto_rejected(self, record: ApprovalRecord) -> bool:
        """Check if approval was auto-rejected due to timeout."""
        for entry in record.history:
            if not isinstance(entry, dict):
                continue
            action = str(entry.get("action", "")).lower()
            message = self._history_message(entry).lower()
            if action == "reject" and "auto-rejected" in message:
                return True
        return False

    def _timeout_wait_hours(self, record: ApprovalRecord) -> float:
        """Compute wait hours before timeout event."""
        start = record.requested_at
        if record.timeout_at:
            return max((record.timeout_at - start).total_seconds(), 0.0) / 3600.0

        timeout_event_time: datetime | None = None
        for entry in record.history:
            if not isinstance(entry, dict):
                continue
            action = str(entry.get("action", "")).lower()
            message = self._history_message(entry).lower()
            if action == "timeout" or (
                action in {"escalate", "reject"} and "timed out" in message
            ):
                timeout_event_time = self._parse_history_time(entry)
                if timeout_event_time:
                    break

        if timeout_event_time is None:
            timeout_event_time = datetime.utcnow()

        return max((timeout_event_time - start).total_seconds(), 0.0) / 3600.0

    def _get_approver_roles(self, record: ApprovalRecord) -> set[str]:
        """Get approver role set for analytics aggregation."""
        roles: set[str] = set()
        for approver in self._get_approvers(record):
            role_name = self._get_user_role_name(approver)
            if role_name:
                roles.add(role_name)

        if roles:
            return roles

        requester_role = self._get_user_role_name(record.requested_by)
        if requester_role:
            return {requester_role}

        return {"unknown"}

    def _is_escalation_policy_enabled(self) -> bool:
        """Check whether role/level escalation policy is enabled."""
        try:
            return bool(get_settings().hitl.escalation_policy_enabled)
        except Exception:
            return True

    def _get_escalation_levels(self) -> list[str]:
        """Get normalized escalation role levels."""
        default_levels = ["developer", "tech_lead", "admin"]
        try:
            raw_levels = get_settings().hitl.escalation_levels
        except Exception:
            raw_levels = ",".join(default_levels)

        levels: list[str] = []
        for item in raw_levels.split(","):
            role_name = self._normalize_actor(item)
            if role_name in ROLES and role_name not in levels:
                levels.append(role_name)

        if levels:
            return levels

        return [role for role in default_levels if role in ROLES]

    def _get_user_role_name(self, user_id: str) -> str | None:
        """Resolve normalized RBAC role name for user."""
        role = get_rbac().get_user_role(user_id)
        if not role:
            return None
        return self._normalize_actor(role.name)

    def _resolve_escalation_route(
        self,
        record: ApprovalRecord,
        escalated_by: str,
    ) -> dict[str, Any] | None:
        """Resolve next escalation target role and approvers."""
        approvers = self._get_approvers(record)
        if not approvers:
            return None

        actor_role = self._get_user_role_name(escalated_by)
        if not actor_role:
            return None

        levels = self._get_escalation_levels()
        if actor_role not in levels:
            return None

        actor_index = levels.index(actor_role)
        higher_roles = levels[actor_index + 1 :]
        if not higher_roles:
            return None

        approver_roles: dict[str, str] = {}
        for approver in approvers:
            role_name = self._get_user_role_name(approver)
            if role_name:
                approver_roles[approver] = role_name

        for target_role in higher_roles:
            targets = [
                approver
                for approver, role_name in approver_roles.items()
                if role_name == target_role
            ]
            if targets:
                return {
                    "from_role": actor_role,
                    "to_role": target_role,
                    "targets": targets,
                    "levels": levels,
                }

        return None

    def _apply_escalation_policy(
        self,
        record: ApprovalRecord,
        escalated_by: str,
        reason: str = "",
    ) -> None:
        """Apply role/level escalation routing for approvers."""
        if not self._is_escalation_policy_enabled():
            return

        route = self._resolve_escalation_route(record, escalated_by)
        if not route:
            return

        previous_approvers = self._get_approvers(record)
        record.metadata["approvers"] = route["targets"]
        record.metadata["escalation_policy"] = {
            "from_role": route["from_role"],
            "to_role": route["to_role"],
            "targets": route["targets"],
            "levels": route["levels"],
            "reason": reason,
            "escalated_by": escalated_by,
            "escalated_at": datetime.utcnow().isoformat(),
        }
        record.metadata["escalation_level"] = route["levels"].index(route["to_role"])

        record.add_history(
            action="escalation_routed",
            actor="system",
            details={
                "from_role": route["from_role"],
                "to_role": route["to_role"],
                "previous_approvers": previous_approvers,
                "new_approvers": route["targets"],
            },
        )

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
        self._apply_escalation_policy(sm.record, escalated_by=escalated_by, reason=reason)
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

    async def get_timeout_analytics(
        self,
        days: int = 7,
        session_id: UUID | None = None,
        stage_name: str | None = None,
    ) -> dict[str, Any]:
        """Get timeout analytics aggregated by stage and role."""
        now = datetime.utcnow()
        window_days = max(days, 1)
        since = now - timedelta(days=window_days)

        async with self.database.session() as db_session:
            repo = ApprovalRepository(db_session)
            records = await repo.list_for_analytics(
                since=since,
                until=now,
                session_id=session_id,
                stage_name=stage_name,
            )

        total_records = len(records)
        timeout_records = [record for record in records if self._is_timeout_related(record)]
        timeout_count = len(timeout_records)
        auto_escalated_count = sum(1 for record in records if self._is_auto_escalated(record))
        auto_rejected_count = sum(1 for record in records if self._is_auto_rejected(record))

        timeout_wait_samples = [self._timeout_wait_hours(record) for record in timeout_records]
        avg_timeout_wait = (
            sum(timeout_wait_samples) / len(timeout_wait_samples) if timeout_wait_samples else 0.0
        )

        stage_stats: dict[str, dict[str, Any]] = {}
        for record in records:
            stage = record.stage_name or "unknown"
            bucket = stage_stats.setdefault(
                stage,
                {
                    "stage_name": stage,
                    "total": 0,
                    "timeout_related": 0,
                    "timeout_wait_samples": [],
                },
            )
            bucket["total"] += 1
            if self._is_timeout_related(record):
                bucket["timeout_related"] += 1
                bucket["timeout_wait_samples"].append(self._timeout_wait_hours(record))

        by_stage: list[dict[str, Any]] = []
        for stage_name_key in sorted(stage_stats):
            bucket = stage_stats[stage_name_key]
            wait_samples = bucket.pop("timeout_wait_samples")
            timeout_related = bucket["timeout_related"]
            total = bucket["total"]
            by_stage.append(
                {
                    "stage_name": stage_name_key,
                    "total": total,
                    "timeout_related": timeout_related,
                    "timeout_rate": timeout_related / total if total > 0 else 0.0,
                    "avg_wait_hours_before_timeout": (
                        sum(wait_samples) / len(wait_samples) if wait_samples else 0.0
                    ),
                }
            )

        role_stats: dict[str, dict[str, Any]] = {}
        for record in records:
            roles = self._get_approver_roles(record)
            timeout_related = self._is_timeout_related(record)
            for role_name in roles:
                bucket = role_stats.setdefault(
                    role_name,
                    {
                        "role": role_name,
                        "total": 0,
                        "timeout_related": 0,
                    },
                )
                bucket["total"] += 1
                if timeout_related:
                    bucket["timeout_related"] += 1

        by_role = [
            {
                "role": role_name,
                "total": bucket["total"],
                "timeout_related": bucket["timeout_related"],
                "timeout_rate": (
                    bucket["timeout_related"] / bucket["total"] if bucket["total"] > 0 else 0.0
                ),
            }
            for role_name, bucket in sorted(role_stats.items())
        ]

        return {
            "generated_at": now.isoformat(),
            "window_days": window_days,
            "since": since.isoformat(),
            "until": now.isoformat(),
            "filters": {
                "session_id": str(session_id) if session_id else None,
                "stage_name": stage_name,
            },
            "total_records": total_records,
            "timeout_related_count": timeout_count,
            "timeout_state_count": sum(
                1 for record in records if record.state == ApprovalState.TIMED_OUT
            ),
            "auto_escalated_count": auto_escalated_count,
            "auto_rejected_count": auto_rejected_count,
            "timeout_rate": (timeout_count / total_records if total_records > 0 else 0.0),
            "avg_wait_hours_before_timeout": avg_timeout_wait,
            "by_stage": by_stage,
            "by_role": by_role,
        }

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
                self._apply_escalation_policy(
                    sm.record,
                    escalated_by="system",
                    reason="Timed out; auto-escalated",
                )
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
            "escalation_policy": record.metadata.get("escalation_policy"),
        }
