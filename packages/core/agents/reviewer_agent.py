import os
"""Code Reviewer Agent."""

from typing import Any

from core.agents.base import BaseAgent, AgentConfig
from core.prompts.agent_prompts import CODE_REVIEW_PROMPT
from core.schemas.agent_outputs import CodeReviewOutput


class ReviewerAgent(BaseAgent):
    """Code Reviewer Agent.
    
    Reviews code for:
    - Correctness and functionality
    - Security vulnerabilities
    - Performance issues
    - Maintainability
    - Adherence to best practices
    """
    
    def __init__(self, config: AgentConfig | None = None):
        if config is None:
            config = AgentConfig(
                name="reviewer_agent",
                description="Code Reviewer - Quality Assurance",
                model_name=os.getenv("AGENT_MODEL", "MiniMax-M2.5"),
                temperature=0.1,
            )
        super().__init__(config)
    
    def get_system_prompt(self) -> str:
        """Get system prompt for Reviewer agent."""
        return CODE_REVIEW_PROMPT
    
    async def execute(self, context: dict[str, Any]) -> CodeReviewOutput:
        """Execute code review.
        
        Args:
            context: Must contain 'code' with files to review
            
        Returns:
            Structured code review output
        """
        code = context.get("code")
        if not code:
            raise ValueError("Context must contain 'code'")
        
        # Build user prompt
        user_prompt = self._build_prompt(context)
        
        # Call LLM
        result = await self._call_llm(
            system_prompt=self.get_system_prompt(),
            user_prompt=user_prompt,
            output_schema=CodeReviewOutput,
        )
        
        return result
    
    def _build_prompt(self, context: dict[str, Any]) -> str:
        """Build user prompt from context."""
        lines = ["# Code Review Task\n"]
        
        # Code to review
        code = context.get("code", {})
        files = code.get("files", [])
        
        lines.append(f"## Files to Review ({len(files)} files)\n")
        
        for file in files:
            path = file.get("path", "unnamed")
            language = file.get("language", "unknown")
            content = file.get("content", "")
            desc = file.get("description", "")
            
            lines.append(f"### File: {path}")
            lines.append(f"**Language**: {language}")
            if desc:
                lines.append(f"**Description**: {desc}")
            lines.append("\n```" + language)
            # Truncate very long files
            if len(content) > 5000:
                lines.append(content[:2500])
                lines.append(f"\n... [{len(content) - 5000} characters truncated] ...\n")
                lines.append(content[-2500:])
            else:
                lines.append(content)
            lines.append("```\n")
        
        # Requirements context
        if context.get("requirements"):
            req = context["requirements"]
            lines.append("## Requirements Context")
            lines.append(req.get("summary", ""))
        
        # Design context
        if context.get("design"):
            design = context["design"]
            lines.append("\n## Design Context")
            lines.append(f"Architecture: {design.get('architecture_style', 'Not specified')}")
        
        # Review focus
        if context.get("focus_areas"):
            lines.append("\n## Focus Areas")
            for area in context["focus_areas"]:
                lines.append(f"- {area}")
        
        return "\n".join(lines)
