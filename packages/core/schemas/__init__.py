"""JSON Schemas for LLM structured outputs."""

from .agent_outputs import (
    CodeReviewOutput,
    CodingOutput,
    RequirementAnalysisOutput,
    SystemDesignOutput,
    TestingOutput,
)

__all__ = [
    "RequirementAnalysisOutput",
    "SystemDesignOutput",
    "CodingOutput",
    "CodeReviewOutput",
    "TestingOutput",
]
