"""Unit and executor tests for the Notion integration."""

import unittest
import uuid
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.notion_service import NotionService


def _response(payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.is_success = 200 <= status_code < 300
    response.status_code = status_code
    response.text = str(payload)
    response.json.return_value = payload
    return response


class NotionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = NotionService({"api_token": "secret_test_token"})

    def test_requires_api_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "api_token"):
            NotionService({})

    def test_connection_uses_current_notion_version(self) -> None:
        with patch("httpx.request", return_value=_response({"id": "bot"})) as request:
            result = self.service.test_connection()
        self.assertEqual(result["id"], "bot")
        self.assertEqual(request.call_args.args[:2], ("GET", "https://api.notion.com/v1/users/me"))
        self.assertEqual(
            request.call_args.kwargs["headers"]["Notion-Version"],
            NotionService.API_VERSION,
        )

    def test_search_builds_payload(self) -> None:
        with patch(
            "httpx.request",
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
        with patch("httpx.request", side_effect=responses) as request:
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
        ):
            result = self.service.list_data_sources("Task")
        self.assertEqual(
            result["data_sources"],
            [{"id": "ds-1", "title": "Tasks", "url": "https://notion.so/tasks"}],
        )

    def test_create_page_uses_data_source_parent(self) -> None:
        with patch(
            "httpx.request",
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

    def test_update_page_sends_properties(self) -> None:
        with patch("httpx.request", return_value=_response({"id": "page-1"})) as request:
            self.service.update_page("page-1", properties={"Status": {"status": {"name": "Done"}}})
        self.assertEqual(request.call_args.args[0], "PATCH")
        self.assertIn("properties", request.call_args.kwargs["json"])

    def test_trash_page_uses_in_trash(self) -> None:
        with patch("httpx.request", return_value=_response({"id": "page-1"})) as request:
            self.service.update_page("page-1", in_trash=True)
        self.assertTrue(request.call_args.kwargs["json"]["in_trash"])

    def test_query_data_source_clamps_page_size(self) -> None:
        with patch(
            "httpx.request",
            return_value=_response({"results": [], "has_more": False, "next_cursor": None}),
        ) as request:
            self.service.query_data_source("ds-1", page_size=500)
        self.assertEqual(request.call_args.kwargs["json"]["page_size"], 100)

    def test_append_blocks_requires_children(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one child"):
            self.service.append_block_children("page-1", [])

    def test_append_blocks_returns_count(self) -> None:
        with patch(
            "httpx.request",
            return_value=_response({"results": [{"id": "block-1"}]}),
        ):
            result = self.service.append_block_children(
                "page-1",
                [{"object": "block", "type": "paragraph", "paragraph": {}}],
            )
        self.assertEqual(result["count"], 1)

    def test_api_error_uses_notion_message(self) -> None:
        with patch(
            "httpx.request",
            return_value=_response(
                {"code": "unauthorized", "message": "API token is invalid"},
                status_code=401,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "API token is invalid"):
                self.service.test_connection()

    def test_transport_error_is_wrapped(self) -> None:
        with patch("httpx.request", side_effect=httpx.ConnectError("offline")):
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
    def _execute(self, node_data: dict):
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
            ).execute(workflow_id=uuid.uuid4(), initial_inputs={"text": "hello"})

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

    def test_missing_credential_returns_node_error(self) -> None:
        result = self._execute({"credentialId": "", "notionOperation": "search"})
        self.assertEqual(result.status, "error")
        notion_result = next(
            item for item in result.node_results if item["node_label"] == "notionNode"
        )
        self.assertIn("credential", notion_result["error"].lower())

    def test_missing_operation_returns_node_error(self) -> None:
        result = self._execute({"credentialId": "cred-1", "notionOperation": ""})
        self.assertEqual(result.status, "error")
        notion_result = next(
            item for item in result.node_results if item["node_label"] == "notionNode"
        )
        self.assertIn("operation", notion_result["error"].lower())

    def test_unknown_operation_returns_node_error(self) -> None:
        result = self._execute({"credentialId": "cred-1", "notionOperation": "explode"})
        self.assertEqual(result.status, "error")
        notion_result = next(
            item for item in result.node_results if item["node_label"] == "notionNode"
        )
        self.assertIn("unknown notion operation", notion_result["error"].lower())
