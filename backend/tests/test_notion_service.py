"""Unit and executor tests for the Notion integration."""

import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.notion_service import NotionService


def _response(
    payload: dict,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    response = MagicMock()
    response.is_success = 200 <= status_code < 300
    response.status_code = status_code
    response.headers = headers or {}
    response.text = str(payload)
    response.json.return_value = payload
    return response


class NotionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = NotionService({"api_token": "secret_test_token"})

    def tearDown(self) -> None:
        self.service.close()
        NotionService.close_shared_client()

    def test_requires_api_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "api_token"):
            NotionService({})

    def test_resolve_bearer_token_prefers_oauth_access_token(self) -> None:
        token = NotionService.resolve_bearer_token(
            {"auth_mode": "oauth", "access_token": "oauth-token", "api_token": "ntn_token"}
        )
        self.assertEqual(token, "oauth-token")

    def test_resolve_bearer_token_falls_back_to_access_token_for_token_mode(self) -> None:
        token = NotionService.resolve_bearer_token({"access_token": "oauth-token"})
        self.assertEqual(token, "oauth-token")

    def test_connection_uses_current_notion_version(self) -> None:
        with patch("httpx.Client.request", return_value=_response({"id": "bot"})) as request:
            result = self.service.test_connection()
        self.assertEqual(result["id"], "bot")
        self.assertEqual(request.call_args.args[:2], ("GET", "https://api.notion.com/v1/users/me"))
        self.assertEqual(
            request.call_args.kwargs["headers"]["Notion-Version"],
            NotionService.API_VERSION,
        )

    def test_search_builds_payload(self) -> None:
        with patch(
            "httpx.Client.request",
            return_value=_response(
                {"results": [{"id": "page-1"}], "has_more": False, "next_cursor": None}
            ),
        ) as request:
            result = self.service.search(
                query="Roadmap",
                filter_object={"property": "object", "value": "page"},
                sort={"direction": "descending", "timestamp": "last_edited_time"},
                page_size=50,
                start_cursor="cursor-1",
            )
        payload = request.call_args.kwargs["json"]
        self.assertEqual(payload["query"], "Roadmap")
        self.assertEqual(payload["page_size"], 50)
        self.assertEqual(payload["start_cursor"], "cursor-1")
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["success"])

    def test_search_fetch_all_follows_cursor(self) -> None:
        responses = [
            _response({"results": [{"id": "1"}], "has_more": True, "next_cursor": "next"}),
            _response({"results": [{"id": "2"}], "has_more": False, "next_cursor": None}),
        ]
        with patch("httpx.Client.request", side_effect=responses) as request:
            result = self.service.search(fetch_all=True)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].kwargs["json"]["start_cursor"], "next")
        self.assertEqual([item["id"] for item in result["results"]], ["1", "2"])

    def test_list_data_sources_returns_editor_options(self) -> None:
        with patch.object(
            self.service,
            "search",
            return_value={
                "results": [
                    {
                        "object": "data_source",
                        "id": "ds-1",
                        "title": [{"plain_text": "Tasks"}],
                        "url": "https://notion.so/tasks",
                    },
                    {"object": "page", "id": "page-1"},
                ]
            },
        ) as search:
            result = self.service.list_data_sources("Task")
        search.assert_called_once_with(
            query="Task",
            filter_object={"property": "object", "value": "data_source"},
            page_size=50,
            start_cursor=None,
            fetch_all=False,
        )
        self.assertEqual(
            result["data_sources"],
            [{"id": "ds-1", "title": "Tasks", "url": "https://notion.so/tasks"}],
        )

    def test_list_pages_returns_editor_options(self) -> None:
        with patch.object(
            self.service,
            "search",
            return_value={
                "results": [
                    {
                        "object": "page",
                        "id": "page-1",
                        "properties": {
                            "Name": {
                                "type": "title",
                                "title": [{"plain_text": "Project Home"}],
                            }
                        },
                        "url": "https://notion.so/home",
                    }
                ]
            },
        ):
            result = self.service.list_pages("Project")
        self.assertEqual(result["pages"][0]["title"], "Project Home")

    def test_discovery_returns_pagination_metadata(self) -> None:
        with patch.object(
            self.service,
            "search",
            return_value={
                "results": [],
                "has_more": True,
                "next_cursor": "cursor-2",
            },
        ) as search:
            result = self.service.list_pages(
                "Project",
                start_cursor="cursor-1",
                page_size=25,
            )
        search.assert_called_once_with(
            query="Project",
            filter_object={"property": "object", "value": "page"},
            page_size=25,
            start_cursor="cursor-1",
            fetch_all=False,
        )
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_cursor"], "cursor-2")

    def test_search_normalizes_legacy_database_filter(self) -> None:
        with patch(
            "httpx.Client.request",
            return_value=_response({"results": [], "has_more": False}),
        ) as request:
            self.service.search(filter_object={"property": "object", "value": "database"})
        self.assertEqual(
            request.call_args.kwargs["json"]["filter"],
            {"property": "object", "value": "data_source"},
        )

    def test_create_page_uses_data_source_parent(self) -> None:
        with patch(
            "httpx.Client.request",
            return_value=_response({"id": "page-1", "url": "https://notion.so/page"}),
        ) as request:
            result = self.service.create_page(
                data_source_id="ds-1",
                properties={"Name": {"title": [{"text": {"content": "Task"}}]}},
                children=[{"object": "block", "type": "paragraph", "paragraph": {}}],
            )
        payload = request.call_args.kwargs["json"]
        self.assertEqual(
            payload["parent"],
            {"type": "data_source_id", "data_source_id": "ds-1"},
        )
        self.assertEqual(result["id"], "page-1")

    def test_create_page_requires_parent(self) -> None:
        with self.assertRaisesRegex(ValueError, "data_source_id or parent_page_id"):
            self.service.create_page(properties={"title": {}})

    def test_create_page_batches_more_than_100_children(self) -> None:
        children = [
            {"object": "block", "type": "paragraph", "index": index} for index in range(150)
        ]
        responses = [
            _response({"id": "page-1", "url": "https://notion.so/page"}),
            _response({"results": [{"id": f"created-{index}"} for index in range(100, 150)]}),
        ]
        with patch("httpx.Client.request", side_effect=responses) as request:
            result = self.service.create_page(
                data_source_id="ds-1",
                properties={"Name": {"title": []}},
                children=children,
            )
        self.assertEqual(result["id"], "page-1")
        self.assertEqual(len(request.call_args_list[0].kwargs["json"]["children"]), 100)
        self.assertEqual(len(request.call_args_list[1].kwargs["json"]["children"]), 50)
        self.assertEqual(
            request.call_args_list[1].kwargs["json"]["position"],
            {"type": "end"},
        )

    def test_retrieve_data_source_returns_property_schema(self) -> None:
        with patch(
            "httpx.Client.request",
            return_value=_response(
                {
                    "id": "ds-1",
                    "properties": {"Name": {"type": "title"}},
                }
            ),
        ) as request:
            result = self.service.retrieve_data_source("ds-1")
        self.assertEqual(
            request.call_args.args[:2],
            ("GET", "https://api.notion.com/v1/data_sources/ds-1"),
        )
        self.assertEqual(result["data_source"]["properties"]["Name"]["type"], "title")

    def test_create_and_update_data_source(self) -> None:
        responses = [
            _response({"id": "ds-1", "url": "https://notion.so/ds-1"}),
            _response({"id": "ds-1", "url": "https://notion.so/ds-1"}),
        ]
        create_request = {
            "parent": {"type": "database_id", "database_id": "database-1"},
            "properties": {"Name": {"title": {}}},
        }
        update_request = {"properties": {"Status": {"status": {}}}}
        with patch("httpx.Client.request", side_effect=responses) as request:
            created = self.service.create_data_source(create_request)
            updated = self.service.update_data_source("ds-1", update_request)
        self.assertEqual(created["id"], "ds-1")
        self.assertEqual(updated["data_source"]["id"], "ds-1")
        self.assertEqual(request.call_args_list[0].args[0], "POST")
        self.assertEqual(request.call_args_list[1].args[0], "PATCH")

    def test_create_data_source_requires_parent(self) -> None:
        with self.assertRaisesRegex(ValueError, "parent object"):
            self.service.create_data_source({"properties": {}})

    def test_create_data_source_requires_properties(self) -> None:
        with self.assertRaisesRegex(ValueError, "properties object"):
            self.service.create_data_source(
                {"parent": {"type": "database_id", "database_id": "database-1"}}
            )

    def test_create_database_sends_complete_request(self) -> None:
        database_request = {
            "parent": {"type": "page_id", "page_id": "page-1"},
            "title": [{"type": "text", "text": {"content": "Tasks"}}],
            "initial_data_source": {"properties": {"Name": {"title": {}}}},
        }
        with patch(
            "httpx.Client.request",
            return_value=_response({"id": "database-1", "url": "https://notion.so/database-1"}),
        ) as request:
            result = self.service.create_database(database_request)
        self.assertEqual(
            request.call_args.args[:2],
            ("POST", "https://api.notion.com/v1/databases"),
        )
        self.assertEqual(request.call_args.kwargs["json"], database_request)
        self.assertEqual(result["id"], "database-1")

    def test_create_database_requires_parent_object(self) -> None:
        with self.assertRaisesRegex(ValueError, "parent object"):
            self.service.create_database({"title": []})

    def test_retrieve_database_returns_data_sources(self) -> None:
        with patch(
            "httpx.Client.request",
            return_value=_response(
                {
                    "id": "database-1",
                    "data_sources": [{"id": "data-source-1", "name": "Tasks"}],
                }
            ),
        ) as request:
            result = self.service.retrieve_database("database-1")
        self.assertEqual(
            request.call_args.args[:2],
            ("GET", "https://api.notion.com/v1/databases/database-1"),
        )
        self.assertEqual(result["database"]["data_sources"][0]["id"], "data-source-1")

    def test_update_database_sends_complete_request(self) -> None:
        database_request = {"is_inline": True, "is_locked": True}
        with patch(
            "httpx.Client.request",
            return_value=_response({"id": "database-1", "url": "https://notion.so/database-1"}),
        ) as request:
            result = self.service.update_database("database-1", database_request)
        self.assertEqual(
            request.call_args.args[:2],
            ("PATCH", "https://api.notion.com/v1/databases/database-1"),
        )
        self.assertEqual(request.call_args.kwargs["json"], database_request)
        self.assertEqual(result["url"], "https://notion.so/database-1")

    def test_update_database_requires_at_least_one_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one field"):
            self.service.update_database("database-1", {})

    def test_update_page_sends_properties(self) -> None:
        with patch("httpx.Client.request", return_value=_response({"id": "page-1"})) as request:
            self.service.update_page("page-1", properties={"Status": {"status": {"name": "Done"}}})
        self.assertEqual(request.call_args.args[0], "PATCH")
        self.assertIn("properties", request.call_args.kwargs["json"])

    def test_trash_page_uses_in_trash(self) -> None:
        with patch("httpx.Client.request", return_value=_response({"id": "page-1"})) as request:
            self.service.update_page("page-1", in_trash=True)
        self.assertTrue(request.call_args.kwargs["json"]["in_trash"])

    def test_query_data_source_clamps_page_size(self) -> None:
        with patch(
            "httpx.Client.request",
            return_value=_response({"results": [], "has_more": False, "next_cursor": None}),
        ) as request:
            self.service.query_data_source("ds-1", page_size=500)
        self.assertEqual(request.call_args.kwargs["json"]["page_size"], 100)

    def test_update_and_delete_block(self) -> None:
        responses = [
            _response({"id": "block-1", "type": "paragraph"}),
            _response({"id": "block-1", "archived": True}),
        ]
        with patch("httpx.Client.request", side_effect=responses) as request:
            updated = self.service.update_block(
                "block-1",
                {"paragraph": {"rich_text": []}},
            )
            deleted = self.service.delete_block("block-1")
        self.assertTrue(updated["success"])
        self.assertTrue(deleted["block"]["archived"])
        self.assertEqual(request.call_args_list[0].args[0], "PATCH")
        self.assertEqual(request.call_args_list[1].args[0], "DELETE")

    def test_append_blocks_requires_children(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one child"):
            self.service.append_block_children("page-1", [])

    def test_append_blocks_returns_count(self) -> None:
        with patch(
            "httpx.Client.request",
            return_value=_response({"results": [{"id": "block-1"}]}),
        ) as request:
            result = self.service.append_block_children(
                "page-1",
                [{"object": "block", "type": "paragraph", "paragraph": {}}],
                after="block-0",
            )
        self.assertEqual(result["count"], 1)
        self.assertNotIn("after", request.call_args.kwargs["json"])
        self.assertEqual(
            request.call_args.kwargs["json"]["position"],
            {
                "type": "after_block",
                "after_block": {"id": "block-0"},
            },
        )

    def test_append_blocks_supports_start_and_batches_in_order(self) -> None:
        children = [{"type": "paragraph", "index": index} for index in range(101)]
        responses = [
            _response({"results": [{"id": f"block-{index}"} for index in range(100)]}),
            _response({"results": [{"id": "block-100"}]}),
        ]
        with patch("httpx.Client.request", side_effect=responses) as request:
            result = self.service.append_block_children(
                "page-1",
                children,
                position="start",
            )
        self.assertEqual(result["count"], 101)
        self.assertEqual(
            request.call_args_list[0].kwargs["json"]["position"],
            {"type": "start"},
        )
        self.assertEqual(
            request.call_args_list[1].kwargs["json"]["position"],
            {
                "type": "after_block",
                "after_block": {"id": "block-99"},
            },
        )

    def test_append_blocks_rejects_invalid_position(self) -> None:
        with self.assertRaisesRegex(ValueError, "position must be"):
            self.service.append_block_children(
                "page-1",
                [{"type": "paragraph"}],
                position="middle",
            )

    def test_notion_urls_are_normalized_to_ids(self) -> None:
        with patch("httpx.Client.request", return_value=_response({"id": "page"})) as request:
            self.service.retrieve_page(
                "https://www.notion.so/workspace/Roadmap-"
                "0123456789abcdef0123456789abcdef?v=fedcba9876543210fedcba9876543210"
            )
        self.assertIn(
            "/pages/01234567-89ab-cdef-0123-456789abcdef",
            request.call_args.args[1],
        )

    def test_rate_limit_response_retries_after_header(self) -> None:
        responses = [
            _response(
                {"code": "rate_limited", "message": "Slow down"},
                status_code=429,
                headers={"Retry-After": "2"},
            ),
            _response({"id": "bot"}),
        ]
        with (
            patch("httpx.Client.request", side_effect=responses) as request,
            patch("app.services.notion_service.random.uniform", return_value=0.0),
            patch("app.services.notion_service.time.sleep") as sleep,
        ):
            result = self.service.test_connection()
        self.assertEqual(result["id"], "bot")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(2.0)

    def test_rate_limit_delay_is_capped_and_jittered(self) -> None:
        responses = [
            _response(
                {"code": "rate_limited"},
                status_code=429,
                headers={"Retry-After": "120"},
            ),
            _response({"id": "bot"}),
        ]
        with (
            patch("httpx.Client.request", side_effect=responses),
            patch("app.services.notion_service.random.uniform", return_value=2.0) as jitter,
            patch("app.services.notion_service.time.sleep") as sleep,
        ):
            self.service.test_connection()
        jitter.assert_called_once_with(0.0, 2.5)
        sleep.assert_called_once_with(10.0)

    def test_reuses_http_client_across_paginated_requests(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _response({"results": [], "has_more": True, "next_cursor": "next"}),
            _response({"results": [], "has_more": False, "next_cursor": None}),
        ]
        service = NotionService({"api_token": "secret"}, client=client)
        service.search(fetch_all=True)
        self.assertEqual(client.request.call_count, 2)
        client.close.assert_not_called()

    def test_reuses_shared_http_client_across_service_instances(self) -> None:
        shared_client = MagicMock()
        shared_client.request.side_effect = [
            _response({"id": "bot-1"}),
            _response({"id": "bot-2"}),
        ]
        with patch("httpx.Client", return_value=shared_client) as client_factory:
            first = NotionService({"api_token": "first"})
            second = NotionService({"api_token": "second"})
            first.test_connection()
            second.test_connection()
        client_factory.assert_called_once()
        self.assertEqual(shared_client.request.call_count, 2)

    def test_api_error_uses_notion_message(self) -> None:
        with patch(
            "httpx.Client.request",
            return_value=_response(
                {"code": "unauthorized", "message": "API token is invalid"},
                status_code=401,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "API token is invalid"):
                self.service.test_connection()

    def test_transport_error_is_wrapped(self) -> None:
        with patch("httpx.Client.request", side_effect=httpx.ConnectError("offline")):
            with self.assertRaisesRegex(ValueError, "Notion connection test failed"):
                self.service.test_connection()

    def test_json_parsers_validate_shapes(self) -> None:
        self.assertEqual(NotionService.parse_json_object('{"ok":true}', "field"), {"ok": True})
        self.assertEqual(NotionService.parse_json_array("[1,2]", "field"), [1, 2])
        with self.assertRaisesRegex(ValueError, "JSON object"):
            NotionService.parse_json_object("[]", "field")
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            NotionService.parse_json_array("[", "field")


def _notion_workflow(node_data: dict) -> tuple[list[dict], list[dict]]:
    nodes = [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "value": "hello", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "notion",
            "type": "notion",
            "position": {"x": 200, "y": 0},
            "data": {"label": "notionNode", **node_data},
        },
        {
            "id": "out",
            "type": "output",
            "position": {"x": 400, "y": 0},
            "data": {"label": "out", "message": "$notionNode", "allowDownstream": False},
        },
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "notion"},
        {"id": "e2", "source": "notion", "target": "out"},
    ]
    return nodes, edges


class NotionExecutorTests(unittest.TestCase):
    def _execute(self, node_data: dict, initial_inputs: dict | None = None):
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = _notion_workflow(node_data)
        with (
            patch("app.db.session.SessionLocal") as session,
            patch("app.services.encryption.decrypt_config", return_value={"api_token": "secret"}),
        ):
            db = MagicMock()
            db.__enter__.return_value = db
            db.__exit__.return_value = False
            credential = MagicMock(encrypted_config="encrypted")
            credential.type = CredentialType.notion
            db.query.return_value.filter.return_value.first.return_value = credential
            session.return_value = db
            return WorkflowExecutor(
                nodes=nodes,
                edges=edges,
                actor_user_id=uuid.uuid4(),
            ).execute(
                workflow_id=uuid.uuid4(),
                initial_inputs=initial_inputs or {"text": "hello"},
            )

    @staticmethod
    def _notion_error(result) -> str:
        notion_result = next(
            item for item in result.node_results if item["node_label"] == "notionNode"
        )
        return str(notion_result["error"])

    def test_search_executes_end_to_end(self) -> None:
        with patch.object(
            NotionService,
            "search",
            return_value={"results": [], "count": 0, "success": True},
        ) as search:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "search",
                    "notionQuery": "$start.text",
                    "notionFilter": "{}",
                    "notionSort": "{}",
                    "notionPageSize": "100",
                }
            )
        self.assertEqual(result.status, "success")
        search.assert_called_once()
        self.assertEqual(search.call_args.kwargs["query"], "hello")

    def test_create_page_resolves_json_expressions(self) -> None:
        with patch.object(
            NotionService,
            "create_page",
            return_value={"page": {"id": "page-1"}, "success": True},
        ) as create:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "createPage",
                    "notionDataSourceId": "ds-1",
                    "notionProperties": ('{"Name":{"title":[{"text":{"content":"$start.text"}}]}}'),
                    "notionChildren": "[]",
                    "notionIcon": "{}",
                    "notionCover": "{}",
                }
            )
        self.assertEqual(result.status, "success")
        self.assertEqual(
            create.call_args.kwargs["properties"]["Name"]["title"][0]["text"]["content"],
            "hello",
        )

    def test_create_page_accepts_whole_object_and_array_expressions(self) -> None:
        properties = {"Name": {"title": [{"text": {"content": "Task"}}]}}
        children = [{"object": "block", "type": "paragraph", "paragraph": {}}]
        with patch.object(
            NotionService,
            "create_page",
            return_value={"page": {"id": "page-1"}, "success": True},
        ) as create:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "createPage",
                    "notionDataSourceId": "$input.data_source_id",
                    "notionProperties": "$input.properties",
                    "notionChildren": "$input.children",
                    "notionIcon": "{}",
                    "notionCover": "{}",
                },
                {
                    "data_source_id": "ds-1",
                    "properties": properties,
                    "children": children,
                },
            )
        self.assertEqual(result.status, "success")
        self.assertEqual(create.call_args.kwargs["properties"], properties)
        self.assertEqual(create.call_args.kwargs["children"], children)

    def test_append_blocks_passes_selected_position(self) -> None:
        with patch.object(
            NotionService,
            "append_block_children",
            return_value={"results": [], "count": 0, "success": True},
        ) as append:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "appendBlocks",
                    "notionBlockId": "block-1",
                    "notionChildren": '[{"type":"paragraph","paragraph":{}}]',
                    "notionAppendPosition": "start",
                }
            )
        self.assertEqual(result.status, "success")
        append.assert_called_once_with(
            "block-1",
            [{"type": "paragraph", "paragraph": {}}],
            position="start",
            after=None,
        )

    def test_update_block_executes_end_to_end(self) -> None:
        with patch.object(
            NotionService,
            "update_block",
            return_value={"block": {"id": "block-1"}, "success": True},
        ) as update:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "updateBlock",
                    "notionBlockId": "block-1",
                    "notionBlock": '{"paragraph":{"rich_text":[]}}',
                }
            )
        self.assertEqual(result.status, "success")
        update.assert_called_once_with("block-1", {"paragraph": {"rich_text": []}})

    def test_delete_block_executes_end_to_end(self) -> None:
        with patch.object(
            NotionService,
            "delete_block",
            return_value={"block": {"id": "block-1", "archived": True}, "success": True},
        ) as delete:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "deleteBlock",
                    "notionBlockId": "block-1",
                }
            )
        self.assertEqual(result.status, "success")
        delete.assert_called_once_with("block-1")

    def test_retrieve_data_source_executes_end_to_end(self) -> None:
        with patch.object(
            NotionService,
            "retrieve_data_source",
            return_value={
                "data_source": {"id": "ds-1", "properties": {"Name": {"type": "title"}}},
                "success": True,
            },
        ) as retrieve:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "retrieveDataSource",
                    "notionDataSourceId": "ds-1",
                }
            )
        self.assertEqual(result.status, "success")
        retrieve.assert_called_once_with("ds-1")

    def test_create_and_update_data_source_execute_end_to_end(self) -> None:
        create_request = {
            "parent": {"type": "database_id", "database_id": "database-1"},
            "properties": {"Name": {"title": {}}},
        }
        update_request = {"properties": {"Status": {"status": {}}}}
        with patch.object(
            NotionService,
            "create_data_source",
            return_value={"data_source": {"id": "ds-1"}, "success": True},
        ) as create:
            created = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "createDataSource",
                    "notionDataSource": "$input.data_source",
                },
                {"data_source": create_request},
            )
        with patch.object(
            NotionService,
            "update_data_source",
            return_value={"data_source": {"id": "ds-1"}, "success": True},
        ) as update:
            updated = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "updateDataSource",
                    "notionDataSourceId": "ds-1",
                    "notionDataSource": "$input.data_source",
                },
                {"data_source": update_request},
            )
        self.assertEqual(created.status, "success")
        self.assertEqual(updated.status, "success")
        create.assert_called_once_with(create_request)
        update.assert_called_once_with("ds-1", update_request)

    def test_create_database_resolves_request_expressions(self) -> None:
        with patch.object(
            NotionService,
            "create_database",
            return_value={"database": {"id": "database-1"}, "success": True},
        ) as create:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "createDatabase",
                    "notionDatabase": (
                        '{"parent":{"type":"page_id","page_id":"$input.parent_id"},'
                        '"title":[{"type":"text","text":{"content":"$input.title"}}]}'
                    ),
                },
                {"parent_id": "page-1", "title": "Tasks"},
            )
        self.assertEqual(result.status, "success")
        create.assert_called_once_with(
            {
                "parent": {"type": "page_id", "page_id": "page-1"},
                "title": [{"type": "text", "text": {"content": "Tasks"}}],
            }
        )

    def test_retrieve_database_executes_end_to_end(self) -> None:
        with patch.object(
            NotionService,
            "retrieve_database",
            return_value={
                "database": {"id": "database-1", "data_sources": []},
                "success": True,
            },
        ) as retrieve:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "retrieveDatabase",
                    "notionDatabaseId": "database-1",
                }
            )
        self.assertEqual(result.status, "success")
        retrieve.assert_called_once_with("database-1")

    def test_update_database_accepts_whole_object_expression(self) -> None:
        update_request = {"is_inline": True, "is_locked": False}
        with patch.object(
            NotionService,
            "update_database",
            return_value={"database": {"id": "database-1"}, "success": True},
        ) as update:
            result = self._execute(
                {
                    "credentialId": "cred-1",
                    "notionOperation": "updateDatabase",
                    "notionDatabaseId": "$input.database_id",
                    "notionDatabase": "$input.database",
                },
                {"database_id": "database-1", "database": update_request},
            )
        self.assertEqual(result.status, "success")
        update.assert_called_once_with("database-1", update_request)

    def test_required_fields_are_validated_before_service_calls(self) -> None:
        cases = [
            ({"notionOperation": "getPage"}, "page ID"),
            ({"notionOperation": "createPage"}, "properties"),
            (
                {
                    "notionOperation": "createPage",
                    "notionProperties": '{"Name":{"title":[]}}',
                },
                "data source ID or parent page ID",
            ),
            ({"notionOperation": "updatePage"}, "page ID"),
            ({"notionOperation": "trashPage"}, "page ID"),
            ({"notionOperation": "restorePage"}, "page ID"),
            ({"notionOperation": "createDatabase"}, "parent object"),
            ({"notionOperation": "retrieveDatabase"}, "database ID"),
            ({"notionOperation": "updateDatabase"}, "at least one field"),
            (
                {
                    "notionOperation": "updateDatabase",
                    "notionDatabase": '{"title":[]}',
                },
                "database ID",
            ),
            ({"notionOperation": "retrieveDataSource"}, "data source ID"),
            ({"notionOperation": "createDataSource"}, "parent object"),
            ({"notionOperation": "updateDataSource"}, "at least one field"),
            (
                {
                    "notionOperation": "updateDataSource",
                    "notionDataSource": '{"properties":{}}',
                },
                "data source ID",
            ),
            ({"notionOperation": "queryDataSource"}, "data source ID"),
            ({"notionOperation": "getBlockChildren"}, "block or page ID"),
            ({"notionOperation": "updateBlock"}, "block ID"),
            ({"notionOperation": "deleteBlock"}, "block ID"),
            (
                {
                    "notionOperation": "appendBlocks",
                    "notionChildren": '[{"type":"paragraph","paragraph":{}}]',
                },
                "block or page ID",
            ),
            (
                {
                    "notionOperation": "appendBlocks",
                    "notionBlockId": "block-1",
                    "notionChildren": "[]",
                },
                "child blocks",
            ),
        ]
        for node_data, expected_error in cases:
            with self.subTest(operation=node_data["notionOperation"]):
                with patch("httpx.Client.request") as request:
                    result = self._execute({"credentialId": "cred-1", **node_data})
                self.assertEqual(result.status, "error")
                self.assertIn(expected_error, self._notion_error(result))
                request.assert_not_called()

    def test_missing_credential_returns_node_error(self) -> None:
        result = self._execute({"credentialId": "", "notionOperation": "search"})
        self.assertEqual(result.status, "error")
        self.assertIn("credential", self._notion_error(result).lower())

    def test_missing_operation_returns_node_error(self) -> None:
        result = self._execute({"credentialId": "cred-1", "notionOperation": ""})
        self.assertEqual(result.status, "error")
        self.assertIn("operation", self._notion_error(result).lower())

    def test_unknown_operation_returns_node_error(self) -> None:
        result = self._execute({"credentialId": "cred-1", "notionOperation": "explode"})
        self.assertEqual(result.status, "error")
        self.assertIn("unknown notion operation", self._notion_error(result).lower())
