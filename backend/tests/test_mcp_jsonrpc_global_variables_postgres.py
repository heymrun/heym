"""MCP JSON-RPC tools/call (/api/mcp) reads and writes global variables, as REST does."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import mcp
from app.db.models import ExecutionHistory, GlobalVariable, User, Workflow
from tests.board_pg_support import connect_or_skip, make_user

TOOL = "greet_and_count"


def _jsonrpc_request(tool: str) -> MagicMock:
    request = MagicMock()
    request.json = AsyncMock(
        return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {}},
        }
    )
    return request


class McpJsonRpcGlobalVariablesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = await connect_or_skip(self)
        self.owner = await make_user(self.engine, "mcp-globals")
        nodes = [
            {"id": "in", "type": "textInput", "data": {"label": "userInput"}},
            {
                "id": "v",
                "type": "variable",
                "data": {
                    "label": "lastCaller",
                    "variableName": "last_caller",
                    "variableValue": "mcp-client",
                    "variableType": "string",
                    "isGlobal": True,
                },
            },
            {
                "id": "out",
                "type": "output",
                "data": {"label": "greeting", "message": "$global.greeting"},
            },
        ]
        edges = [
            {"id": "e1", "source": "in", "target": "v"},
            {"id": "e2", "source": "v", "target": "out"},
        ]
        async with AsyncSession(self.engine) as db:
            db.add(
                Workflow(
                    name=TOOL, owner_id=self.owner.id, nodes=nodes, edges=edges, mcp_enabled=True
                )
            )
            db.add(
                GlobalVariable(
                    owner_id=self.owner.id,
                    name="greeting",
                    value={"v": "Bonjour"},
                    value_type="string",
                )
            )
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            ids = (
                (await db.execute(select(Workflow.id).where(Workflow.owner_id == self.owner.id)))
                .scalars()
                .all()
            )
            if ids:
                await db.execute(
                    delete(ExecutionHistory).where(ExecutionHistory.workflow_id.in_(ids))
                )
            await db.execute(delete(Workflow).where(Workflow.owner_id == self.owner.id))
            await db.execute(delete(GlobalVariable).where(GlobalVariable.owner_id == self.owner.id))
            await db.execute(delete(User).where(User.id == self.owner.id))
            await db.commit()
        await self.engine.dispose()

    async def test_tools_call_reads_and_writes_global_variables(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            answer = await mcp._dispatch_mcp_jsonrpc(_jsonrpc_request(TOOL), self.owner, db)
            await db.commit()

        self.assertFalse(answer["result"].get("isError"))
        self.assertEqual(
            json.loads(answer["result"]["content"][0]["text"]),
            {"greeting": {"result": "Bonjour"}},
        )
        async with AsyncSession(self.engine) as db:
            written = (
                await db.execute(
                    select(GlobalVariable).where(
                        GlobalVariable.owner_id == self.owner.id,
                        GlobalVariable.name == "last_caller",
                    )
                )
            ).scalar_one_or_none()
        self.assertIsNotNone(written)
        self.assertEqual(written.value, {"v": "mcp-client"})


if __name__ == "__main__":
    unittest.main()
