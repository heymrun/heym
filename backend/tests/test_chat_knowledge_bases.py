"""Knowledge bases in chat: listing, documents and search go through the vector store routes."""

import json
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, status

from app.api import ai_assistant
from app.api import chat_knowledge_bases as chat
from app.db.models import Credential, CredentialType, VectorStore
from app.models.schemas import (
    VectorStoreItemsResponse,
    VectorStoreSearchResponse,
    VectorStoreSearchResult,
    VectorStoreSourceGroup,
)
from app.services.heym_agent import profile
from app.services.vector_store import VectorStoreSourceGroup as ServiceSourceGroup

UPDATED = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _row(name: str, description: str | None = None, grant: str = "owner") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), name=name, description=description, updated_at=UPDATED, grant=grant
    )


def _rows_result(rows: list[SimpleNamespace]) -> MagicMock:
    return MagicMock(all=MagicMock(return_value=rows))


def _hit(text: str, score: float, source: str | None = "refunds.pdf", **metadata: object):
    return VectorStoreSearchResult(
        id=str(uuid.uuid4()),
        text=text,
        score=score,
        source=source,
        metadata={"source": source, "text": text, **metadata},
    )


class KnowledgeBaseListTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.db = MagicMock()
        self.db.execute = AsyncMock()

    async def test_lists_reachable_stores_from_the_shared_access_rows(self) -> None:
        policies = _row("Policies", "Refund and returns policy", "shared")
        notes = _row("Notes")
        self.db.execute.return_value = _rows_result([policies, notes])

        with patch.object(
            chat, "vector_store_access_rows", wraps=chat.vector_store_access_rows
        ) as access:
            result = await chat.call_knowledge_base_tool(
                self.db, self.user, "list_knowledge_bases", {}
            )

        access.assert_called_once_with(self.user.id)
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            result["knowledge_bases"][0],
            {
                "id": str(policies.id),
                "name": "Policies",
                "description": "Refund and returns policy",
                "access": "shared",
                "updated_at": UPDATED.isoformat(),
            },
        )
        self.assertIsNone(result["knowledge_bases"][1]["description"])
        self.assertNotIn("status", result)

    async def test_ids_narrow_the_query(self) -> None:
        self.db.execute.return_value = _rows_result([])
        wanted = uuid.uuid4()

        await chat.list_accessible_knowledge_bases(self.db, self.user.id, ids=[wanted])

        statement = self.db.execute.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("vector_stores.id IN", compiled)
        self.assertIn(wanted.hex, compiled.replace("-", ""))

    async def test_an_empty_id_list_matches_nothing_without_a_query(self) -> None:
        self.assertEqual(await chat.list_accessible_knowledge_bases(self.db, self.user.id, []), [])
        self.db.execute.assert_not_awaited()


class KnowledgeBasePromptBlockTests(unittest.TestCase):
    def _bases(self, count: int, description: str | None = "About things") -> list:
        return [
            chat.KnowledgeBase(uuid.uuid4(), f"Store {i}", description, "owner", UPDATED)
            for i in range(count)
        ]

    def test_lists_name_id_and_description(self) -> None:
        bases = self._bases(1)

        block = chat.format_knowledge_bases_for_prompt(bases)

        self.assertTrue(block.startswith("\n\nKnowledge bases ("))
        self.assertIn(f"- Store 0 (id {bases[0].id}): About things", block)

    def test_no_knowledge_bases_adds_no_block(self) -> None:
        self.assertEqual(chat.format_knowledge_bases_for_prompt([]), "")

    def test_a_store_without_description_lists_name_and_id(self) -> None:
        bases = self._bases(1, description=None)

        block = chat.format_knowledge_bases_for_prompt(bases)

        self.assertIn(f"- Store 0 (id {bases[0].id})\n", block + "\n")

    def test_caps_at_fifty_and_points_at_the_list_tool(self) -> None:
        block = chat.format_knowledge_bases_for_prompt(self._bases(53))

        self.assertIn("Store 49", block)
        self.assertNotIn("Store 50", block)
        self.assertIn("3 more", block)
        self.assertIn("list_knowledge_bases", block.splitlines()[-1])

    def test_long_descriptions_are_cut_and_newlines_flattened(self) -> None:
        bases = self._bases(1, description="line one\n\n- injected bullet " + "x" * 400)

        block = chat.format_knowledge_bases_for_prompt(bases)
        entry = block.splitlines()[-1]

        self.assertEqual(len(block.splitlines()), 4)
        self.assertIn("line one - injected bullet", entry)
        self.assertLessEqual(len(entry.split("): ", 1)[1]), chat.PROMPT_DESCRIPTION_CHARS + 1)

    def test_prompt_block_reads_the_user_s_stores(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock(return_value=_rows_result([_row("Handbook", "HR handbook")]))
        user_id = uuid.uuid4()

        import asyncio

        block = asyncio.run(chat.knowledge_bases_prompt_block(db, user_id))

        self.assertIn("Handbook", block)
        self.assertIn("HR handbook", block)


class KnowledgeBaseDocumentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.store = _row("Policies", "Company policies")
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=_rows_result([self.store]))

    async def _documents(self, groups: list[VectorStoreSourceGroup], total: int) -> dict:
        items = AsyncMock(return_value=VectorStoreItemsResponse(sources=groups, total_items=total))
        with patch.object(chat.vector_stores_api, "list_vector_store_items", items):
            result = await chat.call_knowledge_base_tool(
                self.db,
                self.user,
                "list_knowledge_bases",
                {"knowledge_base_id": str(self.store.id)},
            )
        self.items = items
        return result

    async def test_lists_the_documents_of_one_store(self) -> None:
        result = await self._documents(
            [
                VectorStoreSourceGroup(source="", chunk_count=2),
                VectorStoreSourceGroup(source="refunds.pdf", file_size=2048, chunk_count=7),
            ],
            total=9,
        )

        self.items.assert_awaited_once_with(
            self.store.id,
            limit=1000,
            text_truncate_length=0,
            current_user=self.user,
            db=self.db,
        )
        self.assertEqual(result["knowledge_base"]["name"], "Policies")
        self.assertEqual(result["total_chunks"], 9)
        self.assertEqual(
            result["documents"],
            [
                {"source": None, "file_size": None, "chunk_count": 2},
                {"source": "refunds.pdf", "file_size": 2048, "chunk_count": 7},
            ],
        )
        self.assertEqual(result["more_documents"], 0)

    async def test_caps_the_document_list(self) -> None:
        groups = [
            VectorStoreSourceGroup(source=f"doc-{i}.md", chunk_count=1)
            for i in range(chat.MAX_DOCUMENTS + 5)
        ]

        result = await self._documents(groups, total=len(groups))

        self.assertEqual(len(result["documents"]), chat.MAX_DOCUMENTS)
        self.assertEqual(result["more_documents"], 5)

    async def test_an_unreachable_store_errors_without_reading_it(self) -> None:
        self.db.execute.return_value = _rows_result([])

        result = await self._documents([], total=0)

        self.assertEqual(result, {"error": "Knowledge base not found"})
        self.items.assert_not_awaited()

    async def test_reads_documents_through_the_items_route(self) -> None:
        store = VectorStore(
            id=self.store.id,
            name="Policies",
            collection_name="policies",
            owner_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
        )
        credential = Credential(
            id=store.credential_id,
            owner_id=store.owner_id,
            name="Qdrant",
            type=CredentialType.qdrant,
            encrypted_config="encrypted",
        )
        self.db.execute.side_effect = [
            _rows_result([self.store]),
            MagicMock(scalar_one_or_none=MagicMock(return_value=credential)),
        ]
        service = MagicMock()
        service.list_items.return_value = (
            [ServiceSourceGroup(source="handbook.pdf", file_size=10, chunk_count=3, items=[])],
            3,
        )

        with (
            patch(
                "app.api.vector_stores.get_vector_store_with_permission",
                AsyncMock(return_value=(store, "read")),
            ),
            patch("app.api.vector_stores.decrypt_config", return_value={"url": "q"}),
            patch(
                "app.api.vector_stores.get_vector_store_service_from_config",
                return_value=service,
            ),
        ):
            result = await chat.call_knowledge_base_tool(
                self.db,
                self.user,
                "list_knowledge_bases",
                {"knowledge_base_id": str(self.store.id)},
            )

        service.list_items.assert_called_once_with("policies", limit=1000, text_truncate_length=0)
        self.assertEqual(result["documents"][0]["source"], "handbook.pdf")
        self.assertEqual(result["total_chunks"], 3)


class KnowledgeBaseSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.policies = _row("Policies")
        self.handbook = _row("Handbook", grant="shared")
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=_rows_result([self.policies, self.handbook]))

    async def _search(self, search: AsyncMock, **arguments: object) -> dict:
        with patch.object(chat.vector_stores_api, "search_vector_store", search):
            return await chat.call_knowledge_base_tool(
                self.db, self.user, "search_knowledge_base", arguments
            )

    async def test_searches_each_store_through_the_search_route(self) -> None:
        responses = {
            self.policies.id: VectorStoreSearchResponse(
                results=[_hit("Refunds within 30 days.", 0.912345, page=2)]
            ),
            self.handbook.id: VectorStoreSearchResponse(
                results=[_hit("Ask HR for refunds.", 0.5, source="handbook.md")]
            ),
        }

        async def answer(store_id, body, *, current_user, db):
            self.assertIs(current_user, self.user)
            self.assertIs(db, self.db)
            self.assertEqual((body.query, body.limit), ("refund window", 3))
            return responses[store_id]

        search = AsyncMock(side_effect=answer)

        result = await self._search(
            search,
            query="refund window",
            knowledge_base_ids=[str(self.policies.id), str(self.handbook.id)],
            limit=3,
        )

        self.assertEqual(search.await_count, 2)
        self.assertEqual(
            [group["knowledge_base_name"] for group in result["knowledge_bases"]],
            ["Policies", "Handbook"],
        )
        first = result["knowledge_bases"][0]["results"][0]
        self.assertEqual(
            first,
            {
                "source": "refunds.pdf",
                "score": 0.9123,
                "text": "Refunds within 30 days.",
                "metadata": {"page": 2},
            },
        )
        self.assertEqual(result["errors"], [])
        self.assertNotIn("error", result)
        self.assertNotIn("status", result)

    async def test_repeated_ids_are_searched_once(self) -> None:
        search = AsyncMock(return_value=VectorStoreSearchResponse(results=[]))

        await self._search(
            search,
            query="refund",
            knowledge_base_ids=[str(self.policies.id), str(self.policies.id)],
        )

        self.assertEqual(search.await_count, 1)
        self.assertEqual(search.await_args.args[1].limit, 5)

    async def test_one_failing_store_does_not_hide_the_others(self) -> None:
        async def answer(store_id, body, *, current_user, db):
            if store_id == self.handbook.id:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="The vector store could not be searched.",
                )
            return VectorStoreSearchResponse(results=[_hit("Refunds within 30 days.", 0.9)])

        result = await self._search(
            AsyncMock(side_effect=answer),
            query="refund",
            knowledge_base_ids=[str(self.policies.id), str(self.handbook.id)],
        )

        self.assertEqual(len(result["knowledge_bases"]), 1)
        self.assertEqual(
            result["errors"],
            [
                {
                    "knowledge_base_id": str(self.handbook.id),
                    "knowledge_base_name": "Handbook",
                    "error": "The vector store could not be searched.",
                }
            ],
        )
        self.assertNotIn("error", result)

    async def test_an_unreachable_store_is_reported_and_never_searched(self) -> None:
        self.db.execute.return_value = _rows_result([])
        search = AsyncMock()
        hidden = uuid.uuid4()

        result = await self._search(search, query="refund", knowledge_base_ids=[str(hidden)])

        search.assert_not_awaited()
        self.assertEqual(
            result["errors"],
            [{"knowledge_base_id": str(hidden), "error": "Knowledge base not found"}],
        )
        self.assertEqual(result["error"], "Knowledge base not found")

    async def test_long_chunks_are_cut_and_metadata_stays_small(self) -> None:
        metadata = {f"key_{i}": i for i in range(15)}
        metadata.update(nested={"a": 1}, note="n" * 500)
        long_hit = _hit("x" * 5000, 0.7, **metadata)
        search = AsyncMock(return_value=VectorStoreSearchResponse(results=[long_hit]))

        result = await self._search(
            search, query="refund", knowledge_base_ids=[str(self.policies.id)]
        )

        chunk = result["knowledge_bases"][0]["results"][0]
        self.assertLessEqual(len(chunk["text"]), chat.MAX_CHUNK_CHARS + 1)
        self.assertTrue(chunk["text"].endswith("…"))
        self.assertEqual(len(chunk["metadata"]), chat.MAX_METADATA_KEYS)
        self.assertNotIn("nested", chunk["metadata"])
        self.assertNotIn("text", chunk["metadata"])
        self.assertNotIn("source", chunk["metadata"])

    async def test_invalid_arguments_return_an_error(self) -> None:
        search = AsyncMock()
        cases = [
            {"query": "", "knowledge_base_ids": [str(self.policies.id)]},
            {"query": "refund", "knowledge_base_ids": []},
            {"query": "refund", "knowledge_base_ids": [str(uuid.uuid4()) for _ in range(6)]},
            {"query": "refund", "knowledge_base_ids": ["not-a-uuid"]},
            {"query": "refund", "knowledge_base_ids": [str(self.policies.id)], "limit": 11},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = await self._search(search, **arguments)
                self.assertIn("error", result)
        search.assert_not_awaited()


class KnowledgeBaseSummaryTests(unittest.TestCase):
    def test_summaries_carry_counts_never_chunk_text(self) -> None:
        search_result = {
            "query": "refund",
            "knowledge_bases": [
                {"results": [{"text": "SECRET CHUNK"}, {"text": "other"}]},
                {"results": []},
            ],
            "errors": [{"error": "x"}],
        }

        summary = chat.summarize_knowledge_base_tool("search_knowledge_base", search_result)

        self.assertEqual(
            summary, "Found 2 chunk(s) in 2 knowledge base(s); 1 could not be searched"
        )
        self.assertNotIn("SECRET", summary)
        via_chat = ai_assistant._summarize_tool_result(
            "search_knowledge_base", json.dumps(search_result)
        )
        self.assertEqual(via_chat, summary)

    def test_list_and_document_summaries(self) -> None:
        self.assertEqual(
            chat.summarize_knowledge_base_tool("list_knowledge_bases", {"count": 3}),
            "3 knowledge base(s) listed",
        )
        self.assertEqual(
            chat.summarize_knowledge_base_tool(
                "list_knowledge_bases", {"documents": [{}, {}], "more_documents": 4}
            ),
            "6 document(s) listed",
        )
        self.assertEqual(
            chat.summarize_knowledge_base_tool("search_knowledge_base", {"error": "nope"}),
            "Error: nope",
        )

    def test_labels(self) -> None:
        self.assertEqual(
            chat.knowledge_base_tool_label("search_knowledge_base"), "Searching knowledge bases..."
        )
        self.assertEqual(
            chat.knowledge_base_tool_label("list_knowledge_bases"), "Listing knowledge bases..."
        )


class ChatWiringTests(unittest.TestCase):
    def test_tools_are_offered_to_every_dashboard_chat_turn(self) -> None:
        names = {tool["function"]["name"] for tool in ai_assistant.DASHBOARD_CHAT_TOOLS}

        self.assertLessEqual(chat.KNOWLEDGE_BASE_TOOL_NAMES, names)

    def test_schemas_are_plain_function_tools(self) -> None:
        for schema in chat.KNOWLEDGE_BASE_TOOL_SCHEMAS:
            with self.subTest(tool=schema["function"]["name"]):
                self.assertEqual(schema["type"], "function")
                self.assertEqual(schema["function"]["parameters"]["type"], "object")
                self.assertNotIn("anyOf", json.dumps(schema))

    def test_prompt_makes_information_questions_knowledge_first(self) -> None:
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        workflow_first = prompt.split("CRITICAL - Workflow-first behavior:", 1)[1][:700]

        self.assertIn(chat.KNOWLEDGE_BASE_PROMPT, prompt)
        self.assertIn("search_knowledge_base", workflow_first)
        self.assertIn("search what is in them", prompt)

    def test_agent_profile_describes_knowledge_bases(self) -> None:
        self.assertIn("knowledge bases", profile.AGENT_CAPABILITIES)
        self.assertIn(profile.AGENT_CAPABILITIES, profile.MCP_TOOL_DESCRIPTION)
        skill = next(s for s in profile.AGENT_SKILLS if s.id == "knowledge-bases")
        self.assertTrue(skill.examples)


class ChatLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_search_call_runs_in_the_chat_loop_and_reaches_the_model(self) -> None:
        store_id = str(uuid.uuid4())
        tool_call = MagicMock()
        tool_call.id = "call-1"
        tool_call.function.name = "search_knowledge_base"
        tool_call.function.arguments = json.dumps(
            {"query": "refund window", "knowledge_base_ids": [store_id]}
        )
        usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        first = MagicMock(
            choices=[MagicMock(message=MagicMock(content=None, tool_calls=[tool_call]))],
            usage=usage,
        )
        final = MagicMock(
            choices=[MagicMock(message=MagicMock(content="30 days.", tool_calls=None))],
            usage=usage,
        )
        client = MagicMock()
        client.chat.completions.create.side_effect = [first, final]
        tool_result = {
            "query": "refund window",
            "knowledge_bases": [
                {
                    "knowledge_base_id": store_id,
                    "knowledge_base_name": "Policies",
                    "results": [{"source": "refunds.pdf", "score": 0.9, "text": "CHUNK TEXT"}],
                }
            ],
            "errors": [],
        }
        call = AsyncMock(return_value=tool_result)
        user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()

        with (
            patch.object(ai_assistant, "call_knowledge_base_tool", call),
            patch.object(ai_assistant, "record_llm_trace"),
            patch.object(ai_assistant, "record_run_history"),
        ):
            events = [
                chunk
                async for chunk in ai_assistant.stream_dashboard_chat(
                    client,
                    "gpt-4o-mini",
                    "system",
                    [{"role": "user", "content": "What is our refund window?"}],
                    db,
                    user,
                    "OpenAI",
                    "http://localhost",
                )
            ]

        call.assert_awaited_once_with(
            db,
            user,
            "search_knowledge_base",
            {"query": "refund window", "knowledge_base_ids": [store_id]},
        )
        payloads = [
            json.loads(event.removeprefix("data: ").strip())
            for event in events
            if event.startswith("data: {")
        ]
        start = next(p for p in payloads if p.get("type") == "tool_start")
        end = next(p for p in payloads if p.get("type") == "tool_end")
        self.assertEqual(start["label"], "Searching knowledge bases...")
        self.assertIn("Found 1 chunk(s) in 1 knowledge base(s)", json.dumps(end))
        self.assertNotIn("CHUNK TEXT", json.dumps(end))
        second_request = client.chat.completions.create.call_args_list[1].kwargs["messages"]
        tool_message = next(m for m in second_request if m["role"] == "tool")
        self.assertIn("CHUNK TEXT", tool_message["content"])


class SystemPromptBlockTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_turns_list_knowledge_bases_after_the_workflows(self) -> None:
        from app.api import chats
        from app.services.credential_catalog import CredentialPromptMode

        user = SimpleNamespace(id=uuid.uuid4(), user_rules="")
        workflows = [{"id": str(uuid.uuid4()), "name": "Weather", "description": "", "inputs": []}]
        block = "\n\nKnowledge bases (BLOCK):\n- Policies"
        with (
            patch.object(
                chats, "get_workflows_for_user_with_inputs", AsyncMock(return_value=workflows)
            ),
            patch.object(chats, "_load_agents_md_content", return_value=""),
            patch.object(
                chats, "build_credentials_prompt", AsyncMock(return_value="\n\n## Credentials")
            ),
            patch.object(chats, "knowledge_bases_prompt_block", AsyncMock(return_value=block)),
        ):
            parts = await chats._assemble_system_prompt_parts(
                user,
                AsyncMock(),
                include_attachment_instructions=False,
                credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            )

        prompt = parts.full_system_prompt
        self.assertEqual(parts.knowledge_bases_block, block)
        self.assertLess(prompt.index("Available workflows"), prompt.index(block))
        self.assertLess(prompt.index(block), prompt.index("## Credentials"))


if __name__ == "__main__":
    unittest.main()
