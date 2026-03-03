# Prompt Specification

## Overview

All agents in NexusDev use structured prompts with validated JSON output. This document specifies the prompt format and output schemas.

## Prompt Structure

### System Prompt

Each agent has a system prompt that defines:
1. Agent role and responsibilities
2. Task description
3. Output format specification
4. Rules and constraints

```
You are a {ROLE} agent. Your role is to {DESCRIPTION}.

## Your Task
{TASK_DESCRIPTION}

## Guidelines
1. {GUIDELINE_1}
2. {GUIDELINE_2}
...

## Output Format
You MUST respond with a valid JSON object matching this structure:
{SCHEMA_EXAMPLE}

## Rules
- {RULE_1}
- {RULE_2}
...
```

### User Prompt

The user prompt provides context-specific input:

```
# {TASK_NAME}

## {CONTEXT_SECTION_1}
{content}

## {CONTEXT_SECTION_2}
{content}
...
```

## Agent Prompts

### 1. Requirement Analysis (PM Agent)

**System Prompt**: `REQUIREMENT_ANALYSIS_PROMPT`

**Purpose**: Analyze user requirements and produce structured PRD

**Output Schema**: `RequirementAnalysisOutput`

```json
{
    "summary": "Brief summary",
    "user_stories": [
        {
            "id": "US-001",
            "title": "Story title",
            "description": "As a... I want... so that...",
            "acceptance_criteria": ["Given... When... Then..."],
            "priority": "high"
        }
    ],
    "functional_requirements": ["FR1: ..."],
    "non_functional_requirements": ["NFR1: ..."],
    "constraints": ["Constraint 1"],
    "assumptions": ["Assumption 1"],
    "open_questions": ["Question 1"],
    "complexity_estimate": "medium",
    "suggested_technologies": ["Python", "FastAPI"]
}
```

### 2. System Design (Architect Agent)

**System Prompt**: `SYSTEM_DESIGN_PROMPT`

**Purpose**: Create technical architecture based on requirements

**Output Schema**: `SystemDesignOutput`

```json
{
    "overview": "High-level description",
    "architecture_style": "microservices",
    "components": [
        {
            "name": "Component name",
            "responsibility": "What it does",
            "interfaces": ["API endpoints"],
            "dependencies": ["Other components"]
        }
    ],
    "data_flow": [
        {
            "from": "Component A",
            "to": "Component B",
            "data": "What data flows",
            "protocol": "HTTP"
        }
    ],
    "api_specs": [
        {
            "path": "/api/users",
            "method": "POST",
            "description": "Create user",
            "request_schema": {},
            "response_schema": {}
        }
    ],
    "database_schema": [
        {
            "name": "users",
            "columns": [{"name": "id", "type": "UUID", "constraints": "PK"}],
            "indexes": ["idx_email"],
            "relationships": []
        }
    ],
    "external_dependencies": ["Redis", "AWS S3"],
    "security_considerations": ["JWT auth", "Rate limiting"],
    "scalability_plan": "How to scale",
    "deployment_strategy": "Docker + K8s",
    "risks": [{"risk": "Description", "impact": "high", "mitigation": "Strategy"}]
}
```

### 3. Coding (Coder Agent)

**System Prompt**: `CODING_PROMPT`

**Purpose**: Implement code based on system design

**Output Schema**: `CodingOutput`

```json
{
    "files": [
        {
            "path": "src/main.py",
            "language": "python",
            "content": "Complete file content...",
            "description": "Main entry point",
            "dependencies": ["src/config.py"]
        }
    ],
    "entry_points": ["src/main.py"],
    "dependencies": {
        "pip": ["fastapi>=0.100", "pydantic>=2.0"],
        "npm": [],
        "system": []
    },
    "environment_vars": ["DATABASE_URL", "API_KEY"],
    "setup_instructions": ["pip install -r requirements.txt"],
    "testing_instructions": ["pytest tests/"],
    "notes": ["Important implementation note"]
}
```

### 4. Code Review (Reviewer Agent)

**System Prompt**: `CODE_REVIEW_PROMPT`

**Purpose**: Review code for quality, security, and maintainability

**Output Schema**: `CodeReviewOutput`

```json
{
    "summary": "Overall assessment",
    "issues": [
        {
            "severity": "critical/major/minor/suggestion",
            "category": "security/performance/style/bug",
            "file_path": "src/main.py",
            "line_number": 42,
            "message": "Issue description",
            "suggestion": "How to fix"
        }
    ],
    "positive_points": ["Good error handling", "Clean code"],
    "quality_score": 85,
    "security_score": 90,
    "performance_score": 80,
    "maintainability_score": 85,
    "recommendation": "APPROVE/APPROVE_WITH_COMMENTS/REQUEST_CHANGES",
    "suggested_refactorings": ["Extract method", "Use constant"]
}
```

**Scoring Guide**:
- 90-100: Excellent, production-ready
- 80-89: Good, minor issues
- 70-79: Acceptable, needs improvements
- 60-69: Poor, significant issues
- <60: Unacceptable, major rework needed

### 5. Testing (Tester Agent)

**System Prompt**: `TESTING_PROMPT`

**Purpose**: Create and execute tests

**Output Schema**: `TestingOutput`

```json
{
    "test_plan": "Overall testing strategy",
    "test_cases": [
        {
            "name": "Test case name",
            "description": "What it tests",
            "test_type": "unit/integration/e2e",
            "target": "Function/module being tested",
            "steps": ["Step 1", "Step 2"],
            "expected_result": "What should happen",
            "prerequisites": ["Setup needed"]
        }
    ],
    "test_files": [
        {
            "path": "tests/test_main.py",
            "language": "python",
            "content": "Test code..."
        }
    ],
    "coverage_target": 80,
    "execution_results": [
        {
            "test_name": "test_name",
            "status": "passed/failed/skipped",
            "duration_ms": 100,
            "message": "Result details",
            "output": "Test output"
        }
    ],
    "coverage_report": {
        "overall": 85,
        "by_file": {"src/main.py": 90}
    },
    "issues_found": [
        {"severity": "high", "description": "Bug found", "location": "main.py:42"}
    ],
    "recommendation": "PASS/PASS_WITH_WARNINGS/FAIL"
}
```

## Prompt Engineering Guidelines

### 1. Be Specific

- Use concrete examples
- Define clear boundaries
- Specify output format precisely

### 2. Provide Context

- Include relevant background
- Reference previous outputs
- Explain constraints

### 3. Use Structured Output

- Always require JSON
- Define schemas explicitly
- Handle parsing errors gracefully

### 4. Set Constraints

- Limit response length
- Define valid values
- Specify required fields

### 5. Include Examples

- Show expected output format
- Provide sample inputs
- Demonstrate edge cases

## Error Handling

### Parsing Errors

When LLM output doesn't match schema:

1. Try to extract JSON from markdown
2. Attempt to fix common issues (missing fields)
3. Retry with clearer prompt
4. Fail gracefully with error message

### Validation Errors

When output fails Pydantic validation:

1. Log specific validation errors
2. Return partial results if possible
3. Retry with schema reminder

## Versioning

Prompts are versioned with the system:
- Major changes: New schema versions
- Minor changes: Clarifications, examples
- Patch changes: Typos, formatting

## Customization

Users can customize prompts by:
1. Creating new prompt files
2. Extending base agent classes
3. Overriding `get_system_prompt()` method

## Best Practices

1. **Test prompts** with diverse inputs
2. **Monitor success rates** for each agent
3. **Iterate based on feedback**
4. **Keep prompts DRY** - reuse common sections
5. **Document assumptions** in prompts
