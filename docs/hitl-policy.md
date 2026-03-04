# Human-in-the-Loop (HITL) Policy

## Overview

NexusDev implements human-in-the-loop approval at critical workflow checkpoints. This document defines the HITL policy, approval workflows, and escalation procedures.

## Approval Checkpoints

### Default Workflow

The MVP workflow has one mandatory approval checkpoint:

```
Requirement Analysis ──► System Design ──► [APPROVAL REQUIRED] ──► Coding
```

### Rationale

System design approval is required because:
1. Architecture decisions have long-term impact
2. API contracts affect integration
3. Database schema changes are costly
4. Security considerations must be reviewed

## Approval State Machine

```
                    ┌─────────────┐
                    │   PENDING   │
                    └──────┬──────┘
                           │ claim
                           ▼
                    ┌─────────────┐
         ┌─────────│ IN_REVIEW   │─────────┐
         │         └─────────────┘         │
         │                                 │
    reject │                           │ approve
         │                                 │
         ▼                                 ▼
┌─────────────┐                   ┌─────────────┐
│  REJECTED   │                   │  APPROVED   │
└─────────────┘                   └─────────────┘
         │                                 │
         │ request_changes                 │
         └────────► (back to PENDING) ◄────┘
```

### States

| State | Description |
|-------|-------------|
| PENDING | Waiting for reviewer |
| IN_REVIEW | Someone is actively reviewing |
| APPROVED | Approved, can proceed |
| REJECTED | Rejected, must address issues |
| ESCALATED | Escalated to higher authority |
| TIMED_OUT | Approval timeout reached |
| CANCELLED | Approval request cancelled |

### Actions

| Action | From State | To State | Description |
|--------|------------|----------|-------------|
| SUBMIT | - | PENDING | Create approval request |
| CLAIM | PENDING | IN_REVIEW | Claim for review |
| APPROVE | PENDING/IN_REVIEW | APPROVED | Approve request |
| REJECT | PENDING/IN_REVIEW | REJECTED | Reject request |
| REQUEST_CHANGES | IN_REVIEW | PENDING | Return for changes |
| ESCALATE | PENDING/IN_REVIEW | ESCALATED | Escalate to higher authority |
| CANCEL | Any | CANCELLED | Cancel request |

## Approval Configuration

### SOP Configuration

```yaml
stages:
  - name: system_design
    requires_approval: true
    approval_timeout_hours: 24
    approvers:
      - tech_lead
      - architect
      - senior_developer
```

`approvers` is now enforced in runtime approval actions. When an allowlist exists,
only listed actors can claim/approve/reject/request-changes/escalate/remind.

### Timeout Handling

Current behavior:
1. Worker periodically checks pending approvals for timeout
2. Timed-out requests are marked `TIMED_OUT`
3. Notification events are emitted to configurable channels:
   - log
   - webhook (`HITL_WEBHOOK_URL`)
   - email (`HITL_SMTP_URL` + `HITL_EMAIL_TO`)
   - dashboard webhook (`HITL_DASHBOARD_WEBHOOK_URL`)
4. Timeout analytics are available via `GET /approvals/analytics/timeouts`

Planned enhancements:
1. Advanced timeout trend dashboards/alerting

Current timeout controls (env):
- `HITL_REMINDER_HOURS_BEFORE_TIMEOUT`
- `HITL_AUTO_ESCALATE_ON_TIMEOUT`
- `HITL_AUTO_REJECT_ON_TIMEOUT`

## Approval Workflow

### 1. Submission

When a stage requiring approval completes:

```python
approval = await approval_service.create_approval(
    session_id=session.id,
    stage_id=stage.id,
    stage_name=stage.name,
    requested_by="system",
    request_message="Please review the system design",
    timeout_hours=24,
    artifact_ids=[design_artifact.id],
)
```

### 2. Notification

Approvers are notified via:
- Event log
- Webhook (`HITL_WEBHOOK_URL`, if configured)
- Email (`HITL_SMTP_URL` + `HITL_EMAIL_TO`, if configured)
- Dashboard webhook (`HITL_DASHBOARD_WEBHOOK_URL`, if configured)

### 3. Review

Approver reviews:
- Stage outputs (artifacts)
- Previous stage context
- Requirements alignment

### 4. Decision

**Approve**:
```python
await approval_service.approve(
    approval_id=approval.id,
    approved_by="tech_lead",
    message="Looks good! Approved for implementation.",
)
```

**Reject**:
```python
await approval_service.reject(
    approval_id=approval.id,
    rejected_by="tech_lead",
    reason="Need to reconsider the database schema. See comments.",
)
```

**Request Changes**:
```python
await approval_service.request_changes(
    approval_id=approval.id,
    requested_by="tech_lead",
    message="Please add caching layer and update API spec.",
)
```

### 5. Post-Decision

**Approved**:
- Session status → APPROVED
- Workflow can proceed to next stage automatically when
  `HITL_AUTO_ADVANCE_AFTER_APPROVAL=true`
- Audit trail updated

**Rejected**:
- Session status → REJECTED
- Workflow returns to specified stage
- Comments preserved for reference

## Escalation Policy

### Levels

1. **Level 1**: Tech Lead / Senior Developer
2. **Level 2**: Architect / Engineering Manager
3. **Level 3**: CTO / VP Engineering

### Escalation Triggers

- Timeout reached
- Complex technical decision
- Cross-team impact
- Security concerns

### Escalation Process

Escalation is defined in the state machine and policy model and is exposed via
API/service endpoints:
- `POST /approvals/{approval_id}/escalate`
- `POST /approvals/{approval_id}/cancel`
- `POST /approvals/{approval_id}/remind`

### Role/Level Routing

Escalation now supports optional role/level routing:

- `HITL_ESCALATION_POLICY_ENABLED` (default `true`)
- `HITL_ESCALATION_LEVELS` (default `developer,tech_lead,admin`)

When enabled, an escalation action attempts to route approval ownership to the
next higher role in the configured level chain (based on RBAC role resolution).
If matching higher-level approvers exist, runtime approvers are narrowed to that
target set for subsequent actions.

## Audit Trail

All approval actions are logged:

```json
{
    "approval_id": "uuid",
    "session_id": "uuid",
    "stage_name": "system_design",
    "history": [
        {
            "action": "create",
            "actor": "system",
            "timestamp": "2024-01-15T10:00:00Z",
            "state": "pending"
        },
        {
            "action": "approve",
            "actor": "tech_lead",
            "timestamp": "2024-01-15T14:30:00Z",
            "state": "approved",
            "details": {
                "message": "Looks good!"
            }
        }
    ]
}
```

## Best Practices

### For Requesters

1. **Provide context**: Include relevant artifacts
2. **Set reasonable timeouts**: Default 24 hours
3. **Notify approvers**: Send clear notification
4. **Be available**: Answer questions promptly

### For Approvers

1. **Review thoroughly**: Check all outputs
2. **Provide feedback**: Clear approval/rejection reasons
3. **Be timely**: Respond within timeout
4. **Document decisions**: For audit trail

### For System

1. **Send reminders**: Before timeout
2. **Enable escalation**: Auto-escalate on timeout
3. **Preserve history**: Full audit trail
4. **Notify stakeholders**: Keep everyone informed

## Security

1. **Authentication**: Approvers must be authenticated
2. **Authorization**: Check approver permissions (RBAC + SOP approver allowlist)
3. **Non-repudiation**: Actions are logged with user ID
4. **Audit**: All actions are auditable

RBAC runtime controls:
- `RBAC_ENABLED=true|false`
- `RBAC_DEFAULT_ROLE=<role>`
- `RBAC_USER_ROLES=user1:role1,user2:role2`

When RBAC denies an action, API returns `403`.

## Customization

Organizations can customize:
- Approval stages
- Timeout durations
- Approver roles
- Escalation paths
- Notification methods

## API Endpoints

### List Pending Approvals
```
GET /approvals
```

Supports query params:
- `state` (e.g. `pending`, `approved`, `rejected`)
- `session_id`
- `limit`
- `offset`

### Get Approval Details
```
GET /approvals/{approval_id}
```

### Approve
```
POST /approvals/{approval_id}/approve
{
    "user": "tech_lead",
    "message": "Approved"
}
```

### Reject
```
POST /approvals/{approval_id}/reject
{
    "user": "tech_lead",
    "reason": "Needs changes"
}
```

### Add Comment
```
POST /approvals/{approval_id}/comments
{
    "author": "tech_lead",
    "content": "Consider adding caching"
}
```

### Recover Session (manual recovery)
```
POST /sessions/{session_id}/recover
{
    "user": "tech_lead",
    "run_next": true
}
```

### Claim
```
POST /approvals/{approval_id}/claim
{
    "user": "tech_lead"
}
```

### Request Changes
```
POST /approvals/{approval_id}/request-changes
{
    "user": "tech_lead",
    "message": "Please update API contracts"
}
```

### Escalate
```
POST /approvals/{approval_id}/escalate
{
    "user": "tech_lead",
    "reason": "Cross-team decision required"
}
```

### Cancel
```
POST /approvals/{approval_id}/cancel
{
    "user": "requester",
    "reason": "Superseded by newer design"
}
```

### Remind
```
POST /approvals/{approval_id}/remind
{
    "user": "tech_lead",
    "message": "Reminder: approval is due today"
}
```

### Timeout Analytics
```
GET /approvals/analytics/timeouts?days=7&user=api-user
```

## Future Enhancements

1. **Batch Approvals**: Approve multiple stages at once
2. **Conditional Approvals**: Auto-approve based on criteria
3. **Delegation**: Temporarily delegate approval authority
4. **SLA Tracking**: Track approval response times
5. **Analytics**: Approval metrics and trends
