import importlib.util
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

from app.db.models import MCPServer, MCPServerWorkflow
from app.models.schemas import MCPServerResponse

_MIGRATION = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "155_mcp_server_endpoint_path.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_155_mcp_server_endpoint_path", _MIGRATION
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPServerModelImportTests(unittest.TestCase):
    def test_mcp_server_model_importable(self) -> None:
        assert MCPServer.__tablename__ == "mcp_servers"

    def test_mcp_server_workflow_model_importable(self) -> None:
        assert MCPServerWorkflow.__tablename__ == "mcp_server_workflows"

    def test_mcp_server_endpoint_path_column_defaults(self) -> None:
        column = MCPServer.__table__.c.endpoint_path
        self.assertFalse(column.nullable)
        self.assertEqual(column.default.arg, "mcp")
        self.assertEqual(column.server_default.arg, "mcp")

    def test_mcp_server_response_schema_defaults(self) -> None:
        resp = MCPServerResponse(
            id=uuid.uuid4(),
            name="Server 1",
            created_at=datetime.now(timezone.utc),
        )
        self.assertEqual(resp.endpoint_path, "mcp")
        self.assertEqual(resp.model_dump()["endpoint_path"], "mcp")

    def test_mcp_server_response_schema_legacy_sse(self) -> None:
        resp = MCPServerResponse(
            id=uuid.uuid4(),
            name="Server 2",
            created_at=datetime.now(timezone.utc),
            endpoint_path="sse",
        )
        self.assertEqual(resp.endpoint_path, "sse")
        self.assertEqual(resp.model_dump()["endpoint_path"], "sse")


class MCPServerMigrationTests(unittest.TestCase):
    def test_migration_155_metadata(self) -> None:
        mig_155 = _load_migration()
        self.assertEqual(mig_155.revision, "155_mcp_server_endpoint_path")
        self.assertEqual(mig_155.down_revision, "154_vector_store_ingest_jobs")

    def test_migration_upgrade_and_downgrade(self) -> None:
        mig_155 = _load_migration()
        op = MagicMock()
        mig_155.op = op

        mig_155.upgrade()

        # Added with server_default='sse' to backfill existing rows
        added = op.add_column.call_args
        self.assertEqual(added.args[0], "mcp_servers")
        self.assertEqual(added.args[1].name, "endpoint_path")
        self.assertEqual(str(added.args[1].server_default.arg), "sse")

        # Altered with server_default='mcp' for subsequent new records
        altered = op.alter_column.call_args
        self.assertEqual(altered.args[:2], ("mcp_servers", "endpoint_path"))
        self.assertEqual(altered.kwargs["server_default"], "mcp")

        # add_column must execute before alter_column
        names = [call[0] for call in op.method_calls]
        self.assertLess(names.index("add_column"), names.index("alter_column"))

        # Downgrade drops column
        mig_155.downgrade()
        op.drop_column.assert_called_once_with("mcp_servers", "endpoint_path")
