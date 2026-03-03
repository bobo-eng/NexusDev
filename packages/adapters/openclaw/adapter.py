"""OpenClaw Adapter - thin wrapper for OpenClaw skill/plugin integration.

This adapter follows the "Core First" principle:
- Core logic stays in core/
- Adapter only handles parameter mapping and tool calls
- No business logic in adapter layer
"""

from typing import Any
from uuid import UUID

from core.domain.artifact import Artifact
from core.domain.session import Session
from core.domain.stage import Stage


class OpenClawAdapter:
    """Adapter for OpenClaw platform integration.

    OpenClaw is a skill/plugin-based platform for AI agents.
    This adapter maps NexusDev core concepts to OpenClaw's
    skill format without duplicating business logic.

    Responsibilities:
    1. Map Session/Stage/Artifact to OpenClaw skill format
    2. Handle tool call parameter conversion
    3. Forward session context transparently
    """

    def __init__(self, skill_name: str = "nexusdev"):
        self.skill_name = skill_name

    def to_skill_format(
        self,
        session: Session,
        stage: Stage | None = None,
        artifacts: list[Artifact] | None = None,
    ) -> dict[str, Any]:
        """Convert NexusDev entities to OpenClaw skill format.

        Args:
            session: Session entity
            stage: Optional stage entity
            artifacts: Optional list of artifacts

        Returns:
            OpenClaw skill-compatible dictionary
        """
        skill_data = {
            "skill": self.skill_name,
            "version": "1.0.0",
            "session": {
                "id": str(session.id),
                "name": session.name,
                "status": session.status.value,
                "requirement": session.requirement,
                "context": session.context,
            },
        }

        if stage:
            skill_data["stage"] = {
                "id": str(stage.id),
                "name": stage.name,
                "type": stage.stage_type.value,
                "status": stage.status.value,
                "agent": stage.agent_name,
                "sequence": stage.sequence,
            }

        if artifacts:
            skill_data["artifacts"] = [
                {
                    "id": str(a.id),
                    "name": a.name,
                    "type": a.artifact_type.value,
                    "summary": a.get_summary(500),
                }
                for a in artifacts
            ]

        return skill_data

    def from_skill_result(
        self,
        skill_result: dict[str, Any],
        session_id: UUID,
        stage_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Convert OpenClaw skill result to NexusDev format.

        Args:
            skill_result: Result from OpenClaw skill execution
            session_id: Session ID
            stage_id: Optional stage ID

        Returns:
            NexusDev-compatible result dictionary
        """
        return {
            "session_id": str(session_id),
            "stage_id": str(stage_id) if stage_id else None,
            "success": skill_result.get("success", False),
            "output": skill_result.get("output", {}),
            "artifacts": skill_result.get("artifacts", []),
            "logs": skill_result.get("logs", []),
            "metrics": skill_result.get("metrics", {}),
        }

    def map_tool_call(
        self,
        tool_name: str,
        tool_params: dict[str, Any],
        session_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Map a tool call to OpenClaw format.

        Args:
            tool_name: Name of the tool
            tool_params: Tool parameters
            session_context: Session context

        Returns:
            OpenClaw tool call format
        """
        return {
            "skill": self.skill_name,
            "tool": tool_name,
            "parameters": {
                **tool_params,
                "_session_context": session_context,
            },
        }

    def extract_artifacts_from_skill(
        self,
        skill_output: dict[str, Any],
        session_id: UUID,
        stage_id: UUID,
        created_by: str = "openclaw",
    ) -> list[Artifact]:
        """Extract artifacts from OpenClaw skill output.

        Args:
            skill_output: Skill execution output
            session_id: Session ID
            stage_id: Stage ID
            created_by: Creator identifier

        Returns:
            List of Artifact entities
        """
        from core.domain.artifact import ArtifactType

        artifacts = []

        for art_data in skill_output.get("artifacts", []):
            artifact = Artifact(
                session_id=session_id,
                stage_id=stage_id,
                name=art_data.get("name", "unnamed"),
                artifact_type=ArtifactType(art_data.get("type", "custom")),
                description=art_data.get("description", ""),
                content=art_data.get("content", ""),
                content_type=art_data.get("content_type", "text/plain"),
                file_path=art_data.get("file_path"),
                language=art_data.get("language"),
                metadata=art_data.get("metadata", {}),
                created_by=created_by,
            )
            artifacts.append(artifact)

        return artifacts

    def create_skill_manifest(self) -> dict[str, Any]:
        """Create OpenClaw skill manifest for NexusDev.

        Returns:
            Skill manifest dictionary
        """
        return {
            "name": self.skill_name,
            "version": "1.0.0",
            "description": "NexusDev multi-agent development system",
            "author": "NexusDev Team",
            "entry_points": {
                "requirement_analysis": {
                    "description": "Analyze requirements",
                    "input_schema": {"requirement": "string"},
                    "output_schema": {"analysis": "object"},
                },
                "system_design": {
                    "description": "Design system architecture",
                    "input_schema": {"requirements": "object"},
                    "output_schema": {"design": "object"},
                },
                "coding": {
                    "description": "Implement code",
                    "input_schema": {"design": "object"},
                    "output_schema": {"code": "object"},
                },
                "code_review": {
                    "description": "Review code",
                    "input_schema": {"code": "object"},
                    "output_schema": {"review": "object"},
                },
                "testing": {
                    "description": "Run tests",
                    "input_schema": {"code": "object"},
                    "output_schema": {"tests": "object"},
                },
            },
            "config": {
                "timeout_seconds": 300,
                "max_retries": 3,
            },
        }
