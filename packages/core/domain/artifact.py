"""Artifact entity representing workflow outputs."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ArtifactType(str, Enum):
    """Types of artifacts produced during development."""
    
    # Requirements
    PRD = "prd"  # Product Requirements Document
    USER_STORIES = "user_stories"
    
    # Design
    SYSTEM_DESIGN = "system_design"
    API_SPEC = "api_spec"
    DATABASE_SCHEMA = "database_schema"
    ARCHITECTURE_DIAGRAM = "architecture_diagram"
    
    # Code
    SOURCE_CODE = "source_code"
    CONFIGURATION = "configuration"
    MIGRATION = "migration"
    
    # Review
    CODE_REVIEW = "code_review"
    DESIGN_REVIEW = "design_review"
    
    # Testing
    TEST_PLAN = "test_plan"
    TEST_CASES = "test_cases"
    TEST_RESULTS = "test_results"
    COVERAGE_REPORT = "coverage_report"
    
    # Documentation
    README = "readme"
    API_DOCUMENTATION = "api_documentation"
    DEPLOYMENT_GUIDE = "deployment_guide"
    
    # Misc
    LOG = "log"
    METRICS = "metrics"
    CUSTOM = "custom"


class Artifact(BaseModel):
    """An artifact produced during the development workflow.
    
    Artifacts represent all tangible outputs: documents, code,
    configurations, test results, etc.
    """
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    stage_id: UUID | None = Field(default=None)
    
    # Artifact definition
    name: str = Field(..., min_length=1, max_length=200)
    artifact_type: ArtifactType
    description: str = Field(default="", max_length=1000)
    
    # Content
    content: str = Field(default="")
    content_type: str = Field(default="text/plain")
    
    # File storage (optional)
    file_path: str | None = Field(default=None)
    file_size: int | None = Field(default=None)
    checksum: str | None = Field(default=None)
    
    # Metadata
    language: str | None = Field(default=None)  # For code artifacts
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Versioning
    version: int = Field(default=1, ge=1)
    previous_version_id: UUID | None = Field(default=None)
    
    # Relations
    parent_artifact_ids: list[UUID] = Field(default_factory=list)
    derived_artifact_ids: list[UUID] = Field(default_factory=list)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Creator
    created_by: str = Field(default="system")  # Agent name or user
    
    # Validation
    is_validated: bool = Field(default=False)
    validation_result: dict[str, Any] = Field(default_factory=dict)
    
    def update_content(self, content: str) -> "Artifact":
        """Update artifact content."""
        self.content = content
        self.updated_at = datetime.utcnow()
        return self
    
    def link_file(self, path: str, size: int, checksum: str) -> "Artifact":
        """Link a file to this artifact."""
        self.file_path = path
        self.file_size = size
        self.checksum = checksum
        self.updated_at = datetime.utcnow()
        return self
    
    def add_parent(self, artifact_id: UUID) -> "Artifact":
        """Add a parent artifact relationship."""
        if artifact_id not in self.parent_artifact_ids:
            self.parent_artifact_ids.append(artifact_id)
        return self
    
    def add_derived(self, artifact_id: UUID) -> "Artifact":
        """Add a derived artifact relationship."""
        if artifact_id not in self.derived_artifact_ids:
            self.derived_artifact_ids.append(artifact_id)
        return self
    
    def validate(self, result: dict[str, Any]) -> "Artifact":
        """Mark artifact as validated with results."""
        self.is_validated = True
        self.validation_result = result
        self.updated_at = datetime.utcnow()
        return self
    
    def get_summary(self, max_length: int = 200) -> str:
        """Get a summary of the artifact content."""
        if len(self.content) <= max_length:
            return self.content
        return self.content[:max_length] + "..."
    
    def is_code(self) -> bool:
        """Check if artifact is code."""
        return self.artifact_type == ArtifactType.SOURCE_CODE
    
    def is_document(self) -> bool:
        """Check if artifact is a document."""
        return self.artifact_type in {
            ArtifactType.PRD,
            ArtifactType.SYSTEM_DESIGN,
            ArtifactType.API_SPEC,
            ArtifactType.README,
            ArtifactType.API_DOCUMENTATION,
            ArtifactType.DEPLOYMENT_GUIDE,
        }
