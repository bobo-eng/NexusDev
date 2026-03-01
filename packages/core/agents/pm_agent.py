"""Product Manager Agent for requirement analysis."""

from typing import Any

from core.agents.base import BaseAgent, AgentConfig
from core.prompts.agent_prompts import REQUIREMENT_ANALYSIS_PROMPT
from core.schemas.agent_outputs import RequirementAnalysisOutput


class PMAgent(BaseAgent):
    """Product Manager Agent.
    
    Analyzes user requirements and produces:
    - User stories with acceptance criteria
    - Functional and non-functional requirements
    - Complexity estimates
    - Technology recommendations
    """
    
    def __init__(self, config: AgentConfig | None = None):
        if config is None:
            config = AgentConfig(
                name="pm_agent",
                description="Product Manager - Requirement Analysis",
                model_name="gpt-4",
                temperature=0.3,
            )
        super().__init__(config)
    
    def get_system_prompt(self) -> str:
        """Get system prompt for PM agent."""
        return REQUIREMENT_ANALYSIS_PROMPT
    
    async def execute(self, context: dict[str, Any]) -> RequirementAnalysisOutput:
        """Execute requirement analysis.
        
        Args:
            context: Must contain 'requirement' key with user requirement
            
        Returns:
            Structured requirement analysis output
        """
        requirement = context.get("requirement", "")
        if not requirement:
            raise ValueError("Context must contain 'requirement'")
        
        # Build user prompt
        user_prompt = self._build_prompt(context)
        
        # Call LLM
        result, metadata = await self._call_llm(
            system_prompt=self.get_system_prompt(),
            user_prompt=user_prompt,
            output_schema=RequirementAnalysisOutput,
        )

        self._execution_metadata = metadata
        return result
    
    def _build_prompt(self, context: dict[str, Any]) -> str:
        """Build user prompt from context."""
        lines = ["# Requirement Analysis Task\n"]
        
        # Main requirement
        lines.append("## User Requirement")
        lines.append(context.get("requirement", ""))
        
        # Additional context
        if context.get("project_name"):
            lines.append(f"\n## Project Name")
            lines.append(context["project_name"])
        
        if context.get("existing_code"):
            lines.append("\n## Existing Code Context")
            lines.append(context["existing_code"])
        
        if context.get("constraints"):
            lines.append("\n## Known Constraints")
            for constraint in context["constraints"]:
                lines.append(f"- {constraint}")
        
        if context.get("preferences"):
            lines.append("\n## Technology Preferences")
            for pref in context["preferences"]:
                lines.append(f"- {pref}")
        
        return "\n".join(lines)
