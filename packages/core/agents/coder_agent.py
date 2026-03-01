"""Coder Agent for implementation."""

from typing import Any

from core.agents.base import BaseAgent, AgentConfig
from core.prompts.agent_prompts import CODING_PROMPT
from core.schemas.agent_outputs import CodingOutput


class CoderAgent(BaseAgent):
    """Software Engineer Agent.
    
    Implements code based on system design:
    - Writes complete, runnable code files
    - Follows best practices and conventions
    - Includes error handling and logging
    - Produces testable code
    """
    
    def __init__(self, config: AgentConfig | None = None):
        if config is None:
            config = AgentConfig(
                name="coder_agent",
                description="Software Engineer - Code Implementation",
                model_name="gpt-4",
                temperature=0.1,
            )
        super().__init__(config)
    
    def get_system_prompt(self) -> str:
        """Get system prompt for Coder agent."""
        return CODING_PROMPT
    
    async def execute(self, context: dict[str, Any]) -> CodingOutput:
        """Execute code implementation.
        
        Args:
            context: Must contain 'design' from Architect agent output
            
        Returns:
            Structured coding output with files
        """
        design = context.get("design")
        if not design:
            raise ValueError("Context must contain 'design'")
        
        # Build user prompt
        user_prompt = self._build_prompt(context)
        
        # Call LLM
        result, metadata = await self._call_llm(
            system_prompt=self.get_system_prompt(),
            user_prompt=user_prompt,
            output_schema=CodingOutput,
        )

        self._execution_metadata = metadata
        return result
    
    def _build_prompt(self, context: dict[str, Any]) -> str:
        """Build user prompt from context."""
        lines = ["# Code Implementation Task\n"]
        
        # Design
        design = context.get("design", {})
        lines.append("## System Overview")
        lines.append(design.get("overview", "No overview provided"))
        
        lines.append("\n## Architecture Style")
        lines.append(design.get("architecture_style", "Not specified"))
        
        lines.append("\n## Components")
        for comp in design.get("components", []):
            name = comp.get("name", "Unnamed")
            resp = comp.get("responsibility", "")
            lines.append(f"- **{name}**: {resp}")
        
        lines.append("\n## API Specifications")
        for api in design.get("api_specs", []):
            method = api.get("method", "GET")
            path = api.get("path", "/")
            desc = api.get("description", "")
            lines.append(f"- `{method} {path}`: {desc}")
        
        lines.append("\n## Database Schema")
        for table in design.get("database_schema", []):
            name = table.get("name", "unnamed")
            columns = [c.get("name", "?") for c in table.get("columns", [])]
            lines.append(f"- **{name}**: {', '.join(columns)}")
        
        lines.append("\n## Security Considerations")
        for sec in design.get("security_considerations", []):
            lines.append(f"- {sec}")
        
        # Requirements reference
        if context.get("requirements"):
            req = context["requirements"]
            lines.append("\n## Key Requirements to Implement")
            for story in req.get("user_stories", [])[:3]:  # Top 3 stories
                lines.append(f"- {story.get('title', '')}")
        
        # Technology constraints
        if context.get("tech_stack"):
            lines.append("\n## Required Technology Stack")
            for tech in context["tech_stack"]:
                lines.append(f"- {tech}")
        
        return "\n".join(lines)
