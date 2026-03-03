"""LangGraph workflow definition for multi-agent development.

This module defines the complete development workflow as a state graph:
requirement -> design -> [HITL] -> coding -> review -> testing
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from core.domain.session import SessionStatus
from core.domain.stage import StageStatus


class DevelopmentState(BaseModel):
    """State object for the development workflow.
    
    This is passed between nodes in the graph and contains
    all context needed for execution, including memory.
    """
    
    # Session identification
    session_id: UUID
    project_id: str | None = None
    
    # Current execution state
    current_stage: str = ""
    stage_status: StageStatus = StageStatus.PENDING
    
    # Session status
    session_status: SessionStatus = SessionStatus.CREATED
    
    # Stage outputs (accumulated)
    requirements: dict[str, Any] = Field(default_factory=dict)
    design: dict[str, Any] = Field(default_factory=dict)
    code: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] = Field(default_factory=dict)
    tests: dict[str, Any] = Field(default_factory=dict)
    
    # Artifact IDs
    artifact_ids: list[UUID] = Field(default_factory=list)
    
    # HITL
    approval_record_id: UUID | None = None
    approval_decision: str | None = None
    approval_message: str = ""
    
    # Retry tracking
    retry_count: dict[str, int] = Field(default_factory=dict)
    
    # Error handling
    error_message: str = ""
    should_stop: bool = False
    
    # Messages for logging
    messages: Annotated[list, add_messages] = Field(default_factory=list)
    
    # ============ Memory Integration ============
    
    # Working memory - current session context
    working_memory: list[dict[str, Any]] = Field(default_factory=list)
    
    # Episodic memory - event history references
    episodic_memory_refs: list[UUID] = Field(default_factory=list)
    
    # Semantic memory - relevant patterns/knowledge
    semantic_memory_refs: list[UUID] = Field(default_factory=list)
    
    # Memory context for current agent
    agent_context: dict[str, Any] = Field(default_factory=dict)
    
    # Shared context between agents (explicit passing)
    shared_context: dict[str, Any] = Field(default_factory=dict)
    
    def increment_retry(self, stage: str) -> "DevelopmentState":
        """Increment retry count for a stage."""
        self.retry_count[stage] = self.retry_count.get(stage, 0) + 1
        return self
    
    def get_retry_count(self, stage: str) -> int:
        """Get retry count for a stage."""
        return self.retry_count.get(stage, 0)
    
    def add_artifact(self, artifact_id: UUID) -> "DevelopmentState":
        """Add an artifact ID."""
        if artifact_id not in self.artifact_ids:
            self.artifact_ids.append(artifact_id)
        return self
    
    def mark_error(self, message: str) -> "DevelopmentState":
        """Mark state with error."""
        self.error_message = message
        self.session_status = SessionStatus.FAILED
        self.should_stop = True
        return self
    
    # ============ Memory Methods ============
    
    def add_to_working_memory(
        self,
        content: str,
        agent_name: str,
        importance: float = 0.5,
    ) -> "DevelopmentState":
        """Add entry to working memory."""
        from uuid import uuid4
        entry = {
            "id": str(uuid4()),
            "content": content,
            "agent": agent_name,
            "importance": importance,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.working_memory.append(entry)
        return self
    
    def get_working_memory(
        self,
        agent_name: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Get working memory entries."""
        entries = self.working_memory
        if agent_name:
            entries = [e for e in entries if e.get("agent") == agent_name]
        return entries[-limit:]
    
    def add_shared_context(self, key: str, value: Any) -> "DevelopmentState":
        """Add to shared context (explicit agent communication)."""
        self.shared_context[key] = value
        return self
    
    def get_shared_context(self, key: str) -> Any:
        """Get from shared context."""
        return self.shared_context.get(key)
    
    def build_agent_prompt_context(self, agent_name: str) -> str:
        """Build prompt context for an agent including memory."""
        context_parts = []
        
        # Add working memory
        working = self.get_working_memory(agent_name=agent_name, limit=5)
        if working:
            context_parts.append("## Previous Work")
            for entry in working:
                context_parts.append(f"- {entry['content'][:200]}")
        
        # Add shared context
        if self.shared_context:
            context_parts.append("## Shared Context")
            for key, value in self.shared_context.items():
                if isinstance(value, str):
                    context_parts.append(f"- {key}: {value[:200]}")
        
        return "\n".join(context_parts)


def create_development_graph(sop_engine: "SOPEngine") -> StateGraph:
    """Create the development workflow graph.
    
    Args:
        sop_engine: SOP engine for stage definitions
        
    Returns:
        Compiled StateGraph
    """
    from core.workflow.nodes import (
        requirement_analysis_node,
        system_design_node,
        coding_node,
        code_review_node,
        testing_node,
        human_approval_node,
        error_handler_node,
        wait_for_approval_node,
    )
    from core.workflow.router import route_stage, RouteDecision
    
    # Create graph
    workflow = StateGraph(DevelopmentState)
    
    # Add nodes
    workflow.add_node("requirement_analysis", requirement_analysis_node)
    workflow.add_node("system_design", system_design_node)
    workflow.add_node("human_approval", human_approval_node)
    workflow.add_node("wait_for_approval", wait_for_approval_node)
    workflow.add_node("coding", coding_node)
    workflow.add_node("code_review", code_review_node)
    workflow.add_node("testing", testing_node)
    workflow.add_node("error_handler", error_handler_node)
    
    # Define edges with routing
    
    # Start -> requirement_analysis
    workflow.set_entry_point("requirement_analysis")
    
    # requirement_analysis -> system_design (or error)
    workflow.add_conditional_edges(
        "requirement_analysis",
        lambda state: route_stage(state, "requirement_analysis", sop_engine),
        {
            RouteDecision.PROCEED: "system_design",
            RouteDecision.RETRY: "requirement_analysis",
            RouteDecision.FAIL: "error_handler",
        },
    )
    
    # system_design -> human_approval (or error)
    workflow.add_conditional_edges(
        "system_design",
        lambda state: route_stage(state, "system_design", sop_engine),
        {
            RouteDecision.PROCEED: "human_approval",
            RouteDecision.RETRY: "system_design",
            RouteDecision.FAIL: "error_handler",
        },
    )
    
    # human_approval -> coding / wait_for_approval / back to design / error
    workflow.add_conditional_edges(
        "human_approval",
        lambda state: route_stage(state, "human_approval", sop_engine),
        {
            RouteDecision.PROCEED: "coding",
            RouteDecision.RETRY: "system_design",  # Reject -> redesign
            RouteDecision.WAIT: "wait_for_approval",  # Still waiting
            RouteDecision.FAIL: "error_handler",
        },
    )
    
    # wait_for_approval loops back to human_approval (for recheck)
    workflow.add_conditional_edges(
        "wait_for_approval",
        lambda state: route_stage(state, "human_approval", sop_engine),
        {
            RouteDecision.PROCEED: "coding",
            RouteDecision.RETRY: "system_design",
            RouteDecision.WAIT: "wait_for_approval",
            RouteDecision.FAIL: "error_handler",
        },
    )
    
    # coding -> code_review (or error)
    workflow.add_conditional_edges(
        "coding",
        lambda state: route_stage(state, "coding", sop_engine),
        {
            RouteDecision.PROCEED: "code_review",
            RouteDecision.RETRY: "coding",
            RouteDecision.FAIL: "error_handler",
        },
    )
    
    # code_review -> testing (or back to coding for fixes)
    workflow.add_conditional_edges(
        "code_review",
        lambda state: route_stage(state, "code_review", sop_engine),
        {
            RouteDecision.PROCEED: "testing",
            RouteDecision.RETRY: "coding",  # Request changes
            RouteDecision.FAIL: "error_handler",
        },
    )
    
    # testing -> END (or back to coding for fixes)
    workflow.add_conditional_edges(
        "testing",
        lambda state: route_stage(state, "testing", sop_engine),
        {
            RouteDecision.PROCEED: END,
            RouteDecision.RETRY: "coding",  # Failed tests
            RouteDecision.FAIL: "error_handler",
        },
    )
    
    # error_handler -> END
    workflow.add_edge("error_handler", END)
    
    return workflow.compile()


def create_mvp_graph() -> StateGraph:
    """Create MVP development graph with default SOP.
    
    Returns:
        Compiled StateGraph
    """
    from core.sop.sop_engine import SOPEngine, SOPConfig
    
    sop_engine = SOPEngine(SOPEngine(SOPConfig()).create_default_mvp_sop())
    return create_development_graph(sop_engine)
