"""Router for workflow stage transitions.

Determines the next action based on current state and SOP rules.
"""

from enum import Enum
from typing import TYPE_CHECKING

from core.domain.stage import StageStatus

if TYPE_CHECKING:
    from core.sop.sop_engine import SOPEngine
    from core.workflow.graph import DevelopmentState


class RouteDecision(str, Enum):
    """Possible routing decisions."""
    
    PROCEED = "proceed"      # Continue to next stage
    RETRY = "retry"          # Retry current stage
    FAIL = "fail"            # Go to error handler
    WAIT = "wait"            # Wait for external input


def route_stage(
    state: "DevelopmentState",
    stage_name: str,
    sop_engine: "SOPEngine",
) -> RouteDecision:
    """Determine routing decision for a stage.
    
    Args:
        state: Current workflow state
        stage_name: Name of the stage that just completed
        sop_engine: SOP engine for rules
        
    Returns:
        Routing decision
    """
    stage_status = state.stage_status
    retry_count = state.get_retry_count(stage_name)
    
    # Get stage definition
    stage_def = sop_engine.config.get_stage(stage_name)
    max_retries = stage_def.max_retries if stage_def else 3
    
    # Handle different statuses
    if stage_status == StageStatus.COMPLETED:
        return RouteDecision.PROCEED
    
    if stage_status == StageStatus.APPROVED:
        return RouteDecision.PROCEED
    
    if stage_status == StageStatus.REJECTED:
        # Check if we should retry or fail
        if stage_def and stage_def.on_reject:
            return RouteDecision.RETRY
        return RouteDecision.FAIL
    
    if stage_status == StageStatus.WAITING_APPROVAL:
        # Check if approval decision is made
        if state.approval_decision == "approved":
            return RouteDecision.PROCEED
        elif state.approval_decision == "rejected":
            return RouteDecision.RETRY
        else:
            return RouteDecision.WAIT
    
    if stage_status == StageStatus.FAILED:
        # Check retry logic
        if retry_count < max_retries:
            state.increment_retry(stage_name)
            return RouteDecision.RETRY
        return RouteDecision.FAIL
    
    # Default: proceed
    return RouteDecision.PROCEED


def should_require_approval(
    state: "DevelopmentState",
    stage_name: str,
    sop_engine: "SOPEngine",
) -> bool:
    """Check if stage requires human approval.
    
    Args:
        state: Current workflow state
        stage_name: Stage name
        sop_engine: SOP engine
        
    Returns:
        True if approval required
    """
    return sop_engine.requires_approval(stage_name)


def get_next_stage_name(
    state: "DevelopmentState",
    current_stage: str,
    sop_engine: "SOPEngine",
) -> str | None:
    """Get the next stage name based on current state.
    
    Args:
        state: Current workflow state
        current_stage: Current stage name
        sop_engine: SOP engine
        
    Returns:
        Next stage name or None if workflow complete
    """
    stage_def = sop_engine.config.get_stage(current_stage)
    
    if not stage_def:
        return None
    
    # Determine next stage based on status
    if state.stage_status == StageStatus.COMPLETED:
        return stage_def.on_success
    
    if state.stage_status == StageStatus.APPROVED:
        return stage_def.on_success
    
    if state.stage_status == StageStatus.REJECTED:
        return stage_def.on_reject or stage_def.on_failure
    
    if state.stage_status == StageStatus.FAILED:
        return stage_def.on_failure
    
    return None
