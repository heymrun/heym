import json
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.mcp import (
    _connection_has_unresolved_credential_reference,
    _redact_mcp_error,
    _resolve_mcp_fetch_credentials,
    get_credentials_context_for_user,
)
from app.db.models import CredentialType as DBCredentialType
from app.models.schemas import CredentialType


class JungleGridMCPIntegrationTests(unittest.TestCase):
    def test_credential_type_is_registered(self) -> None:
        self.assertEqual(DBCredentialType.jungle_grid.value, "jungle_grid")
        self.assertEqual(CredentialType.jungle_grid.value, "jungle_grid")

    def test_fetch_tool_connection_resolves_api_key_without_serializing_secret(self) -> None:
        connection = {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@jungle-grid/mcp"],
            "env": {
                "JUNGLE_GRID_API_KEY": "$credentials.jungle_grid",
                "JUNGLE_GRID_API_URL": "https://orchestrator.example.com",
            },
        }

        resolved = _resolve_mcp_fetch_credentials(
            connection,
            {"jungle_grid": "test-secret-value"},
        )

        self.assertEqual(resolved["env"]["JUNGLE_GRID_API_KEY"], "test-secret-value")
        self.assertEqual(
            resolved["env"]["JUNGLE_GRID_API_URL"],
            "https://orchestrator.example.com",
        )
        self.assertNotIn("test-secret-value", json.dumps(connection))

    def test_missing_credential_reference_is_detected(self) -> None:
        resolved = _resolve_mcp_fetch_credentials(
            {"env": {"JUNGLE_GRID_API_KEY": "$credentials.missing"}},
            {},
        )

        self.assertTrue(_connection_has_unresolved_credential_reference(resolved))

    def test_mcp_errors_redact_jungle_grid_api_key(self) -> None:
        message = "server failed with JUNGLE_GRID_API_KEY=test-secret-value"
        redacted = _redact_mcp_error(message, {"jungle_grid": "test-secret-value"})

        self.assertEqual(redacted, "server failed with JUNGLE_GRID_API_KEY=[redacted]")

    def test_example_workflow_contains_jungle_grid_mcp_without_secret(self) -> None:
        example_path = (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "examples"
            / "jungle-grid-mcp-workflow.json"
        )
        workflow = json.loads(example_path.read_text())
        serialized = json.dumps(workflow)

        self.assertIn("@jungle-grid/mcp", serialized)
        self.assertIn("$credentials.jungle_grid", serialized)
        self.assertNotIn("jg_", serialized)
        self.assertEqual(workflow["nodes"][1]["type"], "agent")


class JungleGridCredentialContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_credentials_context_includes_team_shared_jungle_grid_credentials(self) -> None:
        user_id = uuid.uuid4()
        team_credential = SimpleNamespace(
            name="team_jungle_grid",
            encrypted_config="encrypted",
            type=DBCredentialType.jungle_grid,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(
                    scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                ),
                MagicMock(
                    scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                ),
                MagicMock(
                    scalars=MagicMock(
                        return_value=MagicMock(all=MagicMock(return_value=[team_credential]))
                    )
                ),
            ]
        )

        with patch("app.api.mcp.decrypt_config", return_value={"api_key": "team-secret-value"}):
            context = await get_credentials_context_for_user(db, user_id)

        self.assertEqual(context["team_jungle_grid"], "team-secret-value")
