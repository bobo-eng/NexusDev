"""LangGraph node implementations for development workflow.

Each node represents a stage in the development process.
Nodes are responsible for:
1. Executing the agent
2. Storing outputs
3. Updating state
4. Handling errors
"""

import logging

from core.agents.architect_agent import ArchitectAgent
from core.agents.coder_agent import CoderAgent
from core.agents.pm_agent import PMAgent
from core.agents.reviewer_agent import ReviewerAgent
from core.agents.tester_agent import TesterAgent
from core.domain.session import SessionStatus
from core.domain.stage import StageStatus
from core.workflow.graph import DevelopmentState

logger = logging.getLogger(__name__)


async def requirement_analysis_node(state: DevelopmentState) -> DevelopmentState:
    """Execute requirement analysis stage.

    Args:
        state: Current workflow state

    Returns:
        Updated state with requirements output
    """
    logger.info(f"[Session {state.session_id}] Starting requirement analysis")

    state.current_stage = "requirement_analysis"
    state.stage_status = StageStatus.RUNNING
    state.session_status = SessionStatus.RUNNING

    try:
        # Create and execute PM agent
        agent = PMAgent()

        context = {
            "requirement": state.requirements.get("raw_requirement", ""),
            "project_name": state.requirements.get("project_name", ""),
        }

        result = await agent.execute(context)

        # Store output
        state.requirements = result.model_dump()
        state.stage_status = StageStatus.COMPLETED

        logger.info(f"[Session {state.session_id}] Requirement analysis completed")

    except Exception as e:
        logger.error(f"[Session {state.session_id}] Requirement analysis failed: {e}")
        state.stage_status = StageStatus.FAILED
        state.error_message = str(e)

    return state


async def system_design_node(state: DevelopmentState) -> DevelopmentState:
    """Execute system design stage.

    Args:
        state: Current workflow state

    Returns:
        Updated state with design output
    """
    logger.info(f"[Session {state.session_id}] Starting system design")

    state.current_stage = "system_design"
    state.stage_status = StageStatus.RUNNING

    try:
        # Create and execute Architect agent
        agent = ArchitectAgent()

        context = {
            "requirements": state.requirements,
        }

        result = await agent.execute(context)

        # Store output
        state.design = result.model_dump()
        state.stage_status = StageStatus.WAITING_APPROVAL  # HITL checkpoint
        state.session_status = SessionStatus.WAITING_APPROVAL

        logger.info(f"[Session {state.session_id}] System design completed, awaiting approval")

    except Exception as e:
        logger.error(f"[Session {state.session_id}] System design failed: {e}")
        state.stage_status = StageStatus.FAILED
        state.error_message = str(e)

    return state


async def human_approval_node(state: DevelopmentState) -> DevelopmentState:
    """Handle human approval for design.

    This node checks the approval decision and routes accordingly.

    Args:
        state: Current workflow state

    Returns:
        Updated state
    """
    logger.info(f"[Session {state.session_id}] Processing human approval")

    state.current_stage = "human_approval"

    # Check approval decision
    decision = state.approval_decision

    if decision == "approved":
        state.stage_status = StageStatus.APPROVED
        state.session_status = SessionStatus.APPROVED
        logger.info(f"[Session {state.session_id}] Design approved")

    elif decision == "rejected":
        state.stage_status = StageStatus.REJECTED
        state.session_status = SessionStatus.REJECTED
        logger.info(f"[Session {state.session_id}] Design rejected")

    else:
        # Still waiting for approval
        state.stage_status = StageStatus.WAITING_APPROVAL
        logger.info(f"[Session {state.session_id}] Waiting for approval")

    return state


async def coding_node(state: DevelopmentState) -> DevelopmentState:
    """Execute coding stage.

    Args:
        state: Current workflow state

    Returns:
        Updated state with code output
    """
    logger.info(f"[Session {state.session_id}] Starting coding")

    state.current_stage = "coding"
    state.stage_status = StageStatus.RUNNING
    state.session_status = SessionStatus.RUNNING

    try:
        # Create and execute Coder agent
        agent = CoderAgent()

        context = {
            "design": state.design,
            "requirements": state.requirements,
        }

        result = await agent.execute(context)

        # Store output
        state.code = result.model_dump()
        state.stage_status = StageStatus.COMPLETED

        logger.info(f"[Session {state.session_id}] Coding completed")

    except Exception as e:
        logger.error(f"[Session {state.session_id}] Coding failed: {e}")
        state.stage_status = StageStatus.FAILED
        state.error_message = str(e)

    return state


async def code_review_node(state: DevelopmentState) -> DevelopmentState:
    """Execute code review stage.

    Args:
        state: Current workflow state

    Returns:
        Updated state with review output
    """
    logger.info(f"[Session {state.session_id}] Starting code review")

    state.current_stage = "code_review"
    state.stage_status = StageStatus.RUNNING

    try:
        # Create and execute Reviewer agent
        agent = ReviewerAgent()

        context = {
            "code": state.code,
            "requirements": state.requirements,
            "design": state.design,
        }

        result = await agent.execute(context)

        # Store output
        state.review = result.model_dump()

        # Check review recommendation
        recommendation = result.recommendation.upper()
        if recommendation == "REQUEST_CHANGES":
            state.stage_status = StageStatus.FAILED  # Will trigger retry
            logger.info(f"[Session {state.session_id}] Code review requested changes")
        else:
            state.stage_status = StageStatus.COMPLETED
            logger.info(f"[Session {state.session_id}] Code review completed")

    except Exception as e:
        logger.error(f"[Session {state.session_id}] Code review failed: {e}")
        state.stage_status = StageStatus.FAILED
        state.error_message = str(e)

    return state


async def testing_node(state: DevelopmentState) -> DevelopmentState:
    """Execute testing stage.

    Args:
        state: Current workflow state

    Returns:
        Updated state with test output
    """
    logger.info(f"[Session {state.session_id}] Starting testing")

    state.current_stage = "testing"
    state.stage_status = StageStatus.RUNNING

    try:
        # Create and execute Tester agent
        agent = TesterAgent()

        context = {
            "code": state.code,
            "requirements": state.requirements,
            "design": state.design,
        }

        result = await agent.execute(context)

        # Store output
        state.tests = result.model_dump()

        # Check test recommendation
        recommendation = result.recommendation.upper()
        if recommendation == "FAIL":
            state.stage_status = StageStatus.FAILED
            logger.info(f"[Session {state.session_id}] Testing failed")
        else:
            state.stage_status = StageStatus.COMPLETED
            state.session_status = SessionStatus.COMPLETED
            logger.info(f"[Session {state.session_id}] Testing completed")

    except Exception as e:
        logger.error(f"[Session {state.session_id}] Testing failed: {e}")
        state.stage_status = StageStatus.FAILED
        state.error_message = str(e)

    return state


async def error_handler_node(state: DevelopmentState) -> DevelopmentState:
    """Handle errors in the workflow.

    Args:
        state: Current workflow state

    Returns:
        Updated state with error handling
    """
    logger.error(f"[Session {state.session_id}] Error handler invoked: {state.error_message}")

    state.session_status = SessionStatus.FAILED
    state.should_stop = True

    # Could add error notification, cleanup, etc. here

    return state


async def wait_for_approval_node(state: DevelopmentState) -> DevelopmentState:
    """Wait for human approval.

    This node is a placeholder that keeps the workflow in a waiting state
    until human approval is received. In a real implementation, this would
    poll the approval status or be triggered by an external event.

    Args:
        state: Current workflow state

    Returns:
        Updated state (still waiting)
    """
    logger.info(f"[Session {state.session_id}] Waiting for human approval")

    state.current_stage = "wait_for_approval"
    state.stage_status = StageStatus.WAITING_APPROVAL

    # In a real implementation, this would:
    # 1. Check approval status from database
    # 2. Update state.approval_decision if approved/rejected
    # 3. Return appropriate status for routing

    # For now, we just keep waiting
    # The actual approval is handled by the API/CLI calling approve_stage

    return state
