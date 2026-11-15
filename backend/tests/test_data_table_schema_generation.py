import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.data_tables import (
    _extract_schema_payload,
    _normalize_generated_columns,
    generate_data_table_schema,
)
from app.db.models import CredentialType
from app.models.schemas import DataTableColumnDef, DataTableSchemaGenerateRequest


class NormalizeGeneratedColumnsTests(unittest.TestCase):
    def test_assigns_ids_and_sequential_order(self) -> None:
        cols = _normalize_generated_columns(
            [
                {"name": "title", "type": "string"},
                {"name": "count", "type": "number", "required": True, "unique": True},
            ],
            existing_names=set(),
        )
        self.assertEqual([c.name for c in cols], ["title", "count"])
        self.assertEqual([c.order for c in cols], [0, 1])
        self.assertTrue(all(isinstance(c.id, uuid.UUID) for c in cols))
        self.assertEqual(cols[1].type, "number")
        self.assertTrue(cols[1].required)
        self.assertTrue(cols[1].unique)

    def test_coerces_unknown_type_to_string_and_drops_blank_names(self) -> None:
        cols = _normalize_generated_columns(
            [
                {"name": "weird", "type": "timestamp"},
                {"name": "  ", "type": "string"},
                {"name": "ok", "type": "DATE"},
            ],
            existing_names=set(),
        )
        self.assertEqual([c.name for c in cols], ["weird", "ok"])
        self.assertEqual(cols[0].type, "string")
        self.assertEqual(cols[1].type, "date")

    def test_dedupes_against_existing_and_within_batch_case_insensitive(self) -> None:
        cols = _normalize_generated_columns(
            [
                {"name": "Email", "type": "string"},
                {"name": "email", "type": "string"},
                {"name": "phone", "type": "string"},
            ],
            existing_names={"EMAIL"},
        )
        self.assertEqual([c.name for c in cols], ["phone"])

    def test_non_list_input_returns_empty(self) -> None:
        self.assertEqual(_normalize_generated_columns(None, set()), [])
        self.assertEqual(_normalize_generated_columns("oops", set()), [])


class ExtractSchemaPayloadTests(unittest.TestCase):
    def test_extracts_from_fenced_block(self) -> None:
        content = 'Here you go:\n```json\n{"name": "T", "columns": []}\n```\nDone.'
        self.assertEqual(_extract_schema_payload(content), {"name": "T", "columns": []})

    def test_extracts_bare_json(self) -> None:
        self.assertEqual(_extract_schema_payload('{"name": "T"}'), {"name": "T"})

    def test_returns_none_for_unparseable(self) -> None:
        self.assertIsNone(_extract_schema_payload("no json here at all"))


def _make_request(existing=None) -> DataTableSchemaGenerateRequest:
    return DataTableSchemaGenerateRequest(
        credential_id=uuid.uuid4(),
        model="gpt-4o-mini",
        prompt="A table of books with title and page count",
        existing_columns=existing,
    )


def _execute_llm_returning(content: str) -> AsyncMock:
    return AsyncMock(return_value={"text": content})


class GenerateDataTableSchemaEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _credential(self) -> MagicMock:
        credential = MagicMock()
        credential.id = uuid.uuid4()
        credential.type = CredentialType.openai
        credential.encrypted_config = "enc"
        return credential

    async def test_returns_normalized_suggestion(self) -> None:
        content = (
            '```json\n{"name": "Books", "description": "My books", "columns": ['
            '{"name": "title", "type": "string", "required": true}, '
            '{"name": "pages", "type": "number"}]}\n```'
        )
        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self._credential()),
            ),
            patch("app.api.data_tables.decrypt_config", return_value={"api_key": "x"}),
            patch(
                "app.api.data_tables.execute_llm",
                _execute_llm_returning(content),
            ),
        ):
            result = await generate_data_table_schema(
                request=_make_request(),
                current_user=MagicMock(id=uuid.uuid4()),
                db=AsyncMock(),
            )
        self.assertEqual(result.name, "Books")
        self.assertEqual(result.description, "My books")
        self.assertEqual([c.name for c in result.columns], ["title", "pages"])
        self.assertTrue(result.columns[0].required)
        self.assertEqual(result.columns[1].type, "number")

    async def test_generate_schema_passes_trace_context_to_llm(self) -> None:
        content = '```json\n{"name": "Books", "columns": [{"name": "title"}]}\n```'
        credential = self._credential()
        user = MagicMock(id=uuid.uuid4())
        execute_llm = _execute_llm_returning(content)
        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=credential),
            ),
            patch("app.api.data_tables.decrypt_config", return_value={"api_key": "x"}),
            patch("app.api.data_tables.execute_llm", execute_llm),
        ):
            await generate_data_table_schema(
                request=_make_request(),
                current_user=user,
                db=AsyncMock(),
            )

        execute_llm.assert_awaited_once()
        kwargs = execute_llm.await_args.kwargs
        trace_context = kwargs["trace_context"]
        self.assertEqual(kwargs["model"], "gpt-4o-mini")
        self.assertEqual(kwargs["extra_body"], {"disable_reasoning": True})
        self.assertEqual(trace_context.user_id, user.id)
        self.assertEqual(trace_context.credential_id, credential.id)
        self.assertEqual(trace_context.source, "data_table_ai")
        self.assertEqual(trace_context.node_label, "AI DataTable Create")

    async def test_generate_schema_recovers_from_disable_reasoning_400(self) -> None:
        content = '```json\n{"name": "Books", "columns": [{"name": "title"}]}\n```'
        calls: list[dict] = []
        exc_400 = Exception("Error code: 400 - Unsupported parameter: disable_reasoning")
        exc_400.status_code = 400

        def create(**kwargs: object) -> SimpleNamespace:
            calls.append(dict(kwargs))
            if len(calls) == 1:
                raise exc_400
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self._credential()),
            ),
            patch("app.api.data_tables.decrypt_config", return_value={"api_key": "x"}),
            patch(
                "app.services.llm_service.LLMService._get_client",
                return_value=(client, "OpenAI"),
            ),
        ):
            result = await generate_data_table_schema(
                request=_make_request(),
                current_user=MagicMock(id=uuid.uuid4()),
                db=AsyncMock(),
            )

        self.assertEqual(result.name, "Books")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["extra_body"], {"disable_reasoning": True})
        self.assertNotIn("extra_body", calls[1])

    async def test_dedupes_against_existing_columns_in_extend_mode(self) -> None:
        existing = [DataTableColumnDef(name="title", type="string", order=0)]
        content = (
            '```json\n{"name": "X", "columns": ['
            '{"name": "Title", "type": "string"}, '
            '{"name": "isbn", "type": "string"}]}\n```'
        )
        execute_llm = _execute_llm_returning(content)
        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self._credential()),
            ),
            patch("app.api.data_tables.decrypt_config", return_value={"api_key": "x"}),
            patch("app.api.data_tables.execute_llm", execute_llm),
        ):
            result = await generate_data_table_schema(
                request=_make_request(existing=existing),
                current_user=MagicMock(id=uuid.uuid4()),
                db=AsyncMock(),
            )
        self.assertEqual([c.name for c in result.columns], ["isbn"])
        self.assertEqual(
            execute_llm.await_args.kwargs["trace_context"].node_label,
            "AI DataTable Extend",
        )

    async def test_missing_credential_returns_400(self) -> None:
        with patch(
            "app.api.ai_assistant.get_credential_for_user",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await generate_data_table_schema(
                    request=_make_request(),
                    current_user=MagicMock(id=uuid.uuid4()),
                    db=AsyncMock(),
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_unparseable_output_returns_422(self) -> None:
        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self._credential()),
            ),
            patch("app.api.data_tables.decrypt_config", return_value={"api_key": "x"}),
            patch(
                "app.api.data_tables.execute_llm",
                _execute_llm_returning("no json here"),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await generate_data_table_schema(
                    request=_make_request(),
                    current_user=MagicMock(id=uuid.uuid4()),
                    db=AsyncMock(),
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_no_usable_columns_returns_422(self) -> None:
        content = '```json\n{"name": "Empty", "columns": []}\n```'
        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self._credential()),
            ),
            patch("app.api.data_tables.decrypt_config", return_value={"api_key": "x"}),
            patch(
                "app.api.data_tables.execute_llm",
                _execute_llm_returning(content),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await generate_data_table_schema(
                    request=_make_request(),
                    current_user=MagicMock(id=uuid.uuid4()),
                    db=AsyncMock(),
                )
        self.assertEqual(ctx.exception.status_code, 422)
