# NexusDev Architecture

## System Overview

NexusDev is a multi-agent automated development system built on three core technologies:
- **LangGraph**: Workflow orchestration and state management
- **MetaSOP**: Standard Operating Procedure engine for stage definitions
- **Pydantic**: Data validation and structured outputs

## Design Principles

### 1. Core First Architecture

All business logic resides in `packages/core/`. Platform adapters (`packages/adapters/`) are thin wrappers that only handle:
- Parameter mapping
- Tool call conversion
- Session context forwarding

```
┌─────────────────────────────────────────────────────────┐
│                      Core Layer                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐  │
│  │ Session │ │  Stage  │ │ Artifact│ │   Review    │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────────┘  │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐  │
│  │  SOP    │ │Workflow │ │  HITL   │ │   Agents    │  │
│  │ Engine  │ │ Graph   │ │   SM    │ │             │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────────┘  │
└─────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   OpenClaw   │  │   OpenWork   │  │     CLI      │
│   Adapter    │  │   Adapter    │  │     API      │
└──────────────┘  └──────────────┘  └──────────────┘
```

### 2. Structured Output

All LLM agents produce validated JSON output:

```python
class CodingOutput(BaseModel):
    files: list[CodeFile]
    dependencies: dict[str, Any]
    setup_instructions: list[str]
```

Benefits:
- Type safety
- Automatic retry on validation failure
- Consistent processing

### 3. Human-in-the-Loop

Critical checkpoints require human approval:

```
System Design ──► [WAITING_APPROVAL] ──► Human Review ──► [APPROVED/REJECTED]
```

The approval state machine supports:
- Approve with comments
- Request changes
- Reject with reason
- Escalate to higher authority
- Timeout handling
- Approver allowlist enforcement from SOP `approvers`

## Component Details

### Domain Layer

**Session**: Represents a complete development workflow
- Lifecycle: CREATED → RUNNING → WAITING_APPROVAL → APPROVED → COMPLETED
- Tracks current stage and completed stages
- Stores requirement and context

**Stage**: Represents a workflow phase
- Types: REQUIREMENT_ANALYSIS, SYSTEM_DESIGN, CODING, CODE_REVIEW, TESTING
- Status: PENDING → RUNNING → [WAITING_APPROVAL] → COMPLETED/FAILED
- Links input/output artifacts

**Artifact**: Represents workflow outputs
- Types: PRD, SYSTEM_DESIGN, SOURCE_CODE, TEST_RESULTS, etc.
- Content stored inline or linked to file
- Versioning and parent/child relationships

**Review**: Represents code/design review
- Types: CODE_REVIEW, DESIGN_REVIEW, SECURITY_REVIEW
- Comments with severity levels
- Quality scores

### Workflow Layer (LangGraph + SessionService)

The repository includes a complete LangGraph workflow definition for full
orchestration scenarios, and the current runtime path executes one stage at a
time through `SessionService.run_stage()` using SOP rules to choose the next stage.

LangGraph graph definition example:

```python
workflow.add_node("requirement_analysis", requirement_analysis_node)
workflow.add_node("system_design", system_design_node)
workflow.add_node("human_approval", human_approval_node)
workflow.add_node("coding", coding_node)
workflow.add_node("code_review", code_review_node)
workflow.add_node("testing", testing_node)

workflow.add_conditional_edges(
    "system_design",
    lambda state: route_stage(state, "system_design"),
    {
        RouteDecision.PROCEED: "human_approval",
        RouteDecision.RETRY: "system_design",
        RouteDecision.FAIL: "error_handler",
    },
)
```

### SOP Layer (MetaSOP)

SOP configuration defines:
- Stage definitions with agent assignments
- Transition rules (on_success, on_failure, on_reject)
- Approval requirements
- Retry policies
- Timeout settings

```yaml
stages:
  - name: system_design
    agent_name: architect_agent
    requires_approval: true
    on_success: coding
    on_failure: _FAILURE_
    on_reject: requirement_analysis
```

### Agent Layer

Each agent:
1. Inherits from `BaseAgent`
2. Defines output schema
3. Implements `execute(context)` method
4. Uses retry logic for LLM calls

```python
class ArchitectAgent(BaseAgent):
    async def execute(self, context: dict) -> SystemDesignOutput:
        result = await self._call_llm(
            system_prompt=SYSTEM_DESIGN_PROMPT,
            user_prompt=self._build_prompt(context),
            output_schema=SystemDesignOutput,
        )
        return result
```

### Storage Layer

Repository pattern provides clean data access:

```python
class SessionRepository:
    async def get_by_id(self, id: UUID) -> Session | None
    async def create(self, entity: Session) -> Session
    async def update(self, entity: Session) -> Session
    async def delete(self, id: UUID) -> bool
```

Supports:
- PostgreSQL (production)
- SQLite (MVP/development)

### Service Layer

Application services provide high-level operations:

```python
class SessionService:
    async def create_session(...) -> Session
    async def run_stage(...) -> dict
    async def approve_stage(...) -> dict
    async def get_status(...) -> dict
```

## Data Flow

### 1. Session Creation

```
CLI/API ──► SessionService.create_session() ──► SessionRepository ──► DB
```

### 2. Stage Execution (Current Runtime)

```
CLI/API ──► SessionService.run_stage()
                    │
                    ▼
     Determine next stage via SOP config
                    │
                    ▼
            Agent.execute()
                    │
                    ▼
            LLM API (OpenAI/Anthropic)
                    │
                    ▼
            StageRepository.update()
                    │
                    ▼
            DB
```

Note: LangGraph nodes/routers are available in `packages/core/workflow/` but are
not the default execution entrypoint in the current runtime path. The
`wait_for_approval_node` now polls approval state from persistence and can
route on approved/rejected/timed_out outcomes.

### 3. Human Approval

```
CLI/API ──► SessionService.approve_stage()
                    │
                    ▼
            ApprovalStateMachine.approve()
                    │
                    ▼
            Session.mark_approved()
                    │
                    ▼
            DB
```

Optional behavior:
- If `HITL_AUTO_ADVANCE_AFTER_APPROVAL=true`, approval triggers `run_stage()` for the next stage.

## Error Handling

### Retry Logic

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
)
async def _call_llm(...) -> T:
    ...
```

### Stage Failure

1. Increment retry count
2. If retries exhausted → FAIL
3. Otherwise → RETRY same stage

### Workflow Failure

1. Mark session as FAILED
2. Store error message
3. Notify user
4. Enable manual recovery

## Security Considerations

1. **API Keys**: Stored in environment variables, never in code
2. **Secrets**: Not included in artifacts or logs
3. **Approval**: Critical stages require human approval with SOP approver allowlists
4. **RBAC**: API and services enforce role permissions for approval actions
5. **Sandboxing**: Code execution in isolated environment (future)

## Scalability

### Horizontal Scaling

- Stateless API servers
- Shared database
- Redis for caching and task queue
- Worker pool for background tasks

### Performance Optimizations

- Async/await throughout
- Connection pooling
- Artifact content lazy loading
- LLM response caching (configurable via `LLM_CACHE_*`)

## Future Enhancements

1. **Parallel Execution**: Multiple agents working simultaneously
2. **Sub-workflows**: Nested workflows for complex tasks
3. **A/B Testing**: Compare multiple implementations
4. **Metrics**: Track success rates, quality scores
5. **Learning**: Improve prompts based on outcomes
