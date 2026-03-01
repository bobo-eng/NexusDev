# NexusDev

Multi-Agent Automated Development System powered by LangGraph + MetaSOP.

## Overview

NexusDev is an intelligent development automation system that orchestrates multiple AI agents to transform user requirements into production-ready code. The system follows a structured workflow with human-in-the-loop approval checkpoints.

## Architecture

```
nexusdev/
├── apps/
│   ├── cli/          # Command-line interface
│   ├── api/          # FastAPI REST service
│   └── worker/       # Background task worker
├── packages/
│   ├── core/         # Core business logic
│   │   ├── domain/   # Entities (Session, Stage, Artifact, Review)
│   │   ├── workflow/ # LangGraph workflow definition
│   │   ├── sop/      # MetaSOP rule engine
│   │   ├── agents/   # AI agents (PM, Architect, Coder, Reviewer, Tester)
│   │   ├── prompts/  # System prompts
│   │   ├── schemas/  # LLM output schemas
│   │   ├── hitl/     # Human-in-the-loop approval
│   │   ├── storage/  # Repository pattern
│   │   └── services/ # Application services
│   └── adapters/     # Platform adapters
│       ├── openclaw/ # OpenClaw integration
│       └── openwork/ # OpenWork integration
├── config/           # Configuration files
├── tests/            # Test suites
└── docs/             # Documentation
```

## Core Principles

1. **Core First**: All business logic resides in `core/`, adapters are thin wrappers
2. **Structured Output**: All agents produce validated JSON output
3. **Human Approval**: Critical checkpoints require human approval
4. **Traceability**: All artifacts and decisions are persisted

## Workflow

```
Requirement Analysis (PM Agent)
    ↓
System Design (Architect Agent)
    ↓
[HITL Checkpoint: Human Approval Required]
    ↓
Coding (Coder Agent)
    ↓
Code Review (Reviewer Agent)
    ↓
Testing (Tester Agent)
    ↓
Complete
```

## Quick Start

### Installation

```bash
# Clone repository
git clone <repo-url>
cd nexusdev

# Install dependencies
pip install -e "."

# Set environment variables
cp config/env/.env.example config/env/.env
# Edit .env with your API keys
```

### CLI Usage

```bash
# Create a session
nexusdev create "My Project" "Build a REST API for user management"

# Check status
nexusdev status <session-id>

# Run workflow stage
nexusdev run <session-id>

# Approve pending stage
nexusdev approve <session-id> <stage-id> -m "Looks good!"

# List sessions
nexusdev list

# View workflow
nexusdev workflow
```

### API Usage

```bash
# Start API server
uvicorn apps.api.main:app --reload

# Create session
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Project",
    "requirement": "Build a REST API for user management"
  }'

# Get status
curl http://localhost:8000/sessions/<session-id>

# Approve stage
curl -X POST http://localhost:8000/sessions/<session-id>/stages/<stage-id>/approve \
  -H "Content-Type: application/json" \
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

### SOP Configuration

Edit `config/sop/default.yaml` to customize the workflow:

```yaml
stages:
  - name: system_design
    requires_approval: true  # Enable HITL
    approval_timeout_hours: 24
```

### Model Configuration

Edit `config/models/default.yaml` to configure LLM providers:

```yaml
providers:
  openai:
    models:
      - name: gpt-4
        temperature: 0.2
```

## Agents

| Agent | Role | Output |
|-------|------|--------|
| PM Agent | Requirement Analysis | PRD, User Stories |
| Architect Agent | System Design | Architecture, API Spec, DB Schema |
| Coder Agent | Implementation | Source Code |
| Reviewer Agent | Code Review | Review Report |
| Tester Agent | Testing | Test Cases, Coverage Report |

## Development

```bash
# Run tests
pytest

# Run linting
ruff check .

# Run type checking
mypy packages/

# Format code
ruff format .
```

## License

MIT License
