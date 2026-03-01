"""Unit tests for domain entities."""

import pytest
from uuid import uuid4

from core.domain.session import Session, SessionStatus
from core.domain.stage import Stage, StageStatus, StageType
from core.domain.artifact import Artifact, ArtifactType
from core.domain.review import Review, ReviewStatus, ReviewType


class TestSession:
    """Tests for Session entity."""
    
    def test_create_session(self):
        """Test creating a session."""
        session = Session(
            name="Test Session",
            requirement="Build a test API",
        )
        
        assert session.name == "Test Session"
        assert session.requirement == "Build a test API"
        assert session.status == SessionStatus.CREATED
        assert session.is_active() is True
    
    def test_session_lifecycle(self):
        """Test session status transitions."""
        session = Session(
            name="Test",
            requirement="Test requirement",
        )
        
        # Start running
        session.mark_running()
        assert session.status == SessionStatus.RUNNING
        
        # Wait for approval
        session.mark_waiting_approval()
        assert session.status == SessionStatus.WAITING_APPROVAL
        assert session.can_approve() is True
        assert session.can_reject() is True
        
        # Approve
        session.mark_approved()
        assert session.status == SessionStatus.APPROVED
        
        # Complete
        session.mark_completed()
        assert session.status == SessionStatus.COMPLETED
        assert session.is_active() is False
    
    def test_advance_stage(self):
        """Test advancing to next stage."""
        session = Session(
            name="Test",
            requirement="Test",
        )
        
        stage1_id = uuid4()
        stage2_id = uuid4()
        
        session.advance_stage(stage1_id)
        assert session.current_stage_id == stage1_id
        assert len(session.completed_stages) == 0
        
        session.advance_stage(stage2_id)
        assert session.current_stage_id == stage2_id
        assert stage1_id in session.completed_stages


class TestStage:
    """Tests for Stage entity."""
    
    def test_create_stage(self):
        """Test creating a stage."""
        stage = Stage(
            session_id=uuid4(),
            name="Requirement Analysis",
            stage_type=StageType.REQUIREMENT_ANALYSIS,
            agent_name="pm_agent",
        )
        
        assert stage.name == "Requirement Analysis"
        assert stage.stage_type == StageType.REQUIREMENT_ANALYSIS
        assert stage.status == StageStatus.PENDING
        assert stage.agent_name == "pm_agent"
    
    def test_stage_lifecycle(self):
        """Test stage status transitions."""
        stage = Stage(
            session_id=uuid4(),
            name="Test Stage",
            stage_type=StageType.CODING,
            agent_name="coder_agent",
        )
        
        # Start
        stage.start()
        assert stage.status == StageStatus.RUNNING
        assert stage.started_at is not None
        
        # Complete
        stage.complete()
        assert stage.status == StageStatus.COMPLETED
        assert stage.completed_at is not None
        assert stage.is_terminal() is True
    
    def test_stage_retry(self):
        """Test stage retry logic."""
        stage = Stage(
            session_id=uuid4(),
            name="Test Stage",
            stage_type=StageType.CODING,
            agent_name="coder_agent",
            max_retries=3,
        )
        
        # Fail first time
        stage.fail("Error occurred")
        assert stage.status == StageStatus.FAILED
        assert stage.can_retry() is True
        
        # Retry
        stage.increment_retry()
        assert stage.retry_count == 1
        
        # Exhaust retries
        stage.retry_count = 3
        assert stage.can_retry() is False


class TestArtifact:
    """Tests for Artifact entity."""
    
    def test_create_artifact(self):
        """Test creating an artifact."""
        artifact = Artifact(
            session_id=uuid4(),
            name="design.md",
            artifact_type=ArtifactType.SYSTEM_DESIGN,
            content="# System Design\n...",
        )
        
        assert artifact.name == "design.md"
        assert artifact.artifact_type == ArtifactType.SYSTEM_DESIGN
        assert artifact.content == "# System Design\n..."
    
    def test_artifact_summary(self):
        """Test artifact summary generation."""
        artifact = Artifact(
            session_id=uuid4(),
            name="test.py",
            artifact_type=ArtifactType.SOURCE_CODE,
            content="def hello():\n    return 'world'",
        )
        
        summary = artifact.get_summary(max_length=20)
        assert len(summary) <= 23  # 20 + "..."
    
    def test_artifact_type_checks(self):
        """Test artifact type checks."""
        code = Artifact(
            session_id=uuid4(),
            name="main.py",
            artifact_type=ArtifactType.SOURCE_CODE,
            content="print('hello')",
        )
        
        doc = Artifact(
            session_id=uuid4(),
            name="README.md",
            artifact_type=ArtifactType.README,
            content="# Project",
        )
        
        assert code.is_code() is True
        assert code.is_document() is False
        assert doc.is_code() is False
        assert doc.is_document() is True


class TestReview:
    """Tests for Review entity."""
    
    def test_create_review(self):
        """Test creating a review."""
        review = Review(
            session_id=uuid4(),
            stage_id=uuid4(),
            review_type=ReviewType.CODE_REVIEW,
            reviewer="reviewer_agent",
        )
        
        assert review.review_type == ReviewType.CODE_REVIEW
        assert review.reviewer == "reviewer_agent"
        assert review.status == ReviewStatus.PENDING
    
    def test_review_outcomes(self):
        """Test review outcome transitions."""
        review = Review(
            session_id=uuid4(),
            stage_id=uuid4(),
            review_type=ReviewType.CODE_REVIEW,
            reviewer="reviewer_agent",
        )
        
        # Start review
        review.start()
        assert review.status == ReviewStatus.IN_PROGRESS
        
        # Approve
        review.approve("Good code!")
        assert review.status == ReviewStatus.APPROVED
        assert review.is_approved() is True
        assert review.has_blocking_issues() is False
    
    def test_review_with_issues(self):
        """Test review with blocking issues."""
        review = Review(
            session_id=uuid4(),
            stage_id=uuid4(),
            review_type=ReviewType.CODE_REVIEW,
            reviewer="reviewer_agent",
        )
        
        # Add critical issue
        review.add_comment(
            message="Security vulnerability found",
            severity="critical",
            file_path="src/auth.py",
            line_number=42,
        )
        
        assert review.critical_issues == 1
        assert review.has_blocking_issues() is True
        
        # Request changes
        review.request_changes("Please fix security issue")
        assert review.status == ReviewStatus.CHANGES_REQUESTED
