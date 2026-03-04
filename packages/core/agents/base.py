"""Base agent class with common functionality."""

from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

T = TypeVar("T", bound=BaseModel)


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    name: str
    description: str = ""
    model_name: str = "gpt-4"
    temperature: float = 0.2
    max_retries: int = 3
    timeout_seconds: int = 300
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

    # LLM response cache
    llm_cache_enabled: bool = True
    llm_cache_ttl_seconds: int = 600
    llm_cache_max_entries: int = 512


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
    cache_hit: bool = False
    raw_output: str = ""
    parsed_output: dict[str, Any] = field(default_factory=dict)


@dataclass
class _CacheEntry:
    """Single LLM cache entry."""

    payload: dict[str, Any]
    created_at: float


class _LLMResponseCache:
    """In-memory TTL cache for LLM responses."""

    def __init__(self, ttl_seconds: int, max_entries: int):
        self.ttl_seconds = max(ttl_seconds, 1)
        self.max_entries = max(max_entries, 1)
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._evictions = 0
        self._expired = 0

    def get(self, key: str, now: float) -> dict[str, Any] | None:
        """Read payload from cache if available and not expired."""
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None

        if now - entry.created_at > self.ttl_seconds:
            self._entries.pop(key, None)
            self._misses += 1
            self._expired += 1
            return None

        self._entries.move_to_end(key)
        self._hits += 1
        return entry.payload

    def set(self, key: str, payload: dict[str, Any], now: float) -> None:
        """Store payload in cache and evict oldest entries if needed."""
        self._entries[key] = _CacheEntry(payload=payload, created_at=now)
        self._entries.move_to_end(key)
        self._sets += 1

        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1

    def clear(self) -> None:
        """Clear all cache entries."""
        self._entries.clear()

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "sets": self._sets,
            "evictions": self._evictions,
            "expired": self._expired,
            "size": len(self._entries),
            "ttl_seconds": self.ttl_seconds,
            "max_entries": self.max_entries,
        }


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
    _llm_response_cache: _LLMResponseCache | None = None

    def __init__(self, config: AgentConfig | None = None, llm: BaseChatModel | None = None):
        self.config = config or self._default_config()
        self._apply_cache_env_overrides()
        self._llm = llm
        self._output_parser = JsonOutputParser()
        self._execution_metadata: AgentExecutionMetadata | None = None

    def _default_config(self) -> AgentConfig:
        """Get default agent configuration."""
        import os

        return AgentConfig(
            name=self.__class__.__name__,
            prompt_version=self.PROMPT_VERSION,
            schema_version=self.SCHEMA_VERSION,
            provider="openai",
            model_name=os.getenv("AGENT_MODEL", "MiniMax-M2.5"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.minimax.chat/v1"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            temperature=0.2,
            timeout_seconds=120,
            llm_cache_enabled=self._env_bool("LLM_CACHE_ENABLED", True),
            llm_cache_ttl_seconds=self._env_int("LLM_CACHE_TTL_SECONDS", 600, minimum=1),
            llm_cache_max_entries=self._env_int("LLM_CACHE_MAX_ENTRIES", 512, minimum=1),
        )

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        """Read boolean value from environment."""
        import os

        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _env_int(name: str, default: int, minimum: int = 1) -> int:
        """Read integer value from environment."""
        import os

        raw = os.getenv(name)
        if raw is None:
            return default

        try:
            return max(int(raw), minimum)
        except ValueError:
            return default

    def _apply_cache_env_overrides(self) -> None:
        """Apply cache-related environment overrides to config."""
        self.config.llm_cache_enabled = self._env_bool(
            "LLM_CACHE_ENABLED",
            self.config.llm_cache_enabled,
        )
        self.config.llm_cache_ttl_seconds = self._env_int(
            "LLM_CACHE_TTL_SECONDS",
            self.config.llm_cache_ttl_seconds,
            minimum=1,
        )
        self.config.llm_cache_max_entries = self._env_int(
            "LLM_CACHE_MAX_ENTRIES",
            self.config.llm_cache_max_entries,
            minimum=1,
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

    def _is_llm_cache_enabled(self) -> bool:
        """Check whether LLM response caching is enabled."""
        return bool(self.config.llm_cache_enabled)

    @classmethod
    def _get_llm_response_cache(
        cls,
        ttl_seconds: int,
        max_entries: int,
    ) -> _LLMResponseCache:
        """Get or initialize shared LLM response cache."""
        if (
            BaseAgent._llm_response_cache is None
            or BaseAgent._llm_response_cache.ttl_seconds != ttl_seconds
            or BaseAgent._llm_response_cache.max_entries != max_entries
        ):
            BaseAgent._llm_response_cache = _LLMResponseCache(
                ttl_seconds=ttl_seconds,
                max_entries=max_entries,
            )
        return BaseAgent._llm_response_cache

    @classmethod
    def clear_llm_cache(cls) -> None:
        """Clear shared LLM response cache."""
        if BaseAgent._llm_response_cache is not None:
            BaseAgent._llm_response_cache.clear()

    @classmethod
    def get_llm_cache_stats(cls) -> dict[str, Any]:
        """Get shared LLM cache statistics."""
        if BaseAgent._llm_response_cache is None:
            return {
                "hits": 0,
                "misses": 0,
                "sets": 0,
                "evictions": 0,
                "expired": 0,
                "size": 0,
                "ttl_seconds": 0,
                "max_entries": 0,
            }
        return BaseAgent._llm_response_cache.stats()

    def _build_llm_cache_key(
        self,
        system_prompt: str,
        user_prompt: str,
        output_schema: type[BaseModel],
    ) -> str:
        """Build stable cache key for LLM request + expected schema."""
        import hashlib
        import json

        payload = {
            "provider": self.config.provider,
            "model_name": self.config.model_name,
            "base_url": self.config.base_url,
            "temperature": self.config.temperature,
            "response_format": self.config.response_format,
            "prompt_version": self.config.prompt_version,
            "schema_version": self.config.schema_version,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "output_schema": f"{output_schema.__module__}.{output_schema.__qualname__}",
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _create_llm(self) -> BaseChatModel:
        """Create LLM instance based on config.

        Uses JSON mode when available (OpenAI) for more reliable structured output.
        """
        from langchain_anthropic import ChatAnthropic
        from langchain_openai import ChatOpenAI

        if self.config.provider == "anthropic":
            return ChatAnthropic(
                model_name=self.config.model_name,
                temperature=self.config.temperature,
                timeout=self.config.timeout_seconds,
                api_key=self.config.api_key,
            )
        else:
            # OpenAI supports JSON mode for more reliable structured output
            extra_body: dict[str, Any] | None = None
            if self.config.base_url and "minimax" in self.config.base_url.lower():
                # MiniMax can separate reasoning from final content.
                extra_body = {"reasoning_split": True}

            return ChatOpenAI(
                model=self.config.model_name,
                temperature=self.config.temperature,
                timeout=self.config.timeout_seconds,
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                model_kwargs={"response_format": {"type": "json_object"}},
                extra_body=extra_body,
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
    ) -> T:
        """Call LLM with structured output.

        Uses JSON mode when available for more reliable output.
        Falls back to regex extraction if needed.

        Args:
            system_prompt: System instruction
            user_prompt: User input
            output_schema: Expected output schema class

        Returns:
            Validated output object

        Raises:
            ValidationError: If output doesn't match schema
            Exception: For LLM/API errors
        """
        import time

        start_time = time.time()
        cache_key: str | None = None

        if self._is_llm_cache_enabled():
            cache = self._get_llm_response_cache(
                ttl_seconds=self.config.llm_cache_ttl_seconds,
                max_entries=self.config.llm_cache_max_entries,
            )
            cache_key = self._build_llm_cache_key(system_prompt, user_prompt, output_schema)
            cached_payload = cache.get(cache_key, now=start_time)
            if cached_payload is not None:
                content = str(cached_payload.get("raw_output", ""))
                parsed = cached_payload.get("parsed_output", {})
                if not isinstance(parsed, dict):
                    parsed, _parse_method = self._parse_json(content)

                result = self._validate_output(parsed, output_schema)
                metadata = AgentExecutionMetadata(
                    agent_name=self.name,
                    prompt_version=self.config.prompt_version,
                    schema_version=self.config.schema_version,
                    model_name=self.config.model_name,
                    temperature=self.config.temperature,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    cache_hit=True,
                    raw_output=content[:1000],  # Truncate for storage
                    parsed_output=parsed,
                )
                self._execution_metadata = metadata
                return result

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
        parsed, _parse_method = self._parse_json(content)

        result = self._validate_output(parsed, output_schema)

        if self._is_llm_cache_enabled() and cache_key:
            cache_payload = {
                "raw_output": content,
                "parsed_output": parsed,
            }
            cache = self._get_llm_response_cache(
                ttl_seconds=self.config.llm_cache_ttl_seconds,
                max_entries=self.config.llm_cache_max_entries,
            )
            cache.set(cache_key, cache_payload, now=time.time())

        # Create metadata
        metadata = AgentExecutionMetadata(
            agent_name=self.name,
            prompt_version=self.config.prompt_version,
            schema_version=self.config.schema_version,
            model_name=self.config.model_name,
            temperature=self.config.temperature,
            execution_time_ms=execution_time_ms,
            cache_hit=False,
            raw_output=content[:1000],  # Truncate for storage
            parsed_output=parsed,
        )

        self._execution_metadata = metadata
        return result

    def _parse_json(self, content: str) -> tuple[dict[str, Any], str]:
        """Parse JSON from LLM response.

        Args:
            content: Raw LLM response

        Returns:
            Tuple of (parsed dict, parse method used)
        """
        import json
        import re

        cleaned_content = self._strip_reasoning_trace(content)

        # Try direct parse first (works with JSON mode)
        try:
            return json.loads(cleaned_content), "direct"
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned_content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1)), "markdown_codeblock"
            except json.JSONDecodeError:
                pass

        # Try to find any JSON object
        json_match = re.search(r"(\{.*\})", cleaned_content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1)), "regex_extract"
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from response: {content[:200]}...")

    def _strip_reasoning_trace(self, content: str) -> str:
        """Strip provider-specific reasoning wrappers from output content."""
        import re

        cleaned = re.sub(
            r"<think>.*?</think>\s*",
            "",
            content,
            flags=re.DOTALL | re.IGNORECASE,
        )
        cleaned = re.sub(
            r"<thinking>.*?</thinking>\s*",
            "",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return cleaned.strip()

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
            if "missing" in error_type and field_path:
                field_name = field_path[-1]
                # Set default based on field name patterns
                if "list" in str(err.get("input", "")).lower():
                    fixed[field_name] = []
                elif "dict" in str(err.get("input", "")).lower():
                    fixed[field_name] = {}
                else:
                    fixed[field_name] = ""

        return fixed if fixed != data else None

    def _validate_output(self, parsed: dict[str, Any], output_schema: type[T]) -> T:
        """Validate parsed JSON against output schema with fallback fixups."""
        try:
            return output_schema(**parsed)
        except ValidationError as validation_error:
            fixed = self._attempt_fix(parsed, validation_error)
            if fixed:
                return output_schema(**fixed)
            raise

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
