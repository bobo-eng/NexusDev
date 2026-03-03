"""Contract tests for platform adapters.

Ensures OpenClaw and OpenWork adapters maintain compatibility
with core domain models.
"""

from uuid import uuid4

from adapters.openclaw.adapter import OpenClawAdapter
from adapters.openwork.adapter import OpenWorkAdapter
from core.domain.artifact import Artifact, ArtifactType
from core.domain.session import Session
from core.domain.stage import Stage, StageType


class TestOpenClawAdapter:
    """Contract tests for OpenClaw adapter."""

    def test_to_skill_format_basic(self):
        """Test basic session conversion to skill format."""
        adapter = OpenClawAdapter()

        session = Session(
            name="Test Session",
            requirement="Build an API",
        )

        skill_data = adapter.to_skill_format(session)

        assert skill_data["skill"] == "nexusdev"
        assert skill_data["version"] == "1.0.0"
        assert skill_data["session"]["id"] == str(session.id)
        assert skill_data["session"]["name"] == "Test Session"
        assert skill_data["session"]["requirement"] == "Build an API"

    def test_to_skill_format_with_stage(self):
        """Test conversion with stage."""
        adapter = OpenClawAdapter()

        session = Session(
            name="Test Session",
            requirement="Build an API",
        )

        stage = Stage(
            session_id=session.id,
            name="Requirement Analysis",
            stage_type=StageType.REQUIREMENT_ANALYSIS,
            agent_name="pm_agent",
        )

        skill_data = adapter.to_skill_format(session, stage=stage)

        assert "stage" in skill_data
        assert skill_data["stage"]["name"] == "Requirement Analysis"
        assert skill_data["stage"]["type"] == "requirement_analysis"
        assert skill_data["stage"]["agent"] == "pm_agent"

    def test_to_skill_format_with_artifacts(self):
        """Test conversion with artifacts."""
        adapter = OpenClawAdapter()

        session = Session(
            name="Test Session",
            requirement="Build an API",
        )

        artifacts = [
            Artifact(
                session_id=session.id,
                name="design.md",
                artifact_type=ArtifactType.SYSTEM_DESIGN,
                content="# Design",
            )
        ]

        skill_data = adapter.to_skill_format(session, artifacts=artifacts)

        assert "artifacts" in skill_data
        assert len(skill_data["artifacts"]) == 1
        assert skill_data["artifacts"][0]["name"] == "design.md"

    def test_from_skill_result(self):
        """Test conversion from skill result."""
        adapter = OpenClawAdapter()

        skill_result = {
            "success": True,
            "output": {"files": []},
            "artifacts": [{"name": "test.py", "content": "print('hello')"}],
            "logs": ["Executed successfully"],
            "metrics": {"duration_ms": 1000},
        }

        session_id = uuid4()
        result = adapter.from_skill_result(skill_result, session_id)

        assert result["session_id"] == str(session_id)
        assert result["success"] is True
        assert "artifacts" in result

    def test_extract_artifacts(self):
        """Test artifact extraction from skill output."""
        adapter = OpenClawAdapter()

        skill_output = {
            "artifacts": [
                {
                    "name": "main.py",
                    "type": "source_code",
                    "content": "def main(): pass",
                    "language": "python",
                }
            ]
        }

        session_id = uuid4()
        stage_id = uuid4()

        artifacts = adapter.extract_artifacts_from_skill(skill_output, session_id, stage_id)

        assert len(artifacts) == 1
        assert artifacts[0].name == "main.py"
        assert artifacts[0].artifact_type == ArtifactType.SOURCE_CODE
        assert artifacts[0].session_id == session_id
        assert artifacts[0].stage_id == stage_id

    def test_skill_manifest(self):
        """Test skill manifest structure."""
        adapter = OpenClawAdapter()

        manifest = adapter.create_skill_manifest()

        assert manifest["name"] == "nexusdev"
        assert "entry_points" in manifest
        assert "requirement_analysis" in manifest["entry_points"]
        assert "config" in manifest


class TestOpenWorkAdapter:
    """Contract tests for OpenWork adapter."""

    def test_to_plugin_format_basic(self):
        """Test basic session conversion to plugin format."""
        adapter = OpenWorkAdapter()

        session = Session(
            name="Test Session",
            requirement="Build an API",
        )

        plugin_data = adapter.to_plugin_format(session)

        assert plugin_data["plugin"] == "nexusdev"
        assert plugin_data["version"] == "1.0.0"
        assert plugin_data["workflow"]["id"] == str(session.id)
        assert plugin_data["workflow"]["name"] == "Test Session"

    def test_to_plugin_format_with_task(self):
        """Test conversion with task (stage)."""
        adapter = OpenWorkAdapter()

        session = Session(
            name="Test Session",
            requirement="Build an API",
        )

        stage = Stage(
            session_id=session.id,
            name="Coding",
            stage_type=StageType.CODING,
            agent_name="coder_agent",
        )

        plugin_data = adapter.to_plugin_format(session, stage=stage)

        assert "task" in plugin_data
        assert plugin_data["task"]["name"] == "Coding"
        assert plugin_data["task"]["executor"] == "coder_agent"

    def test_from_plugin_result(self):
        """Test conversion from plugin result."""
        adapter = OpenWorkAdapter()

        plugin_result = {
            "status": "success",
            "result": {"code": {}},
            "outputs": [{"name": "test.py"}],
            "execution_logs": ["Done"],
            "performance": {"duration_ms": 500},
        }

        session_id = uuid4()
        result = adapter.from_plugin_result(plugin_result, session_id)

        assert result["session_id"] == str(session_id)
        assert result["success"] is True

    def test_plugin_spec(self):
        """Test plugin spec structure."""
        adapter = OpenWorkAdapter()

        spec = adapter.create_plugin_spec()

        assert spec["name"] == "nexusdev"
        assert "actions" in spec
        action_names = [a["name"] for a in spec["actions"]]
        assert "analyze_requirements" in action_names
        assert "implement_code" in action_names

    def test_cross_platform_conversion(self):
        """Test conversion between OpenWork and OpenClaw formats."""
        openwork = OpenWorkAdapter()

        session = Session(
            name="Test Session",
            requirement="Build an API",
        )

        stage = Stage(
            session_id=session.id,
            name="Testing",
            stage_type=StageType.TESTING,
            agent_name="tester_agent",
        )

        # Create OpenWork format
        plugin_data = openwork.to_plugin_format(session, stage=stage)

        # Convert to OpenClaw format
        claw_format = openwork.to_openclaw_format(plugin_data)

        assert claw_format["skill"] == "nexusdev"
        assert claw_format["session"]["name"] == "Test Session"
        assert claw_format["stage"]["name"] == "Testing"


class TestAdapterCompatibility:
    """Cross-adapter compatibility tests."""

    def test_both_adapters_handle_same_session(self):
        """Both adapters should handle the same session correctly."""
        openclaw = OpenClawAdapter()
        openwork = OpenWorkAdapter()

        session = Session(
            name="Compatibility Test",
            requirement="Test both adapters",
        )

        # Both should convert without errors
        claw_data = openclaw.to_skill_format(session)
        work_data = openwork.to_plugin_format(session)

        # Both should preserve session ID
        assert claw_data["session"]["id"] == str(session.id)
        assert work_data["workflow"]["id"] == str(session.id)

    def test_both_adapters_handle_same_artifact(self):
        """Both adapters should extract artifacts correctly."""
        openclaw = OpenClawAdapter()
        openwork = OpenWorkAdapter()

        session_id = uuid4()
        stage_id = uuid4()

        # OpenClaw format
        claw_output = {"artifacts": [{"name": "test.py", "type": "source_code", "content": "pass"}]}

        # OpenWork format
        work_output = {"outputs": [{"name": "test.py", "type": "source_code", "content": "pass"}]}

        claw_artifacts = openclaw.extract_artifacts_from_skill(claw_output, session_id, stage_id)
        work_artifacts = openwork.extract_artifacts_from_plugin(work_output, session_id, stage_id)

        # Both should produce equivalent artifacts
        assert len(claw_artifacts) == len(work_artifacts)
        assert claw_artifacts[0].name == work_artifacts[0].name
        assert claw_artifacts[0].artifact_type == work_artifacts[0].artifact_type
