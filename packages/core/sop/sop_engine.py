"""MetaSOP Engine - Standard Operating Procedure engine.

Inspired by MetaGPT's SOP concept, this engine defines:
- Stage definitions and their properties
- Transition rules between stages
- Approval requirements
- Retry policies
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import yaml


class StageAction(str, Enum):
    """Actions that can be performed on a stage."""
    
    START = "start"
    COMPLETE = "complete"
    APPROVE = "approve"
    REJECT = "reject"
    RETRY = "retry"
    SKIP = "skip"
    FAIL = "fail"


@dataclass
class StageDefinition:
    """Definition of a workflow stage.
    
    Defines what an agent does, what it produces,
    and how it transitions to the next stage.
    """
    
    name: str
    stage_type: str
    description: str = ""
    agent_name: str = ""
    
    # Execution
    timeout_minutes: int = 30
    max_retries: int = 3
    
    # Approval
    requires_approval: bool = False
    approval_timeout_hours: int = 24
    approvers: list[str] = field(default_factory=list)
    
    # Artifacts
    expected_outputs: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    
    # Transitions
    on_success: str | None = None
    on_failure: str | None = None
    on_reject: str | None = None
    
    # Conditions
    skip_if: str | None = None  # Condition to skip this stage
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "stage_type": self.stage_type,
            "description": self.description,
            "agent_name": self.agent_name,
            "timeout_minutes": self.timeout_minutes,
            "max_retries": self.max_retries,
            "requires_approval": self.requires_approval,
            "approval_timeout_hours": self.approval_timeout_hours,
            "approvers": self.approvers,
            "expected_outputs": self.expected_outputs,
            "required_inputs": self.required_inputs,
            "on_success": self.on_success,
            "on_failure": self.on_failure,
            "on_reject": self.on_reject,
            "skip_if": self.skip_if,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageDefinition":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            stage_type=data["stage_type"],
            description=data.get("description", ""),
            agent_name=data.get("agent_name", ""),
            timeout_minutes=data.get("timeout_minutes", 30),
            max_retries=data.get("max_retries", 3),
            requires_approval=data.get("requires_approval", False),
            approval_timeout_hours=data.get("approval_timeout_hours", 24),
            approvers=data.get("approvers", []),
            expected_outputs=data.get("expected_outputs", []),
            required_inputs=data.get("required_inputs", []),
            on_success=data.get("on_success"),
            on_failure=data.get("on_failure"),
            on_reject=data.get("on_reject"),
            skip_if=data.get("skip_if"),
        )


@dataclass
class SOPConfig:
    """SOP Configuration.
    
    Defines the complete workflow with all stages
    and global settings.
    """
    
    name: str = "default"
    description: str = ""
    version: str = "1.0.0"
    
    # Global settings
    default_timeout_minutes: int = 30
    default_max_retries: int = 3
    auto_approve: bool = False  # For testing
    
    # Stages in order
    stages: list[StageDefinition] = field(default_factory=list)
    
    # Global transitions
    allow_stage_skip: bool = False
    allow_rollback: bool = True
    
    def get_stage(self, name: str) -> StageDefinition | None:
        """Get stage definition by name."""
        for stage in self.stages:
            if stage.name == name:
                return stage
        return None
    
    def get_stage_index(self, name: str) -> int:
        """Get stage index by name."""
        for i, stage in enumerate(self.stages):
            if stage.name == name:
                return i
        return -1
    
    def get_next_stage(self, current_name: str) -> StageDefinition | None:
        """Get next stage in sequence."""
        idx = self.get_stage_index(current_name)
        if idx >= 0 and idx < len(self.stages) - 1:
            return self.stages[idx + 1]
        return None
    
    def get_first_stage(self) -> StageDefinition | None:
        """Get first stage."""
        return self.stages[0] if self.stages else None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "default_timeout_minutes": self.default_timeout_minutes,
            "default_max_retries": self.default_max_retries,
            "auto_approve": self.auto_approve,
            "allow_stage_skip": self.allow_stage_skip,
            "allow_rollback": self.allow_rollback,
            "stages": [s.to_dict() for s in self.stages],
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SOPConfig":
        """Create from dictionary."""
        return cls(
            name=data.get("name", "default"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            default_timeout_minutes=data.get("default_timeout_minutes", 30),
            default_max_retries=data.get("default_max_retries", 3),
            auto_approve=data.get("auto_approve", False),
            allow_stage_skip=data.get("allow_stage_skip", False),
            allow_rollback=data.get("allow_rollback", True),
            stages=[StageDefinition.from_dict(s) for s in data.get("stages", [])],
        )
    
    @classmethod
    def from_yaml(cls, path: str) -> "SOPConfig":
        """Load from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)
    
    def to_yaml(self, path: str) -> None:
        """Save to YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False)


class SOPEngine:
    """SOP Engine - manages workflow execution according to SOP rules.
    
    The engine:
    1. Validates stage transitions
    2. Enforces approval requirements
    3. Manages retry logic
    4. Tracks stage dependencies
    """
    
    def __init__(self, config: SOPConfig):
        self.config = config
    
    def can_start_stage(self, stage_name: str, completed_stages: list[str]) -> bool:
        """Check if a stage can be started.
        
        Args:
            stage_name: Name of stage to start
            completed_stages: List of completed stage names
            
        Returns:
            True if stage can be started
        """
        stage = self.config.get_stage(stage_name)
        if not stage:
            return False
        
        # Check required inputs
        for required in stage.required_inputs:
            if required not in completed_stages:
                return False
        
        return True
    
    def get_next_action(
        self,
        stage_name: str,
        stage_status: str,
        retry_count: int = 0,
    ) -> tuple[StageAction, str | None]:
        """Determine next action based on stage status.
        
        Args:
            stage_name: Current stage name
            stage_status: Current stage status
            retry_count: Number of retries attempted
            
        Returns:
            Tuple of (action, next_stage_name or None)
        """
        stage = self.config.get_stage(stage_name)
        if not stage:
            return StageAction.FAIL, None
        
        # Handle terminal states
        if stage_status == "completed":
            return StageAction.COMPLETE, stage.on_success
        
        if stage_status == "approved":
            return StageAction.APPROVE, stage.on_success
        
        if stage_status == "rejected":
            return StageAction.REJECT, stage.on_reject or stage.on_failure
        
        if stage_status == "failed":
            if retry_count < stage.max_retries:
                return StageAction.RETRY, None
            return StageAction.FAIL, stage.on_failure
        
        if stage_status == "waiting_approval":
            return StageAction.APPROVE, None  # Wait for human
        
        return StageAction.START, None
    
    def requires_approval(self, stage_name: str) -> bool:
        """Check if stage requires human approval."""
        stage = self.config.get_stage(stage_name)
        if not stage:
            return False
        
        # Global auto-approve override
        if self.config.auto_approve:
            return False
        
        return stage.requires_approval
    
    def get_agent_for_stage(self, stage_name: str) -> str:
        """Get agent name responsible for a stage."""
        stage = self.config.get_stage(stage_name)
        return stage.agent_name if stage else ""
    
    def validate_transition(
        self,
        from_stage: str,
        to_stage: str,
        from_status: str,
    ) -> bool:
        """Validate if a stage transition is allowed.
        
        Args:
            from_stage: Source stage name
            to_stage: Target stage name
            from_status: Source stage status
            
        Returns:
            True if transition is valid
        """
        # Can always transition to failure
        if to_stage == "_FAILURE_":
            return from_status in ["failed", "rejected"]
        
        # Must be completed or approved to proceed
        if from_status not in ["completed", "approved"]:
            return False
        
        # Check if to_stage is the expected next stage
        stage = self.config.get_stage(from_stage)
        if stage and stage.on_success == to_stage:
            return True
        
        # Check sequential order
        from_idx = self.config.get_stage_index(from_stage)
        to_idx = self.config.get_stage_index(to_stage)
        
        if from_idx >= 0 and to_idx == from_idx + 1:
            return True
        
        return False
    
    def get_stage_sequence(self) -> list[str]:
        """Get ordered list of stage names."""
        return [s.name for s in self.config.stages]
    
    def create_default_mvp_sop(self) -> SOPConfig:
        """Create default MVP SOP configuration."""
        stages = [
            StageDefinition(
                name="requirement_analysis",
                stage_type="REQUIREMENT_ANALYSIS",
                description="Analyze user requirements and produce PRD",
                agent_name="pm_agent",
                timeout_minutes=20,
                max_retries=2,
                requires_approval=False,
                expected_outputs=["prd", "user_stories"],
                on_success="system_design",
                on_failure="_FAILURE_",
            ),
            StageDefinition(
                name="system_design",
                stage_type="SYSTEM_DESIGN",
                description="Design system architecture and APIs",
                agent_name="architect_agent",
                timeout_minutes=30,
                max_retries=2,
                requires_approval=True,  # HITL checkpoint
                expected_outputs=["system_design", "api_spec", "database_schema"],
                required_inputs=["requirement_analysis"],
                on_success="coding",
                on_failure="_FAILURE_",
                on_reject="requirement_analysis",
            ),
            StageDefinition(
                name="coding",
                stage_type="CODING",
                description="Implement the system based on design",
                agent_name="coder_agent",
                timeout_minutes=45,
                max_retries=3,
                requires_approval=False,
                expected_outputs=["source_code", "configuration"],
                required_inputs=["system_design"],
                on_success="code_review",
                on_failure="_FAILURE_",
            ),
            StageDefinition(
                name="code_review",
                stage_type="CODE_REVIEW",
                description="Review code for quality and issues",
                agent_name="reviewer_agent",
                timeout_minutes=20,
                max_retries=2,
                requires_approval=False,
                expected_outputs=["code_review_report"],
                required_inputs=["coding"],
                on_success="testing",
                on_failure="coding",  # Loop back for fixes
            ),
            StageDefinition(
                name="testing",
                stage_type="TESTING",
                description="Create and run tests",
                agent_name="tester_agent",
                timeout_minutes=30,
                max_retries=2,
                requires_approval=False,
                expected_outputs=["test_cases", "test_results", "coverage_report"],
                required_inputs=["coding", "code_review"],
                on_success="_COMPLETE_",
                on_failure="coding",  # Loop back for fixes
            ),
        ]
        
        return SOPConfig(
            name="mvp_default",
            description="MVP workflow: requirement -> design -> [HITL] -> coding -> review -> testing",
            version="1.0.0",
            stages=stages,
            allow_rollback=True,
        )
