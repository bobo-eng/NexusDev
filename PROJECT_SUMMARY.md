# NexusDev Project Summary

## Overview

NexusDev is a **Multi-Agent Automated Development System** built with:
- **LangGraph** for workflow orchestration
- **MetaSOP** for stage definitions and transitions
- **Pydantic v2** for structured data validation

## Current Runtime Notes

- `SessionService.run_stage()` now supports runtime mode switching:
  - `single_stage` (default): execute one stage at a time via mapped agent
  - `full_graph`: execute the LangGraph workflow in one run
- Workflow mode can be set by env `NEXUSDEV_WORKFLOW_MODE` or request/CLI `mode` override.
- LangGraph workflow definitions remain under `packages/core/workflow/`.
- SOP now loads from YAML by default (with fallback to built-in MVP config when YAML load fails).
- API now supports approval detail and comment endpoints:
  - `GET /approvals/{approval_id}`
  - `POST /approvals/{approval_id}/comments`
- API now also supports approval lifecycle actions:
  - `POST /approvals/{approval_id}/claim`
  - `POST /approvals/{approval_id}/request-changes`
  - `POST /approvals/{approval_id}/escalate`
  - `POST /approvals/{approval_id}/cancel`
  - `POST /approvals/{approval_id}/remind`
- SOP `approvers` allowlist is now enforced by approval actions.
- RBAC is wired into API + service approval paths (`RBAC_ENABLED`, `RBAC_DEFAULT_ROLE`, `RBAC_USER_ROLES`).
- Approval lifecycle now emits notification events via configurable channels (log/webhook/email/dashboard webhook).
- Timeout handling supports pre-timeout reminders and optional auto-escalate/auto-reject policies.
- Escalation now supports role/level routing (`HITL_ESCALATION_POLICY_ENABLED`, `HITL_ESCALATION_LEVELS`).
- Timeout analytics endpoint added: `GET /approvals/analytics/timeouts` (by stage/by role/timeout rates).
- Session recovery endpoint/service added for manual recovery from `failed`/`rejected` states.
- Approval listing supports state filter and pagination.
- Workflow `wait_for_approval_node` now reads approval state from DB (no longer pure placeholder).
- Approval can auto-advance to next stage when `HITL_AUTO_ADVANCE_AFTER_APPROVAL=true`.
- Stage and approval flows now write runtime metrics through `core.observability.metrics`.
- BaseAgent now supports configurable LLM response caching (`LLM_CACHE_ENABLED`, `LLM_CACHE_TTL_SECONDS`, `LLM_CACHE_MAX_ENTRIES`).

## Project Structure

```
nexusdev/
├── pyproject.toml              # Python project config
├── README.md                   # Quick start guide
├── Dockerfile                  # Container image (fixed install order)
├── docker-compose.yml          # Multi-service deployment
│
├── apps/                       # Application layer
│   ├── cli/                    # Typer CLI (nexusdev command)
│   ├── api/                    # FastAPI REST service
│   └── worker/                 # Background task worker (implemented)
│
├── packages/
│   ├── core/                   # Business logic (Core First)
│   │   ├── domain/            # Session, Stage, Artifact, Review
│   │   ├── agents/            # 5 AI Agents with JSON mode
│   │   ├── workflow/          # LangGraph with WAIT routing
│   │   ├── sop/               # MetaSOP engine
│   │   ├── hitl/              # Approval state machine
│   │   ├── storage/           # Repository + ArtifactStorage
│   │   ├── services/          # Session/Stage/Approval services
│   │   ├── schemas/           # LLM output schemas
│   │   ├── prompts/           # Versioned system prompts
│   │   ├── config/            # Unified Settings loader
│   │   ├── observability/     # Structured logging + metrics
│   │   ├── security/          # Sanitization + RBAC
│   │   └── memory/            # Memory system (4 types + retrieval)
│   │       ├── stores/        # working/episodic/semantic/procedural
│   │       ├── retrieval/     # vector/graph search
│   │       └── manager.py     # unified entry point
│   │
│   └── adapters/               # Platform adapters
│       ├── openclaw/          # OpenClaw skill adapter
│       └── openwork/          # OpenWork plugin adapter
│
├── config/
│   ├── sop/default.yaml       # SOP workflow
│   ├── models/default.yaml    # LLM provider config
│   └── env/.env.example       # Environment template
│
├── tests/                      # Test suite
│   └── unit/                  # Domain + adapter tests
│
├── scripts/                    # Dev/CI scripts
└── docs/                       # Architecture docs
```

## Key Fixes (Code Review Response)

### ✅ Critical Blockers Fixed

| Issue | Fix Location | Description |
|-------|--------------|-------------|
| run_stage 不执行 | `session_service.py:171` | 实现 `_execute_workflow()` 真正调用 Agent |
| 审批链路未打通 | `session_service.py:208` | `wait_for_approval()` + `mark_waiting_approval()` |
| WAIT 路由死角 | `graph.py:143` | 添加 `wait_for_approval_node` + `WAIT` 分支映射 |
| 审批仅内存存储 | `approval_service.py:22` | 实现 `ApprovalRepository` 持久化到 DB |
| Worker 占位 | `worker/main.py:77` | 实现 `_process_pending_stages()` + `_check_timeouts()` |
| Dockerfile 顺序 | `Dockerfile:16` | 先 COPY 代码再 `pip install -e .` |
| list_sessions 空 | `session_service.py:300` | 实现 `SessionRepository.get_all()` |

### ✅ Optimizations Implemented

| Feature | Location | Description |
|---------|----------|-------------|
| 幂等阶段执行 | `session_service.py:127` | 检查现有 stage 避免重复创建 |
| Prompt 版本化 | `base.py:45` | `PROMPT_VERSION` + `SCHEMA_VERSION` |
| JSON mode | `base.py:96` | OpenAI `response_format={"type": "json_object"}` |
| 产物分层存储 | `artifact_storage.py` | DB 存元数据，文件系统存内容 |
| 统一配置 | `config/settings.py` | `Settings` 类加载 env + YAML |
| 结构化日志 | `observability/logger.py` | `session_id/stage_id/agent_name` 自动注入 |
| 指标收集 | `observability/metrics.py` | 成功率、执行时间、重试次数 |
| 契约测试 | `tests/unit/test_adapters.py` | OpenClaw/OpenWork 兼容性测试 |
| 安全脱敏 | `security/sanitizer.py` | API key、password 自动脱敏 |
| RBAC | `security/rbac.py` | admin/tech_lead/developer/viewer 角色 |

## Workflow

```
Requirement Analysis (PM Agent)
    ↓
System Design (Architect Agent)
    ↓
[HITL Checkpoint: Human Approval Required]
    ↓ ← Reject 返回 redesign
Coding (Coder Agent)
    ↓
Code Review (Reviewer Agent)
    ↓ ← Request changes 返回 coding
Testing (Tester Agent)
    ↓ ← Fail 返回 coding
Complete
```

## Memory System

NexusDev implements a 4-type memory system for contextual awareness:

### Memory Types

| Type | Purpose | Scope | Storage |
|------|---------|-------|---------|
| **Working** | Current session context | Session | In-memory (LRU) |
| **Episodic** | Agent interaction history | Session/Project | Database |
| **Semantic** | Knowledge base, patterns | Project/Global | DB + Vector Store |
| **Procedural** | SOPs, workflows | Global | Database |

### Agent Memory Profiles

```python
# PM Agent
input: [WORKING, EPISODIC]
output: [EPISODIC, SEMANTIC]
special: ["requirement_history", "user_preferences"]

# Architect Agent
input: [WORKING, SEMANTIC]
output: [EPISODIC, SEMANTIC, PROCEDURAL]
special: ["design_decisions", "tech_constraints"]

# Coder Agent
input: [WORKING, SEMANTIC, PROCEDURAL]
output: [EPISODIC]
special: ["code_dependencies", "coding_patterns"]
```

### Memory Operations

```python
from core.memory import get_memory_manager

memory = get_memory_manager()

# Store memory
await memory.remember(
    content="Design decision: Use PostgreSQL",
    agent_name="architect_agent",
    memory_type=MemoryType.SEMANTIC,
    importance=0.9,
)

# Recall memories
results = await memory.recall(
    query="database design",
    agent_name="architect_agent",
    limit=5,
)

# Semantic search
similar = await memory.find_similar_memories(
    content="How to handle user authentication?",
    limit=3,
)

# Get code dependencies
deps = await memory.get_code_dependencies("src/auth.py")
```

### Retrieval Mechanisms

- **Vector Search**: Semantic similarity using embeddings
- **Graph Traversal**: Code dependency navigation
- **Keyword Search**: Exact match for tags/content

### Memory Lifecycle

1. **Creation**: Agent stores output to appropriate memory type
2. **Compression**: Old memories summarized automatically
3. **Pruning**: Low-importance memories removed
4. **Consolidation**: Similar memories merged

## Usage

### CLI

```bash
# Create session
nexusdev create "My Project" "Build a REST API"

# Check status
nexusdev status <session-id>

# Run workflow stage (idempotent)
nexusdev run <session-id>

# Approve pending stage
nexusdev approve <session-id> <stage-id> -m "LGTM!"

# List sessions
nexusdev list
```

### API

```bash
# Start API server
uvicorn apps.api.main:app --reload

# Create session
curl -X POST http://localhost:8000/sessions \
  -d '{"name": "My Project", "requirement": "Build API"}'

# Get status
curl http://localhost:8000/sessions/<session-id>

# Approve stage
curl -X POST http://localhost:8000/sessions/<id>/stages/<id>/approve \
  -d '{"user": "admin", "message": "Approved"}'
```

### Docker

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api
```

## Configuration

### Environment Variables

```bash
# Required
OPENAI_API_KEY=sk-...
DATABASE_URL=sqlite+aiosqlite:///./nexusdev.db

# Optional
LOG_LEVEL=INFO
WORKER_POLL_INTERVAL=5
HITL_DEFAULT_TIMEOUT_HOURS=24
```

### SOP Customization

```yaml
# config/sop/default.yaml
stages:
  - name: system_design
    requires_approval: true      # Enable HITL
    approval_timeout_hours: 24
    on_success: coding
    on_reject: requirement_analysis  # Reject → go back
```

## Observability

### Structured Logs

```json
{
  "timestamp": "2024-01-15T10:00:00Z",
  "level": "INFO",
  "message": "Stage completed",
  "session_id": "uuid",
  "stage_id": "uuid",
  "agent_name": "architect_agent",
  "trace_id": "uuid"
}
```

### Metrics

```python
from core.observability.metrics import get_metrics

metrics = get_metrics()
metrics.get_overall_success_rate()  # 0.95
metrics.get_agent_success_rate("coder_agent")  # 0.98
metrics.get_approval_stats()  # {approved: 10, rejected: 2, ...}
```

## Security

### Content Sanitization

```python
from core.security.sanitizer import sanitize_content

safe = sanitize_content("API key: sk-abc123...")
# → "API key: [OPENAI_API_KEY_REDACTED]"
```

### RBAC

```python
from core.security.rbac import get_rbac, Permission

rbac = get_rbac()
rbac.assign_role("user123", "tech_lead")
rbac.check_permission("user123", Permission.APPROVAL_APPROVE)  # True
```

## Development

```bash
# Setup
bash scripts/dev.sh

# Run tests
pytest tests/unit/

# Lint
ruff check .

# Type check
mypy packages/

# CI
bash scripts/ci.sh
```

## Stats

- **72 Python files**
- **~12,000 lines of code**
- **100% syntax valid**
- **5 AI agents**
- **3-layer architecture** (core/adapters/apps)

## License

MIT License
