"""Metrics collection for observability.

Tracks:
- Stage success/failure rates
- Agent execution times
- Retry counts
- Approval wait times
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any


@dataclass
class StageMetrics:
    """Metrics for a single stage execution."""

    stage_type: str
    agent_name: str
    success: bool
    execution_time_ms: float
    retry_count: int = 0
    error_type: str | None = None


@dataclass
class AgentMetrics:
    """Aggregated metrics for an agent."""

    agent_name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_execution_time_ms: float = 0.0
    retry_count: int = 0


@dataclass
class ApprovalMetrics:
    """Metrics for approval workflow."""

    total_requests: int = 0
    approved: int = 0
    rejected: int = 0
    timed_out: int = 0
    total_wait_time_hours: float = 0.0


class MetricsCollector:
    """Collect and aggregate metrics."""

    def __init__(self):
        self._stage_metrics: list[StageMetrics] = []
        self._agent_metrics: dict[str, AgentMetrics] = {}
        self._approval_metrics = ApprovalMetrics()

    def record_stage(
        self,
        stage_type: str,
        agent_name: str,
        success: bool,
        execution_time_ms: float,
        retry_count: int = 0,
        error_type: str | None = None,
    ) -> None:
        """Record stage execution metrics."""
        metric = StageMetrics(
            stage_type=stage_type,
            agent_name=agent_name,
            success=success,
            execution_time_ms=execution_time_ms,
            retry_count=retry_count,
            error_type=error_type,
        )
        self._stage_metrics.append(metric)

        # Update agent metrics
        if agent_name not in self._agent_metrics:
            self._agent_metrics[agent_name] = AgentMetrics(agent_name=agent_name)

        agent = self._agent_metrics[agent_name]
        agent.total_calls += 1
        agent.total_execution_time_ms += execution_time_ms
        agent.retry_count += retry_count

        if success:
            agent.successful_calls += 1
        else:
            agent.failed_calls += 1

    def record_approval(
        self,
        approved: bool,
        rejected: bool = False,
        timed_out: bool = False,
        wait_time_hours: float = 0.0,
    ) -> None:
        """Record approval metrics."""
        self._approval_metrics.total_requests += 1
        self._approval_metrics.total_wait_time_hours += wait_time_hours

        if approved:
            self._approval_metrics.approved += 1
        elif rejected:
            self._approval_metrics.rejected += 1
        elif timed_out:
            self._approval_metrics.timed_out += 1

    def get_agent_success_rate(self, agent_name: str) -> float:
        """Get success rate for an agent."""
        agent = self._agent_metrics.get(agent_name)
        if not agent or agent.total_calls == 0:
            return 0.0
        return agent.successful_calls / agent.total_calls

    def get_agent_avg_execution_time(self, agent_name: str) -> float:
        """Get average execution time for an agent."""
        agent = self._agent_metrics.get(agent_name)
        if not agent or agent.total_calls == 0:
            return 0.0
        return agent.total_execution_time_ms / agent.total_calls

    def get_overall_success_rate(self) -> float:
        """Get overall success rate."""
        total = len(self._stage_metrics)
        if total == 0:
            return 0.0
        successful = sum(1 for m in self._stage_metrics if m.success)
        return successful / total

    def get_approval_stats(self) -> dict[str, Any]:
        """Get approval statistics."""
        m = self._approval_metrics

        avg_wait = 0.0
        if m.total_requests > 0:
            avg_wait = m.total_wait_time_hours / m.total_requests

        return {
            "total_requests": m.total_requests,
            "approved": m.approved,
            "rejected": m.rejected,
            "timed_out": m.timed_out,
            "approval_rate": m.approved / m.total_requests if m.total_requests > 0 else 0.0,
            "avg_wait_time_hours": avg_wait,
        }

    def get_all_metrics(self) -> dict[str, Any]:
        """Get all metrics summary."""
        return {
            "overall_success_rate": self.get_overall_success_rate(),
            "total_stages": len(self._stage_metrics),
            "agents": {
                name: {
                    "success_rate": self.get_agent_success_rate(name),
                    "avg_execution_time_ms": self.get_agent_avg_execution_time(name),
                    "total_calls": agent.total_calls,
                    "retry_count": agent.retry_count,
                }
                for name, agent in self._agent_metrics.items()
            },
            "approvals": self.get_approval_stats(),
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._stage_metrics.clear()
        self._agent_metrics.clear()
        self._approval_metrics = ApprovalMetrics()


# Global metrics instance
_metrics = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Get global metrics collector."""
    return _metrics


def timed(metric_name: str | None = None):
    """Decorator to time function execution.

    Usage:
        @timed("agent_execution")
        async def execute(self, context):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                success = True
                return result
            except Exception:
                success = False
                raise
            finally:
                elapsed_ms = (time.time() - start) * 1000
                name = metric_name or func.__name__
                # Could emit to metrics system here

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                success = True
                return result
            except Exception:
                success = False
                raise
            finally:
                elapsed_ms = (time.time() - start) * 1000
                name = metric_name or func.__name__

        return async_wrapper if func.__code__.co_flags & 0x80 else sync_wrapper

    return decorator
