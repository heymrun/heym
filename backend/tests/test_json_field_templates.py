"""JSON node fields keep a resolved value with a quote or a line break inside that value."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.config import settings
from app.db.models import CredentialType
from app.services.encryption import encrypt_config
from app.services.node_execution.json_fields import render_json_template, resolve_json_field
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

    def test_a_line_break_escape_inside_an_expression_still_resolves(self) -> None:
        # Parsing decodes the `\n` escape into a line break the expression cannot parse; the
        # field goes back to substitution, which reads it as written.
        template = '{"notes": "$input.notes.replace(\'\\n\', \' \')", "status": "new"}'
        inputs = {"input": {"notes": "line one\nline two"}}
        want = {"notes": "line one line two", "status": "new"}

        rendered = render_json_template(self.executor, template, inputs, "n1")
        self.assertEqual(json.loads(rendered), want)
        self.assertEqual(resolve_json_field(self.executor, template, inputs, "n1"), want)

    def test_a_value_with_a_line_break_that_resolves_is_still_parsed_first(self) -> None:
        template = '{"body": "Hi $input.name,\\nthanks for signing up"}'
        want = {"body": f"Hi {TRICKY},\nthanks for signing up"}

        rendered = render_json_template(self.executor, template, self.inputs, "n1")
        self.assertEqual(json.loads(rendered), want)
        self.assertEqual(resolve_json_field(self.executor, template, self.inputs, "n1"), want)

    def test_an_expression_in_a_key_resolves_like_one_in_a_value(self) -> None:
        template = '{"$input.kind": "x", "meta": {"$input.kind": "$input.name"}}'
        inputs = {"input": {"kind": "bug_report", "name": TRICKY}}
        want = {"bug_report": "x", "meta": {"bug_report": TRICKY}}

        rendered = render_json_template(self.executor, template, inputs, "n1")
        self.assertEqual(json.loads(rendered), want)
        self.assertEqual(resolve_json_field(self.executor, template, inputs, "n1"), want)

    def test_a_key_that_resolves_to_a_quote_stays_a_valid_key(self) -> None:
        template = '{"$input.name": 1}'

        rendered = render_json_template(self.executor, template, self.inputs, "n1")
        self.assertEqual(json.loads(rendered), {TRICKY: 1})


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

    def test_supabase_insert_resolves_an_expression_in_a_column_name(self) -> None:
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
                "supabaseRows": '[{"id": "$input.userId", "$input.column": "$input.name"}]',
            },
        }
        result = _run(
            node,
            {"input": {"userId": "u-1", "column": "display_name", "name": "Ada"}},
            credential,
            patch("app.services.supabase_service.get_guarded_http_client", return_value=client),
            patch.object(settings, "http_allow_private_urls", True),
        )

        self.assertEqual(result.status, "success", result.error)
        self.assertEqual(sent, [[{"id": "u-1", "display_name": "Ada"}]])


def _credential(credential_type: CredentialType, config: dict) -> SimpleNamespace:
    return SimpleNamespace(type=credential_type, encrypted_config=encrypt_config(config))


class MoreNodeJsonFieldTests(unittest.TestCase):
    """ClickHouse, BigQuery, RabbitMQ, Sentry, GitHub, WebSocket and Decision do it too."""

    def test_clickhouse_insert_and_filter_keep_the_value(self) -> None:
        service = MagicMock()
        service.insert.return_value = {"inserted": 1}
        service.remove.return_value = {"removed": 1}
        data = {"label": "ch", "credentialId": "cred-1", "clickhouseTable": "leads"}
        insert = {
            "id": "c1",
            "type": "clickhouse",
            "data": {
                **data,
                "clickhouseOperation": "insert",
                "clickhouseData": '[{"name": "$input.name", "source": "form"}]',
            },
        }
        remove = {
            "id": "c2",
            "type": "clickhouse",
            "data": {
                **data,
                "clickhouseOperation": "remove",
                "clickhouseFilter": '{"name": "$input.name"}',
            },
        }
        credential = _credential(CredentialType.clickhouse, {"host": "ch"})
        with patch("app.services.clickhouse_service.ClickHouseService", return_value=service):
            inserted = _run(insert, {"input": {"name": TRICKY}}, credential)
            removed = _run(remove, {"input": {"name": TRICKY}}, credential)

        self.assertEqual((inserted.status, removed.status), ("success", "success"))
        service.insert.assert_called_once_with("leads", [{"name": TRICKY, "source": "form"}])
        service.remove.assert_called_once_with("leads", filters={"name": TRICKY})

    def test_clickhouse_filter_that_resolves_empty_still_means_no_filter(self) -> None:
        service = MagicMock()
        service.count.return_value = {"count": 3}
        node = {
            "id": "c1",
            "type": "clickhouse",
            "data": {
                "label": "ch",
                "credentialId": "cred-1",
                "clickhouseOperation": "count",
                "clickhouseTable": "leads",
                "clickhouseFilter": "$input.filter",
            },
        }
        with patch("app.services.clickhouse_service.ClickHouseService", return_value=service):
            result = _run(
                node, {"input": {"filter": ""}}, _credential(CredentialType.clickhouse, {"h": 1})
            )

        self.assertEqual(result.status, "success")
        service.count.assert_called_once_with("leads", filters={})

    def test_bigquery_insert_rows_keeps_the_value(self) -> None:
        service = MagicMock()
        service.insert_rows.return_value = {"inserted": 1}
        node = {
            "id": "b1",
            "type": "bigquery",
            "data": {
                "label": "bq",
                "credentialId": "cred-1",
                "bqOperation": "insertRows",
                "bqProjectId": "p",
                "bqDatasetId": "d",
                "bqTableId": "t",
                "bqRows": '[{"name": "$input.name"}]',
            },
        }
        with patch("app.services.bigquery_service.BigQueryService", return_value=service):
            result = _run(
                node, {"input": {"name": TRICKY}}, _credential(CredentialType.bigquery, {"k": 1})
            )

        self.assertEqual(result.status, "success")
        service.insert_rows.assert_called_once_with("p", "d", "t", [{"name": TRICKY}])

    def _rabbitmq_body(self, template: str, inputs: dict) -> object:
        publish = AsyncMock(return_value={"published": True})
        node = {
            "id": "r1",
            "type": "rabbitmq",
            "data": {
                "label": "mq",
                "credentialId": "cred-1",
                "rabbitmqOperation": "send",
                "rabbitmqQueueName": "leads",
                "rabbitmqMessageBody": template,
            },
        }
        with patch("app.services.rabbitmq_pool.publish_message_direct", publish):
            result = _run(
                node, inputs, _credential(CredentialType.rabbitmq, {"rabbitmq_host": "m"})
            )
        self.assertEqual(result.status, "success")
        return publish.call_args.kwargs["body"]

    def test_rabbitmq_json_body_is_published_as_the_object(self) -> None:
        body = self._rabbitmq_body(
            '{"name": "$input.name", "event": "signup"}', {"input": {"name": TRICKY}}
        )
        self.assertEqual(body, {"name": TRICKY, "event": "signup"})

    def test_rabbitmq_json_body_resolves_an_expression_in_a_key(self) -> None:
        body = self._rabbitmq_body(
            '{"$input.kind": "x", "event": "signup"}', {"input": {"kind": "bug_report"}}
        )
        self.assertEqual(body, {"bug_report": "x", "event": "signup"})

    def test_rabbitmq_text_body_is_still_published_as_text(self) -> None:
        body = self._rabbitmq_body("Hello $input.name", {"input": {"name": "Ada"}})
        self.assertEqual(body, "Hello Ada")

    def test_sentry_payload_keeps_the_value(self) -> None:
        service = MagicMock()
        service.update_project.return_value = {"slug": "web"}
        node = {
            "id": "s1",
            "type": "sentry",
            "data": {
                "label": "sentry",
                "credentialId": "cred-1",
                "sentryOperation": "updateProject",
                "sentryOrganizationSlug": "acme",
                "sentryProjectSlug": "web",
                "sentryPayload": '{"name": "$input.name"}',
            },
        }
        result = _run(
            node,
            {"input": {"name": TRICKY}},
            _credential(CredentialType.sentry, {"auth_token": "t"}),
            patch("app.services.node_execution.nodes.sentry_node.SessionLocal", MagicMock()),
            patch(
                "app.services.node_execution.nodes.sentry_node.SentryService",
                return_value=service,
            ),
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(service.update_project.call_args.args[-1], {"name": TRICKY})

    def test_github_workflow_inputs_keep_the_value(self) -> None:
        service = MagicMock()
        service.dispatch_workflow.return_value = {"dispatched": True}
        node = {
            "id": "g1",
            "type": "github",
            "data": {
                "label": "deploy",
                "credentialId": "cred-1",
                "githubOperation": "dispatchWorkflow",
                "githubOwner": "acme",
                "githubRepo": "web",
                "githubWorkflowId": "notify.yml",
                "githubBranch": "main",
                "githubWorkflowInputs": '{"message": "$input.name"}',
            },
        }
        with patch("app.services.github_service.GitHubService", return_value=service):
            result = _run(
                node, {"input": {"name": TRICKY}}, _credential(CredentialType.github, {"t": 1})
            )

        self.assertEqual(result.status, "success")
        self.assertEqual(service.dispatch_workflow.call_args.kwargs["inputs"], {"message": TRICKY})

    def _websocket_frame(self, template: str, inputs: dict) -> object:
        send = AsyncMock(return_value={"sent": True})
        node = {
            "id": "w1",
            "type": "websocketSend",
            "data": {
                "label": "push",
                "websocketUrl": "wss://feed.example/ws",
                "websocketMessage": template,
            },
        }
        with patch("app.services.workflow_executor.send_websocket_message", send):
            result = _run(node, inputs, SimpleNamespace(type=None, encrypted_config=""))
        self.assertEqual(result.status, "success")
        return send.call_args.kwargs["message"]

    def test_websocket_json_message_stays_valid_json(self) -> None:
        frame = self._websocket_frame(
            '{"name": "$input.name", "kind": "lead"}', {"input": {"name": TRICKY}}
        )
        self.assertEqual(json.loads(frame), {"name": TRICKY, "kind": "lead"})

    def test_websocket_text_and_static_messages_are_sent_as_written(self) -> None:
        inputs = {"input": {"name": "Ada"}}
        self.assertEqual(self._websocket_frame("Hello $input.name", inputs), "Hello Ada")
        self.assertEqual(self._websocket_frame('{"ping":1}', inputs), '{"ping":1}')

    def _decision_body(self, template: str, inputs: dict) -> object:
        call = MagicMock(return_value={"answers": []})
        node = {
            "id": "d1",
            "type": "decision",
            "data": {
                "label": "decide",
                "credentialId": "cred-1",
                "customBodyEnabled": True,
                "customBody": template,
            },
        }
        result = _run(
            node,
            inputs,
            SimpleNamespace(type=None, encrypted_config=""),
            patch("app.services.node_execution.nodes.decision_node.call_decision_model", call),
            patch(
                "app.services.node_execution.nodes.decision_node.load_decision_credential",
                return_value={"base_url": "https://decide.example", "api_key": "k"},
            ),
        )
        self.assertEqual(result.status, "success")
        return call.call_args.kwargs["body"]

    def test_decision_custom_body_keeps_the_value(self) -> None:
        body = self._decision_body(
            '{"model": "m", "state": "Customer: $input.name", "questions": []}',
            {"input": {"name": TRICKY}},
        )
        self.assertEqual(body, {"model": "m", "state": f"Customer: {TRICKY}", "questions": []})

    def test_decision_custom_body_from_one_expression_resolves_as_before(self) -> None:
        raw = json.dumps({"model": "m", "state": "s", "questions": []})
        body = self._decision_body("$input.body", {"input": {"body": raw}})
        self.assertEqual(body, {"model": "m", "state": "s", "questions": []})


if __name__ == "__main__":
    unittest.main()
