"""Structured output schemas for LLM agents.

All agents must produce outputs conforming to these schemas.
This enables validation, retry logic, and consistent processing.
"""

from typing import Any

from pydantic import BaseModel, Field


class RequirementAnalysisOutput(BaseModel):
    """Output schema for Requirement Analysis Agent (PM)."""
    
    summary: str = Field(..., description="Brief summary of the requirements")
    user_stories: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of user stories with acceptance criteria"
    )
    functional_requirements: list[str] = Field(
        default_factory=list,
        description="List of functional requirements"
    )
    non_functional_requirements: list[str] = Field(
        default_factory=list,
        description="List of non-functional requirements"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Technical or business constraints"
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions made during analysis"
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Questions that need clarification"
    )
    complexity_estimate: str = Field(
        default="medium",
        description="Complexity estimate: low, medium, high"
    )
    suggested_technologies: list[str] = Field(
        default_factory=list,
        description="Suggested technology stack"
    )


class APISpec(BaseModel):
    """API endpoint specification."""
    
    path: str = Field(..., description="API path")
    method: str = Field(..., description="HTTP method")
    description: str = Field(..., description="What this endpoint does")
    request_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="Request body schema"
    )
    response_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="Response body schema"
    )


class DatabaseTable(BaseModel):
    """Database table specification."""
    
    name: str = Field(..., description="Table name")
    columns: list[dict[str, Any]] = Field(..., description="Column definitions")
    indexes: list[str] = Field(default_factory=list, description="Index definitions")
    relationships: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Foreign key relationships"
    )


class SystemDesignOutput(BaseModel):
    """Output schema for System Design Agent (Architect)."""
    
    overview: str = Field(..., description="High-level system overview")
    architecture_style: str = Field(
        ...,
        description="Architecture pattern: monolith, microservices, serverless, etc."
    )
    components: list[dict[str, Any]] = Field(
        ...,
        description="System components with responsibilities"
    )
    data_flow: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Data flow between components"
    )
    api_specs: list[APISpec] = Field(
        default_factory=list,
        description="API specifications"
    )
    database_schema: list[DatabaseTable] = Field(
        default_factory=list,
        description="Database schema design"
    )
    external_dependencies: list[str] = Field(
        default_factory=list,
        description="External services/libraries needed"
    )
    security_considerations: list[str] = Field(
        default_factory=list,
        description="Security measures to implement"
    )
    scalability_plan: str = Field(
        default="",
        description="How the system scales"
    )
    deployment_strategy: str = Field(
        default="",
        description="Recommended deployment approach"
    )
    risks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Identified risks and mitigations"
    )


class CodeFile(BaseModel):
    """A single code file output."""
    
    path: str = Field(..., description="File path relative to project root")
    language: str = Field(..., description="Programming language")
    content: str = Field(..., description="Complete file content")
    description: str = Field(default="", description="What this file does")
    dependencies: list[str] = Field(
        default_factory=list,
        description="Files this depends on"
    )


class CodingOutput(BaseModel):
    """Output schema for Coding Agent."""
    
    files: list[CodeFile] = Field(..., description="Generated code files")
    entry_points: list[str] = Field(
        default_factory=list,
        description="Main entry point files"
    )
    dependencies: dict[str, Any] = Field(
        default_factory=dict,
        description="Package dependencies (npm, pip, etc.)"
    )
    environment_vars: list[str] = Field(
        default_factory=list,
        description="Required environment variables"
    )
    setup_instructions: list[str] = Field(
        default_factory=list,
        description="Steps to set up the project"
    )
    testing_instructions: list[str] = Field(
        default_factory=list,
        description="How to run tests"
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Additional implementation notes"
    )


class CodeIssue(BaseModel):
    """A code issue found during review."""
    
    severity: str = Field(..., description="critical, major, minor, suggestion")
    category: str = Field(
        ...,
        description="Issue category: style, security, performance, bug, etc."
    )
    file_path: str | None = Field(default=None, description="File with issue")
    line_number: int | None = Field(default=None, description="Line number")
    message: str = Field(..., description="Issue description")
    suggestion: str = Field(default="", description="How to fix")


class CodeReviewOutput(BaseModel):
    """Output schema for Code Review Agent."""
    
    summary: str = Field(..., description="Overall review summary")
    issues: list[CodeIssue] = Field(
        default_factory=list,
        description="Issues found"
    )
    positive_points: list[str] = Field(
        default_factory=list,
        description="What's done well"
    )
    quality_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Overall quality score 0-100"
    )
    security_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Security assessment 0-100"
    )
    performance_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Performance assessment 0-100"
    )
    maintainability_score: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Maintainability assessment 0-100"
    )
    recommendation: str = Field(
        ...,
        description="APPROVE, APPROVE_WITH_COMMENTS, or REQUEST_CHANGES"
    )
    suggested_refactorings: list[str] = Field(
        default_factory=list,
        description="Suggested improvements"
    )


class TestCase(BaseModel):
    """A single test case."""
    
    name: str = Field(..., description="Test case name")
    description: str = Field(..., description="What this test verifies")
    test_type: str = Field(
        ...,
        description="unit, integration, e2e, performance, security"
    )
    target: str = Field(..., description="What is being tested")
    steps: list[str] = Field(..., description="Test steps")
    expected_result: str = Field(..., description="Expected outcome")
    prerequisites: list[str] = Field(
        default_factory=list,
        description="Setup needed before test"
    )


class TestResult(BaseModel):
    """Result of running tests."""
    
    test_name: str = Field(..., description="Test that was run")
    status: str = Field(..., description="passed, failed, skipped, error")
    duration_ms: int = Field(default=0, description="Test execution time")
    message: str = Field(default="", description="Result message")
    output: str = Field(default="", description="Test output/logs")


class TestingOutput(BaseModel):
    """Output schema for Testing Agent."""
    
    test_plan: str = Field(..., description="Overall testing strategy")
    test_cases: list[TestCase] = Field(
        default_factory=list,
        description="Defined test cases"
    )
    test_files: list[CodeFile] = Field(
        default_factory=list,
        description="Generated test code files"
    )
    coverage_target: int = Field(
        default=80,
        ge=0,
        le=100,
        description="Target code coverage percentage"
    )
    execution_results: list[TestResult] = Field(
        default_factory=list,
        description="Results from test execution"
    )
    coverage_report: dict[str, Any] = Field(
        default_factory=dict,
        description="Coverage statistics"
    )
    issues_found: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Bugs/issues discovered"
    )
    recommendation: str = Field(
        ...,
        description="PASS, PASS_WITH_WARNINGS, or FAIL"
    )
