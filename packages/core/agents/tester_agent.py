"""QA Engineer Agent for testing."""

from typing import Any

from core.agents.base import BaseAgent, AgentConfig
from core.prompts.agent_prompts import TESTING_PROMPT
from core.schemas.agent_outputs import TestingOutput


class TesterAgent(BaseAgent):
    """QA Engineer Agent.
    
    Creates and executes tests:
    - Test plan and test cases
    - Unit, integration, and e2e tests
    - Coverage analysis
    - Bug identification
    """
    
    def __init__(self, config: AgentConfig | None = None):
        if config is None:
            config = AgentConfig(
                name="tester_agent",
                description="QA Engineer - Testing",
                model_name="gpt-4",
                temperature=0.2,
            )
        super().__init__(config)
    
    def get_system_prompt(self) -> str:
        """Get system prompt for Tester agent."""
        return TESTING_PROMPT
    
    async def execute(self, context: dict[str, Any]) -> TestingOutput:
        """Execute testing.
        
        Args:
            context: Must contain 'code' and optionally 'requirements'
            
        Returns:
            Structured testing output
        """
        code = context.get("code")
        if not code:
            raise ValueError("Context must contain 'code'")
        
        # Build user prompt
        user_prompt = self._build_prompt(context)
        
        # Call LLM
        result, metadata = await self._call_llm(
            system_prompt=self.get_system_prompt(),
            user_prompt=user_prompt,
            output_schema=TestingOutput,
        )

        self._execution_metadata = metadata
        return result
    
    def _build_prompt(self, context: dict[str, Any]) -> str:
        """Build user prompt from context."""
        lines = ["# Testing Task\n"]
        
        # Code to test
        code = context.get("code", {})
        files = code.get("files", [])
        
        lines.append(f"## Code to Test ({len(files)} files)\n")
        
        for file in files:
            path = file.get("path", "unnamed")
            language = file.get("language", "unknown")
            content = file.get("content", "")
            
            lines.append(f"### File: {path}")
            lines.append(f"**Language**: {language}")
            lines.append("\n```" + language)
            # Truncate for context window
            if len(content) > 3000:
                lines.append(content[:1500])
                lines.append(f"\n... [{len(content) - 3000} characters truncated] ...\n")
                lines.append(content[-1500:])
            else:
                lines.append(content)
            lines.append("```\n")
        
        # Entry points
        entry_points = code.get("entry_points", [])
        if entry_points:
            lines.append("## Entry Points")
            for ep in entry_points:
                lines.append(f"- {ep}")
        
        # Dependencies
        deps = code.get("dependencies", {})
        if deps:
            lines.append("\n## Dependencies")
            for key, values in deps.items():
                if values:
                    lines.append(f"- **{key}**: {', '.join(str(v) for v in values[:5])}")
        
        # Requirements context
        if context.get("requirements"):
            req = context["requirements"]
            lines.append("\n## Requirements to Cover")
            for story in req.get("user_stories", []):
                title = story.get("title", "")
                lines.append(f"- {title}")
        
        # Design context
        if context.get("design"):
            design = context["design"]
            lines.append("\n## API Endpoints to Test")
            for api in design.get("api_specs", [])[:5]:
                method = api.get("method", "GET")
                path = api.get("path", "/")
                lines.append(f"- `{method} {path}`")
        
        # Testing requirements
        if context.get("coverage_target"):
            lines.append(f"\n## Coverage Target: {context['coverage_target']}%")
        
        if context.get("test_types"):
            lines.append("\n## Required Test Types")
            for tt in context["test_types"]:
                lines.append(f"- {tt}")
        
        return "\n".join(lines)
