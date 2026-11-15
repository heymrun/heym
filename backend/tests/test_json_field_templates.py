"""JSON node fields keep a resolved value with a quote or a line break inside that value."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from app.config import settings
from app.db.models import CredentialType
from app.services.encryption import encrypt_config
from app.services.node_execution.json_fields import render_json_template
from app.services.notion_service import NotionService
from app.services.workflow_executor import WorkflowExecutor

TRICKY = 'Dwayne "The Rock" Johnson\nsecond line'


def _executor(node: dict) -> WorkflowExecutor:
    return WorkflowExecutor(nodes=[node], edges=[], workflow_id=uuid.uuid4())


def _run(node: dict, inputs: dict, credential: SimpleNamespace, *extra_patches):
    executor = _executor(node)
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch.object(WorkflowExecutor, "_get_accessible_credential", return_value=credential),
    ):
        for patcher in extra_patches:
            patcher.start()
        try:
            return executor.execute_node(node["id"], inputs)
        finally:
            for patcher in extra_patches:
                patcher.stop()


def _recording_client(response_json: object, base_url: str = "") -> tuple[httpx.Client, list]:
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content or b"null"))
        return httpx.Response(200, json=response_json)

    return httpx.Client(base_url=base_url, transport=httpx.MockTransport(handler)), sent


class RenderJsonTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = _executor({"id": "n1", "type": "set", "data": {"label": "n1"}})
        self.inputs = {"input": {"name": TRICKY, "age": 41}}

    def test_a_value_with_a_quote_and_a_line_break_stays_inside_its_string(self) -> None:
        rendered = render_json_template(
            self.executor, '{"name": "$input.name", "status": "new"}', self.inputs, "n1"
        )
        self.assertEqual(json.loads(rendered), {"name": TRICKY, "status": "new"})

    def test_a_template_that_is_not_json_yet_is_substituted_first(self) -> None:
        rendered = render_json_template(self.executor, '{"age": $input.age}', self.inputs, "n1")
        self.assertEqual(json.loads(rendered), {"age": 41})

    def test_operator_keys_and_plain_values_are_kept(self) -> None:
        rendered = render_json_template(
            self.executor, '{"age": {"$gt": 18}, "tags": ["a", 1, true]}', self.inputs, "n1"
        )
        self.assertEqual(json.loads(rendered), {"age": {"$gt": 18}, "tags": ["a", 1, True]})


class NodeJsonFieldTests(unittest.TestCase):
    def test_grist_create_record_keeps_the_fields(self) -> None:
        server = "https://docs.getgrist.com"
        client, sent = _recording_client({"records": [{"id": 42}]}, server)
        credential = SimpleNamespace(
            type=CredentialType.grist,
            encrypted_config=encrypt_config({"api_key": "k", "server_url": server}),
        )
        node = {
            "id": "g1",
            "type": "grist",
            "data": {
                "label": "addLead",
                "credentialId": "cred-1",
                "gristOperation": "createRecord",
                "gristDocId": "doc123",
                "gristTableId": "Leads",
                "gristRecordData": '{"User_Name": "Ada", "Notes": "$input.notes"}',
            },
        }
        result = _run(
            node,
            {"input": {"notes": TRICKY}},
            credential,
            patch("app.services.grist_pool.get_grist_client", return_value=client),
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(sent, [{"records": [{"fields": {"User_Name": "Ada", "Notes": TRICKY}}]}])

    def test_notion_create_page_keeps_the_title(self) -> None:
        client, sent = _recording_client({"object": "page", "id": "p1", "url": "https://n/p1"})
        credential = SimpleNamespace(
            type=CredentialType.notion, encrypted_config=encrypt_config({"api_token": "ntn_x"})
        )
        node = {
            "id": "n1",
            "type": "notion",
            "data": {
                "label": "createTask",
                "credentialId": "cred-1",
                "notionOperation": "createPage",
                "notionDataSourceId": "1f2e3d4c-5b6a-4978-8695-a4b3c2d1e0f9",
                "notionProperties": '{"Name": {"title": [{"text": {"content": "$input.title"}}]}}',
            },
        }
        result = _run(
            node,
            {"input": {"title": TRICKY}},
            credential,
            patch.object(NotionService, "_shared_client", client),
        )

        self.assertEqual(result.status, "success", result.error)
        self.assertEqual(sent[-1]["properties"]["Name"]["title"][0]["text"]["content"], TRICKY)

    def test_supabase_insert_keeps_the_row(self) -> None:
        client, sent = _recording_client([{"id": "u-1"}])
        credential = SimpleNamespace(
            type=CredentialType.supabase,
            encrypted_config=encrypt_config(
                {"supabase_url": "https://abcd.supabase.co", "supabase_key": "service-key"}
            ),
        )
        node = {
            "id": "s1",
            "type": "supabase",
            "data": {
                "label": "saveProfile",
                "credentialId": "cred-1",
                "supabaseOperation": "insert",
                "supabaseTable": "profiles",
                "supabaseRowsInputMode": "raw",
                "supabaseRows": '[{"id": "$input.userId", "display_name": "$input.name"}]',
            },
        }
        result = _run(
            node,
            {"input": {"userId": "u-1", "name": TRICKY}},
            credential,
            patch("app.services.supabase_service.get_guarded_http_client", return_value=client),
            # Only so the SSRF guard does not resolve the made-up project host.
            patch.object(settings, "http_allow_private_urls", True),
        )

        self.assertEqual(result.status, "success", result.error)
        self.assertEqual(sent, [[{"id": "u-1", "display_name": TRICKY}]])


if __name__ == "__main__":
    unittest.main()
