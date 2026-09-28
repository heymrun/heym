"""The chat's data table tools: list the user's tables, and create one through the router."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import ai_assistant
from app.services.data_table_catalog import CatalogColumn, CatalogDataTable


def _tool(name: str) -> dict:
    return next(
        item for item in ai_assistant.DASHBOARD_CHAT_TOOLS if item["function"]["name"] == name
    )


class DataTableToolsRegisteredTests(unittest.TestCase):
    def test_tools_are_offered_to_the_chat(self) -> None:
        names = {item["function"]["name"] for item in ai_assistant.DASHBOARD_CHAT_TOOLS}

        self.assertIn("list_data_tables", names)
        self.assertIn("create_data_table", names)

    def test_create_tool_takes_a_name_and_typed_columns(self) -> None:
        parameters = _tool("create_data_table")["function"]["parameters"]

        self.assertEqual(parameters["required"], ["name", "columns"])
        column = parameters["properties"]["columns"]["items"]
        self.assertEqual(
            column["properties"]["type"]["enum"], ["string", "number", "boolean", "date", "json"]
        )

    def test_prompt_lists_tables_asks_when_ambiguous_and_never_touches_rows(self) -> None:
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT

        self.assertIn("Call list_data_tables when", prompt)
        self.assertIn("Never read or write rows yourself", prompt)
        self.assertIn("one createTable option", prompt)
        self.assertIn('`Created data table "<name>" (id <id>)` means the table exists', prompt)
        self.assertIn("(8) I can list your data tables and their columns", prompt)


class ListDataTablesForChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_catalog_payload(self) -> None:
        table = CatalogDataTable(
            uuid.uuid4(), "leads", None, "owner", None, (CatalogColumn("email", "string"),)
        )
        db = AsyncMock()
        user_id = uuid.uuid4()

        with patch.object(
            ai_assistant, "load_data_table_catalog", AsyncMock(return_value=[table])
        ) as load:
            result = await ai_assistant.list_data_tables_for_chat(db, user_id)

        load.assert_awaited_once_with(db, user_id)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["tables"][0]["columns"][0]["name"], "email")


class CreateDataTableForChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.db = AsyncMock()

    async def _create(self, route: AsyncMock, **overrides: object) -> dict:
        arguments: dict[str, object] = {
            "name": "leads",
            "description": "Website leads",
            "columns": [
                {"name": "email", "type": "string", "unique": True},
                {"name": "score", "type": "Number"},
            ],
        }
        arguments.update(overrides)
        with patch.object(ai_assistant, "create_data_table_route", route):
            return await ai_assistant.create_data_table_for_chat(self.db, self.user, **arguments)

    async def test_creates_through_the_router_and_returns_the_table(self) -> None:
        table_id = uuid.uuid4()
        route = AsyncMock(
            return_value=SimpleNamespace(
                id=table_id,
                name="leads",
                description="Website leads",
                columns=[
                    {"name": "email", "type": "string", "unique": True, "order": 0},
                    {"name": "score", "type": "number", "order": 1},
                ],
            )
        )

        result = await self._create(route)

        self.assertTrue(result["created"])
        self.assertEqual(result["table"]["id"], str(table_id))
        self.assertEqual(result["table"]["access"], "owner")
        payload = route.await_args.args[0]
        self.assertEqual([column.name for column in payload.columns], ["email", "score"])
        self.assertEqual(payload.columns[1].type, "number")
        self.assertTrue(payload.columns[0].unique)
        self.assertEqual(route.await_args.kwargs, {"current_user": self.user, "db": self.db})

    async def test_router_errors_come_back_as_tool_errors(self) -> None:
        route = AsyncMock(
            side_effect=HTTPException(
                status_code=400, detail="Data table with this name already exists"
            )
        )

        result = await self._create(route)

        self.assertEqual(result, {"error": "Data table with this name already exists"})

    async def test_bad_columns_are_refused_before_the_router(self) -> None:
        route = AsyncMock()
        cases = {
            "At least one column is required": [],
            "Duplicate column name: Email": [
                {"name": "email", "type": "string"},
                {"name": "Email", "type": "string"},
            ],
            "Unknown column type for email: text": [{"name": "email", "type": "text"}],
            "Each column needs a name": [{"name": " ", "type": "string"}],
        }

        for message, columns in cases.items():
            result = await self._create(route, columns=columns)
            self.assertIn(message, result["error"])
        route.assert_not_awaited()

    async def test_a_blank_name_is_refused(self) -> None:
        route = AsyncMock()

        result = await self._create(route, name="  ")

        self.assertEqual(result, {"error": "Table name is required"})
        route.assert_not_awaited()


class DataTableToolDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def _stream(
        self, tool_name: str, arguments: dict, target: str, result: dict
    ) -> tuple[AsyncMock, list[str]]:
        user = MagicMock()
        user.id = uuid.uuid4()
        tool_call = MagicMock()
        tool_call.id = "call-1"
        tool_call.function.name = tool_name
        tool_call.function.arguments = json.dumps(arguments)
        tool_message = MagicMock(content=None)
        tool_message.tool_calls = [tool_call]
        final_message = MagicMock(content="Done.", tool_calls=None)
        usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=tool_message)], usage=usage),
            MagicMock(choices=[MagicMock(message=final_message)], usage=usage),
        ]
        handler = AsyncMock(return_value=result)

        with patch("app.api.ai_assistant.record_run_history"), patch(target, handler):
            chunks = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "save my leads in a table"}],
                    AsyncMock(),
                    user,
                    "OpenAI",
                    "http://localhost",
                )
            ]
        return handler, chunks

    async def test_create_data_table_call_reaches_the_helper(self) -> None:
        arguments = {"name": "leads", "columns": [{"name": "email", "type": "string"}]}

        handler, chunks = await self._stream(
            "create_data_table",
            arguments,
            "app.api.ai_assistant.create_data_table_for_chat",
            {"created": True, "table": {"name": "leads", "columns": [{"name": "email"}]}},
        )

        kwargs = handler.await_args.kwargs
        self.assertEqual(kwargs["name"], "leads")
        self.assertEqual(kwargs["columns"], arguments["columns"])
        self.assertTrue(any('"label": "Creating data table..."' in chunk for chunk in chunks))
        self.assertTrue(
            any("Created data table 'leads' with 1 column(s)" in chunk for chunk in chunks)
        )

    async def test_list_data_tables_call_reaches_the_helper(self) -> None:
        handler, chunks = await self._stream(
            "list_data_tables",
            {},
            "app.api.ai_assistant.list_data_tables_for_chat",
            {"count": 2, "tables": [], "truncated": False},
        )

        handler.assert_awaited_once()
        self.assertTrue(any("2 data table(s) listed" in chunk for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
