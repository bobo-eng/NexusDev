"""Stage transition rules and logic."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.sop.sop_engine import SOPConfig


class TransitionCondition(StrEnum):
    """Predefined transition conditions."""

    ALWAYS = "always"
    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"
    ON_APPROVAL = "on_approval"
    ON_REJECTION = "on_rejection"
    ON_RETRY_EXHAUSTED = "on_retry_exhausted"
    MANUAL = "manual"


@dataclass
class TransitionRule:
    """A single transition rule.

    Defines when and how to transition from one stage to another.
    """

    from_stage: str
    to_stage: str
    condition: TransitionCondition

    # Optional guard function
    guard: Callable[[dict[str, Any]], bool] | None = None

    # Metadata
    description: str = ""
    priority: int = 0  # Higher priority rules evaluated first

    def evaluate(self, context: dict[str, Any]) -> bool:
        """Evaluate if this transition should fire.

        Args:
            context: Execution context with current state

        Returns:
            True if transition should occur
        """
        if self.guard:
            return self.guard(context)
        return True


@dataclass
class StageTransition:
    """Manages transitions for a stage.

    A stage can have multiple possible transitions
    based on different conditions.
    """

    stage_name: str
    rules: list[TransitionRule] = None

    def __post_init__(self):
        if self.rules is None:
            self.rules = []

    def add_rule(self, rule: TransitionRule) -> "StageTransition":
        """Add a transition rule."""
        self.rules.append(rule)
        # Sort by priority
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        return self

    def get_next_stage(self, context: dict[str, Any]) -> str | None:
        """Determine next stage based on context.

        Args:
            context: Execution context

        Returns:
            Next stage name or None if no transition matches
        """
        for rule in self.rules:
            if rule.evaluate(context):
                return rule.to_stage
        return None

    @classmethod
    def create_linear_transition(
        cls,
        stage_name: str,
        next_stage: str,
    ) -> "StageTransition":
        """Create a simple linear transition.

        Args:
            stage_name: Current stage
            next_stage: Next stage in sequence

        Returns:
            StageTransition with single success rule
        """
        return cls(
            stage_name=stage_name,
            rules=[
                TransitionRule(
                    from_stage=stage_name,
                    to_stage=next_stage,
                    condition=TransitionCondition.ON_SUCCESS,
                    description=f"Proceed to {next_stage} on success",
                )
            ],
        )

    @classmethod
    def create_with_fallback(
        cls,
        stage_name: str,
        success_stage: str,
        failure_stage: str,
    ) -> "StageTransition":
        """Create transition with success and failure paths.

        Args:
            stage_name: Current stage
            success_stage: Stage on success
            failure_stage: Stage on failure

        Returns:
            StageTransition with success and failure rules
        """
        return cls(
            stage_name=stage_name,
            rules=[
                TransitionRule(
                    from_stage=stage_name,
                    to_stage=success_stage,
                    condition=TransitionCondition.ON_SUCCESS,
                    description=f"Proceed to {success_stage} on success",
                    priority=10,
                ),
                TransitionRule(
                    from_stage=stage_name,
                    to_stage=failure_stage,
                    condition=TransitionCondition.ON_FAILURE,
                    description=f"Go to {failure_stage} on failure",
                    priority=5,
                ),
            ],
        )


class TransitionGraph:
    """Graph of all stage transitions.

    Manages the complete workflow transition logic.
    """

    def __init__(self):
        self._transitions: dict[str, StageTransition] = {}

    def add_transition(self, transition: StageTransition) -> "TransitionGraph":
        """Add a stage transition."""
        self._transitions[transition.stage_name] = transition
        return self

    def get_transition(self, stage_name: str) -> StageTransition | None:
        """Get transition for a stage."""
        return self._transitions.get(stage_name)

    def get_next_stage(
        self,
        current_stage: str,
        context: dict[str, Any],
    ) -> str | None:
        """Get next stage based on current stage and context.

        Args:
            current_stage: Current stage name
            context: Execution context

        Returns:
            Next stage name or None
        """
        transition = self._transitions.get(current_stage)
        if not transition:
            return None
        return transition.get_next_stage(context)

    def validate_path(self, path: list[str]) -> bool:
        """Validate if a stage path is valid.

        Args:
            path: List of stage names

        Returns:
            True if path is valid
        """
        if len(path) < 2:
            return True

        for i in range(len(path) - 1):
            current = path[i]
            next_stage = path[i + 1]

            transition = self._transitions.get(current)
            if not transition:
                return False

            # Check if any rule leads to next_stage
            valid = any(r.to_stage == next_stage for r in transition.rules)
            if not valid:
                return False

        return True

    def get_all_paths(
        self,
        start: str,
        end: str,
        max_depth: int = 10,
    ) -> list[list[str]]:
        """Find all possible paths from start to end.

        Args:
            start: Starting stage
            end: Ending stage
            max_depth: Maximum path length

        Returns:
            List of valid paths
        """
        paths = []

        def dfs(current: str, path: list[str], depth: int):
            if depth > max_depth:
                return

            path = path + [current]

            if current == end:
                paths.append(path)
                return

            transition = self._transitions.get(current)
            if not transition:
                return

            for rule in transition.rules:
                if rule.to_stage not in path:  # Avoid cycles
                    dfs(rule.to_stage, path, depth + 1)

        dfs(start, [], 0)
        return paths

    @classmethod
    def from_sop_config(cls, config: "SOPConfig") -> "TransitionGraph":
        """Build transition graph from SOP config.

        Args:
            config: SOP configuration

        Returns:
            Populated transition graph
        """
        graph = cls()

        for stage in config.stages:
            rules = []

            # Success transition
            if stage.on_success:
                rules.append(
                    TransitionRule(
                        from_stage=stage.name,
                        to_stage=stage.on_success,
                        condition=TransitionCondition.ON_SUCCESS,
                        description=f"Success: go to {stage.on_success}",
                        priority=10,
                    )
                )

            # Failure transition
            if stage.on_failure:
                rules.append(
                    TransitionRule(
                        from_stage=stage.name,
                        to_stage=stage.on_failure,
                        condition=TransitionCondition.ON_FAILURE,
                        description=f"Failure: go to {stage.on_failure}",
                        priority=5,
                    )
                )

            # Rejection transition
            if stage.on_reject:
                rules.append(
                    TransitionRule(
                        from_stage=stage.name,
                        to_stage=stage.on_reject,
                        condition=TransitionCondition.ON_REJECTION,
                        description=f"Rejection: go to {stage.on_reject}",
                        priority=8,
                    )
                )

            if rules:
                graph.add_transition(
                    StageTransition(
                        stage_name=stage.name,
                        rules=rules,
                    )
                )

        return graph
