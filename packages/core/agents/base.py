"""Base agent class with common functionality."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from core.schemas.agent_outputs import (
    RequirementAnalysisOutput,
    SystemDesignOutput,
    CodingOutput,
    CodeReviewOutput,
    TestingOutput,
)

T = TypeVar("T", bound=BaseModel)


@dataclass
class AgentConfig:
    """Configuration for an agent."""
    
    name: str
    description: str = ""
    model_name: str = "gpt-4"
    temperature: float = 0.2
    max_retries: int = 3
    timeout_seconds: int = 120
    
    # Provider settings
    provider: str = "openai"  # openai, anthropic
    api_key: str | None = None
    base_url: str | None = None
    
    # Advanced settings
    context_window: int = 8000
    response_format: str = "json"
    
    # Prompt versioning
    prompt_version: str = "1.0.0"
    schema_version: str = "1.0.0"


@dataclass
class AgentExecutionMetadata:
    """Metadata for agent execution."""
    
    agent_name: str
    prompt_version: str
    schema_version: str
    model_name: str
    temperature: float
    execution_time_ms: float = 0.0
    retry_count: int = 0
    raw_output: str = ""
    parsed_output: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Base class for all agents.
    
    Provides common functionality:
    - LLM interaction with retry logic
    - Structured output parsing and validation
    - Error handling and recovery
    - Prompt versioning
    """
    
    # Class-level version info
    PROMPT_VERSION: str = "1.0.0"
    SCHEMA_VERSION: str = "1.0.0"
    
    def __init__(self, config: AgentConfig | None = None, llm: BaseChatModel | None = None):
        self.config = config or self._default_config()
        self._llm = llm
        self._output_parser = JsonOutputParser()
        self._execution_metadata: AgentExecutionMetadata | None = None
    
    def _default_config(self) -> AgentConfig:
        """Get default agent configuration."""
        return AgentConfig(
            name=self.__class__.__name__,
            prompt_version=self.PROMPT_VERSION,
            schema_version=self.SCHEMA_VERSION,
        )
    
    @property
    def name(self) -> str:
        """Agent name."""
        return self.config.name
    
    @property
    def llm(self) -> BaseChatModel:
        """Get or create LLM instance."""
        if self._llm is None:
            self._llm = self._create_llm()
        return self._llm
    
    def _create_llm(self) -> BaseChatModel:
        """Create LLM instance based on config.
        
        Uses JSON mode when available (OpenAI) for more reliable structured output.
        """
        from langchain_openai import ChatOpenAI
        from langchain_anthropic import ChatAnthropic
        
        if self.config.provider == "anthropic":
            return ChatAnthropic(
                model=self.config.model_name,
                temperature=self.config.temperature,
                timeout=self.config.timeout_seconds,
                api_key=self.config.api_key,
            )
        else:
            # OpenAI supports JSON mode for more reliable structured output
            return ChatOpenAI(
                model=self.config.model_name,
                temperature=self.config.temperature,
                timeout=self.config.timeout_seconds,
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                model_kwargs={"response_format": {"type": "json_object"}},
            )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True,
    )
    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: type[T],
    ) -> tuple[T, AgentExecutionMetadata]:
        """Call LLM with structured output.
        
        Uses JSON mode when available for more reliable output.
        Falls back to regex extraction if needed.
        
        Args:
            system_prompt: System instruction
            user_prompt: User input
            output_schema: Expected output schema class
            
        Returns:
            Tuple of (validated output object, execution metadata)
            
        Raises:
            ValidationError: If output doesn't match schema
            Exception: For LLM/API errors
        """
        import time
        
        start_time = time.time()
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        
        # Get response from LLM
        response = await self.llm.ainvoke(messages)
        content = response.content
        
        if not isinstance(content, str):
            content = str(content)
        
        execution_time_ms = (time.time() - start_time) * 1000
        
        # Parse JSON
        parsed, parse_method = self._parse_json(content)
        
        # Validate against schema
        try:
            result = output_schema(**parsed)
        except ValidationError as e:
            # Try to fix common issues
            fixed = self._attempt_fix(parsed, e)
            if fixed:
                result = output_schema(**fixed)
            else:
                raise
        
        # Create metadata
        metadata = AgentExecutionMetadata(
            agent_name=self.name,
            prompt_version=self.config.prompt_version,
            schema_version=self.config.schema_version,
            model_name=self.config.model_name,
            temperature=self.config.temperature,
            execution_time_ms=execution_time_ms,
            raw_output=content[:1000],  # Truncate for storage
            parsed_output=parsed,
        )
        
        return result, metadata
    
    def _parse_json(self, content: str) -> tuple[dict[str, Any], str]:
        """Parse JSON from LLM response.
        
        Args:
            content: Raw LLM response
            
        Returns:
            Tuple of (parsed dict, parse method used)
        """
        import json
        import re
        
        # Try direct parse first (works with JSON mode)
        try:
            return json.loads(content), "direct"
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1)), "markdown_codeblock"
            except json.JSONDecodeError:
                pass
        
        # Try to find any JSON object
        json_match = re.search(r'(\{.*\})', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1)), "regex_extract"
            except json.JSONDecodeError:
                pass
        
        raise ValueError(f"Could not parse JSON from response: {content[:200]}...")
    
    def _attempt_fix(
        self,
        data: dict[str, Any],
        error: ValidationError,
    ) -> dict[str, Any] | None:
        """Attempt to fix common validation errors."""
        fixed = data.copy()
        
        for err in error.errors():
            field_path = err.get("loc", ())
            error_type = err.get("type", "")
            
            # Handle missing required fields
            if "missing" in error_type:
                if field_path:
                    field_name = field_path[-1]
                    # Set default based on field name patterns
                    if "list" in str(err.get("input", "")).lower():
                        fixed[field_name] = []
                    elif "dict" in str(err.get("input", "")).lower():
                        fixed[field_name] = {}
                    else:
                        fixed[field_name] = ""
        
        return fixed if fixed != data else None
    
    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> BaseModel:
        """Execute agent's main task.
        
        Args:
            context: Execution context with inputs
            
        Returns:
            Structured output matching agent's schema
        """
        pass
    
    def get_system_prompt(self) -> str:
        """Get system prompt for this agent."""
        raise NotImplementedError
    
    def format_context(self, context: dict[str, Any]) -> str:
        """Format context for LLM prompt."""
        lines = []
        for key, value in context.items():
            if isinstance(value, dict):
                lines.append(f"## {key}")
                for k, v in value.items():
                    lines.append(f"- {k}: {v}")
            elif isinstance(value, list):
                lines.append(f"## {key}")
                for item in value:
                    lines.append(f"- {item}")
            else:
                lines.append(f"## {key}\n{value}")
        return "\n\n".join(lines)
    
    def get_execution_metadata(self) -> AgentExecutionMetadata | None:
        """Get metadata from last execution."""
        return self._execution_metadata
