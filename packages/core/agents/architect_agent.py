import os
"""System Architect Agent for design."""

from typing import Any

from core.agents.base import BaseAgent, AgentConfig
from core.prompts.agent_prompts import SYSTEM_DESIGN_PROMPT
from core.schemas.agent_outputs import SystemDesignOutput


class ArchitectAgent(BaseAgent):
    """System Architect Agent.
    
    Creates technical architecture based on requirements:
    - Component design
    - API specifications
    - Database schema
    - Security and scalability planning
    """
    
    def __init__(self, config: AgentConfig | None = None):
        if config is None:
            config = AgentConfig(
                name="architect_agent",
                description="System Architect - Technical Design",
                model_name=os.getenv("AGENT_MODEL", "MiniMax-M2.5"),
                temperature=0.2,
            )
        super().__init__(config)
    
    def get_system_prompt(self) -> str:
        """Get system prompt for Architect agent."""
        return SYSTEM_DESIGN_PROMPT
    
    async def execute(self, context: dict[str, Any]) -> SystemDesignOutput:
        """Execute system design.
        
        Args:
            context: Must contain 'requirements' from PM agent output
            
        Returns:
            Structured system design output
        """
        requirements = context.get("requirements")
        if not requirements:
            raise ValueError("Context must contain 'requirements'")
        
        # Build user prompt
        user_prompt = self._build_prompt(context)
        
        # Call LLM
        result = await self._call_llm(
            system_prompt=self.get_system_prompt(),
            user_prompt=user_prompt,
            output_schema=SystemDesignOutput,
        )
        
        return result
    
    def _build_prompt(self, context: dict[str, Any]) -> str:
        """Build user prompt from context."""
        lines = ["# System Design Task\n"]
        
        # Requirements
        req = context.get("requirements", {})
        lines.append("## Requirements Summary")
        lines.append(req.get("summary", "No summary provided"))
        
        lines.append("\n## User Stories")
        for story in req.get("user_stories", []):
            title = story.get("title", "Untitled")
            desc = story.get("description", "")
            lines.append(f"- **{title}**: {desc}")
        
        lines.append("\n## Functional Requirements")
        for fr in req.get("functional_requirements", []):
            lines.append(f"- {fr}")
        
        lines.append("\n## Non-Functional Requirements")
        for nfr in req.get("non_functional_requirements", []):
            lines.append(f"- {nfr}")
        
        lines.append("\n## Constraints")
        for constraint in req.get("constraints", []):
            lines.append(f"- {constraint}")
        
        lines.append("\n## Suggested Technologies")
        for tech in req.get("suggested_technologies", []):
            lines.append(f"- {tech}")
        
        # Additional context
        if context.get("existing_system"):
            lines.append("\n## Existing System Context")
            lines.append(context["existing_system"])
        
        if context.get("scalability_requirements"):
            lines.append("\n## Scalability Requirements")
            lines.append(context["scalability_requirements"])
        
        return "\n".join(lines)
