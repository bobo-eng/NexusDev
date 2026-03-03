"""OpenWork Adapter - thin wrapper for OpenWork plugin integration.

OpenWork is another platform for AI agent workflows.
This adapter provides the same thin mapping as OpenClaw adapter.
"""

from typing import Any
from uuid import UUID

from core.domain.artifact import Artifact
from core.domain.session import Session
from core.domain.stage import Stage


class OpenWorkAdapter:
    """Adapter for OpenWork platform integration.
    
    OpenWork uses a plugin architecture for extending functionality.
    This adapter maps NexusDev concepts to OpenWork plugin format.
    
    Responsibilities:
    1. Map Session/Stage/Artifact to OpenWork plugin format
    2. Handle plugin parameter conversion
    3. Forward session context transparently
    """
    
    def __init__(self, plugin_name: str = "nexusdev"):
        self.plugin_name = plugin_name
    
    def to_plugin_format(
        self,
        session: Session,
        stage: Stage | None = None,
        artifacts: list[Artifact] | None = None,
    ) -> dict[str, Any]:
        """Convert NexusDev entities to OpenWork plugin format.
        
        Args:
            session: Session entity
            stage: Optional stage entity
            artifacts: Optional list of artifacts
            
        Returns:
            OpenWork plugin-compatible dictionary
        """
        plugin_data = {
            "plugin": self.plugin_name,
            "version": "1.0.0",
            "workflow": {
                "id": str(session.id),
                "name": session.name,
                "state": session.status.value,
                "input": {
                    "requirement": session.requirement,
                    "context": session.context,
                },
            },
        }
        
        if stage:
            plugin_data["task"] = {
                "id": str(stage.id),
                "name": stage.name,
                "type": stage.stage_type.value,
                "state": stage.status.value,
                "executor": stage.agent_name,
                "order": stage.sequence,
            }
        
        if artifacts:
            plugin_data["outputs"] = [
                {
                    "id": str(a.id),
                    "name": a.name,
                    "type": a.artifact_type.value,
                    "content_preview": a.get_summary(500),
                }
                for a in artifacts
            ]
        
        return plugin_data
    
    def from_plugin_result(
        self,
        plugin_result: dict[str, Any],
        session_id: UUID,
        stage_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Convert OpenWork plugin result to NexusDev format.
        
        Args:
            plugin_result: Result from OpenWork plugin execution
            session_id: Session ID
            stage_id: Optional stage ID
            
        Returns:
            NexusDev-compatible result dictionary
        """
        return {
            "session_id": str(session_id),
            "stage_id": str(stage_id) if stage_id else None,
            "success": plugin_result.get("status") == "success",
            "result": plugin_result.get("result", {}),
            "outputs": plugin_result.get("outputs", []),
            "logs": plugin_result.get("execution_logs", []),
            "metrics": plugin_result.get("performance", {}),
        }
    
    def map_action_call(
        self,
        action_name: str,
        action_params: dict[str, Any],
        workflow_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Map an action call to OpenWork format.
        
        Args:
            action_name: Name of the action
            action_params: Action parameters
            workflow_context: Workflow context
            
        Returns:
            OpenWork action call format
        """
        return {
            "plugin": self.plugin_name,
            "action": action_name,
            "input": {
                **action_params,
                "_workflow_context": workflow_context,
            },
        }
    
    def extract_artifacts_from_plugin(
        self,
        plugin_output: dict[str, Any],
        session_id: UUID,
        stage_id: UUID,
        created_by: str = "openwork",
    ) -> list[Artifact]:
        """Extract artifacts from OpenWork plugin output.
        
        Args:
            plugin_output: Plugin execution output
            session_id: Session ID
            stage_id: Stage ID
            created_by: Creator identifier
            
        Returns:
            List of Artifact entities
        """
        from core.domain.artifact import ArtifactType
        
        artifacts = []
        
        for out_data in plugin_output.get("outputs", []):
            artifact = Artifact(
                session_id=session_id,
                stage_id=stage_id,
                name=out_data.get("name", "unnamed"),
                artifact_type=ArtifactType(out_data.get("type", "custom")),
                description=out_data.get("description", ""),
                content=out_data.get("content", ""),
                content_type=out_data.get("content_type", "text/plain"),
                file_path=out_data.get("path"),
                language=out_data.get("language"),
                metadata=out_data.get("metadata", {}),
                created_by=created_by,
            )
            artifacts.append(artifact)
        
        return artifacts
    
    def create_plugin_spec(self) -> dict[str, Any]:
        """Create OpenWork plugin specification for NexusDev.
        
        Returns:
            Plugin specification dictionary
        """
        return {
            "name": self.plugin_name,
            "version": "1.0.0",
            "description": "NexusDev multi-agent development system",
            "author": "NexusDev Team",
            "actions": [
                {
                    "name": "analyze_requirements",
                    "description": "Analyze user requirements",
                    "input": {"requirement": {"type": "string", "required": True}},
                    "output": {"analysis": {"type": "object"}},
                },
                {
                    "name": "design_system",
                    "description": "Design system architecture",
                    "input": {"requirements": {"type": "object", "required": True}},
                    "output": {"design": {"type": "object"}},
                },
                {
                    "name": "implement_code",
                    "description": "Implement code from design",
                    "input": {"design": {"type": "object", "required": True}},
                    "output": {"code": {"type": "object"}},
                },
                {
                    "name": "review_code",
                    "description": "Review implemented code",
                    "input": {"code": {"type": "object", "required": True}},
                    "output": {"review": {"type": "object"}},
                },
                {
                    "name": "run_tests",
                    "description": "Run tests on code",
                    "input": {"code": {"type": "object", "required": True}},
                    "output": {"tests": {"type": "object"}},
                },
            ],
            "hooks": {
                "on_init": "initialize",
                "on_complete": "cleanup",
            },
            "config": {
                "timeout": 300,
                "retries": 3,
            },
        }
    
    def to_openclaw_format(
        self,
        plugin_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert OpenWork format to OpenClaw format (cross-platform).
        
        Args:
            plugin_data: OpenWork plugin data
            
        Returns:
            OpenClaw-compatible format
        """
        # Map OpenWork terminology to OpenClaw
        return {
            "skill": plugin_data.get("plugin"),
            "version": plugin_data.get("version"),
            "session": {
                "id": plugin_data.get("workflow", {}).get("id"),
                "name": plugin_data.get("workflow", {}).get("name"),
                "status": plugin_data.get("workflow", {}).get("state"),
                "requirement": plugin_data.get("workflow", {}).get("input", {}).get("requirement"),
                "context": plugin_data.get("workflow", {}).get("input", {}).get("context", {}),
            },
            "stage": {
                "id": plugin_data.get("task", {}).get("id"),
                "name": plugin_data.get("task", {}).get("name"),
                "type": plugin_data.get("task", {}).get("type"),
                "status": plugin_data.get("task", {}).get("state"),
                "agent": plugin_data.get("task", {}).get("executor"),
                "sequence": plugin_data.get("task", {}).get("order"),
            } if plugin_data.get("task") else None,
            "artifacts": [
                {
                    "id": o.get("id"),
                    "name": o.get("name"),
                    "type": o.get("type"),
                    "summary": o.get("content_preview"),
                }
                for o in plugin_data.get("outputs", [])
            ],
        }
