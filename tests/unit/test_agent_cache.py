"""Tests for BaseAgent LLM response cache."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from core.agents.base import AgentConfig, BaseAgent
from pydantic import BaseModel


class DummyOutput(BaseModel):
    """Small output schema for cache tests."""

    value: str


class FakeLLM:
    """Fake LLM that counts invocations."""

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ['{"value":"ok"}']
        self.calls = 0

    async def ainvoke(self, messages: list[Any]) -> SimpleNamespace:
        """Return deterministic fake response."""
        del messages
        index = min(self.calls, len(self.responses) - 1)
        content = self.responses[index]
        self.calls += 1
        return SimpleNamespace(content=content)


class DummyAgent(BaseAgent):
    """Minimal agent wrapper for invoking _call_llm."""

    def get_system_prompt(self) -> str:
        return "system"

    async def execute(self, context: dict[str, Any]) -> DummyOutput:
        prompt = str(context.get("prompt", ""))
        return await self._call_llm(
            system_prompt=self.get_system_prompt(),
            user_prompt=prompt,
            output_schema=DummyOutput,
        )


@pytest.fixture(autouse=True)
def _reset_cache_and_env(monkeypatch: pytest.MonkeyPatch):
    """Ensure deterministic cache behavior per test."""
    for key in ("LLM_CACHE_ENABLED", "LLM_CACHE_TTL_SECONDS", "LLM_CACHE_MAX_ENTRIES"):
        monkeypatch.delenv(key, raising=False)
    BaseAgent.clear_llm_cache()
    yield
    BaseAgent.clear_llm_cache()


@pytest.mark.asyncio
async def test_llm_cache_hit_for_same_prompt() -> None:
    """Same prompt + model params should hit cache."""
    llm = FakeLLM()
    config = AgentConfig(
        name="dummy",
        model_name="model-a",
        temperature=0.2,
        llm_cache_enabled=True,
        llm_cache_ttl_seconds=60,
        llm_cache_max_entries=32,
    )
    agent = DummyAgent(config=config, llm=llm)

    first = await agent.execute({"prompt": "same prompt"})
    second = await agent.execute({"prompt": "same prompt"})

    assert first.value == "ok"
    assert second.value == "ok"
    assert llm.calls == 1

    stats = DummyAgent.get_llm_cache_stats()
    assert stats["hits"] == 1
    assert stats["sets"] == 1


@pytest.mark.asyncio
async def test_llm_cache_respects_disable_flag() -> None:
    """Disabled cache should always call LLM."""
    llm = FakeLLM()
    config = AgentConfig(
        name="dummy",
        model_name="model-a",
        llm_cache_enabled=False,
    )
    agent = DummyAgent(config=config, llm=llm)

    await agent.execute({"prompt": "same prompt"})
    await agent.execute({"prompt": "same prompt"})

    assert llm.calls == 2
    stats = DummyAgent.get_llm_cache_stats()
    assert stats["size"] == 0


@pytest.mark.asyncio
async def test_llm_cache_ttl_expiry_triggers_miss() -> None:
    """Expired cache entry should call LLM again."""
    llm = FakeLLM(responses=['{"value":"first"}', '{"value":"second"}'])
    config = AgentConfig(
        name="dummy",
        model_name="model-a",
        llm_cache_enabled=True,
        llm_cache_ttl_seconds=1,
        llm_cache_max_entries=32,
    )
    agent = DummyAgent(config=config, llm=llm)

    first = await agent.execute({"prompt": "ttl prompt"})
    await asyncio.sleep(1.1)
    second = await agent.execute({"prompt": "ttl prompt"})

    assert first.value == "first"
    assert second.value == "second"
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_llm_cache_key_includes_model_params() -> None:
    """Different model parameters should not reuse cache."""
    llm = FakeLLM()
    agent_a = DummyAgent(
        config=AgentConfig(name="dummy-a", model_name="model-a", temperature=0.1),
        llm=llm,
    )
    agent_b = DummyAgent(
        config=AgentConfig(name="dummy-b", model_name="model-b", temperature=0.1),
        llm=llm,
    )

    await agent_a.execute({"prompt": "same prompt"})
    await agent_b.execute({"prompt": "same prompt"})

    assert llm.calls == 2
