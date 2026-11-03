"""Slack node files: a message's files into Drive, and Drive files into Slack."""

import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from app.services import file_storage, slack_files, ssrf_guard
from app.services import slack_service as slack
from app.services.file_sandbox.manifest import DriveFileRef, FileAccessError
from app.services.file_sandbox.scope import RunFileScope
from app.services.node_execution.base import NodeExecutionContext
from app.services.slack_operations import run_bot_operation

CONFIG = {"bot_token": "xoxb-test", "signing_secret": "secret"}
OWNER = uuid.uuid4()
WORKFLOW = uuid.uuid4()
PDF_URL = "https://files.slack.com/files-pri/T1-F0CASE001/download/claim.pdf"
DOCX_URL = "https://files.slack.com/files-pri/T1-F0CASE002/download/exhibit.docx"


class _Executor:
    """Resolves one `$name` to a fixed object (as preserve_type does) or text in a template."""

    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = values or {}
        self.trace_user_id = OWNER
        self.actor_user_id = OWNER
        self.workflow_id = str(WORKFLOW)
        self.file_scope = RunFileScope().including_workflow(WORKFLOW)
        self._base_url = "https://heym.example"

    def resolve_expression(
        self, expr: str, _inputs: dict, _node_id: str, preserve_type: bool = False
    ) -> object:
        return self.values.get(expr, expr)

    def evaluate_message_template(self, template: str, _inputs: dict, _node_id: str) -> str:
        for key, value in self.values.items():
            template = template.replace(key, str(value))
        return template

    def _require_actor_user_id(self, _label: str) -> uuid.UUID:
        return self.actor_user_id


def _ctx(data: dict, values: dict[str, object] | None = None) -> NodeExecutionContext:
    return NodeExecutionContext(
        executor=_Executor(values),
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=time.time(),
        node={"id": "n1", "type": "slack", "data": data},
        node_type="slack",
        node_data=data,
        node_label=data.get("label", "files"),
    )


def _file_info(file_id: str, name: str, url: str, **extra: object) -> dict:
    return {
        "ok": True,
        "file": {
            "id": file_id,
            "name": name,
            "mimetype": "application/pdf" if name.endswith(".pdf") else "application/msword",
            "size": 9,
            "url_private_download": url,
            **extra,
        },
    }


FILES_INFO = {
    "F0CASE001": _file_info("F0CASE001", "claim.pdf", PDF_URL),
    "F0CASE002": _file_info("F0CASE002", "exhibit.docx", DOCX_URL),
}
EVENT = {
    "type": "message",
    "subtype": "file_share",
    "channel": "C0LEGAL01",
    "ts": "1700000000.000100",
    "user": "U0LAWYER1",
    "text": "New claim from Acme, hearing on 12 Dec",
    "files": [
        {"id": "F0CASE001", "name": "claim.pdf", "url_private": "https://evil.example/steal"},
        {"id": "F0CASE002", "name": "exhibit.docx"},
    ],
}


class _Harness:
    """Fake Slack API, file host and Drive storage for one test."""

    def __init__(self, test: unittest.TestCase, infos: dict | None = None) -> None:
        self.calls: list[tuple[str, dict, dict]] = []
        self.requests: list[httpx.Request] = []
        self.guarded: list[str] = []
        self.infos = infos if infos is not None else FILES_INFO
        self.messages: list[dict] = []
        self.responses: dict[str, httpx.Response] = {}
        self.root = Path(tempfile.mkdtemp())
        self.db = MagicMock()
        session = MagicMock()
        session.__enter__.return_value = self.db
        client = httpx.Client(transport=httpx.MockTransport(self._serve))
        for patcher in (
            patch.object(slack, "call_slack", side_effect=self._call),
            patch.object(ssrf_guard, "guard_http_url", side_effect=self._guard),
            patch.object(ssrf_guard, "get_guarded_http_client", return_value=client),
            patch.object(file_storage, "_storage_root", return_value=self.root),
            patch("app.db.session.SessionLocal", return_value=session),
        ):
            patcher.start()
            test.addCleanup(patcher.stop)

    def _call(self, _token: str, method: str, payload: dict | None = None, **kwargs: object):
        self.calls.append((method, payload or {}, kwargs))
        if method == "files.info":
            return self.infos[(payload or {})["file"]]
        if method in ("conversations.history", "conversations.replies"):
            return {"ok": True, "messages": self.messages}
        if method == "files.getUploadURLExternal":
            name = (payload or {})["filename"]
            return {
                "ok": True,
                "upload_url": f"https://files.slack.com/upload/v1/{name}",
                "file_id": f"F0UP{len(self.calls):05d}",
            }
        return {"ok": True}

    def _guard(self, url: str, _subject: str = "") -> None:
        self.guarded.append(url)

    def _serve(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        canned = self.responses.get(str(request.url))
        if canned is not None:
            return canned
        return httpx.Response(
            200, content=b"%PDF-case", headers={"content-type": "application/pdf"}
        )

    def methods(self) -> list[str]:
        return [method for method, _payload, _kwargs in self.calls]

    def stored_files(self) -> list[Path]:
        return [path for path in self.root.rglob("*") if path.is_file()]


class TestDownloadFiles(unittest.TestCase):
    def test_a_message_brings_every_file_and_its_text(self) -> None:
        harness = _Harness(self)
        output = run_bot_operation(
            _ctx(
                {"slackOperation": "downloadFile", "slackFile": "$slackEvent.event"},
                {"$slackEvent.event": EVENT},
            ),
            "cred",
            CONFIG,
        )

        self.assertEqual(output["count"], 2)
        self.assertEqual(output["text"], "New claim from Acme, hearing on 12 Dec")
        self.assertEqual((output["channel"], output["ts"]), ("C0LEGAL01", "1700000000.000100"))
        self.assertEqual(output["user"], "U0LAWYER1")
        self.assertEqual([f["filename"] for f in output["files"]], ["claim.pdf", "exhibit.docx"])
        self.assertEqual(output["file_ids"], [f["id"] for f in output["files"]])
        self.assertEqual(output["id"], output["files"][0]["id"])
        self.assertEqual(output["slack_file_id"], "F0CASE001")
        self.assertTrue(output["download_url"].startswith("https://heym.example/"))
        self.assertEqual(len(harness.stored_files()), 2)
        harness.db.commit.assert_called_once()

    def test_the_drive_rows_belong_to_the_run_so_its_agent_can_open_them(self) -> None:
        harness = _Harness(self)
        run_bot_operation(
            _ctx({"slackOperation": "downloadFile", "slackFile": "F0CASE001"}), "cred", CONFIG
        )

        rows = [
            c.args[0] for c in harness.db.add.call_args_list if hasattr(c.args[0], "storage_path")
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].workflow_id, WORKFLOW)
        self.assertEqual(rows[0].owner_id, OWNER)
        self.assertEqual(rows[0].metadata_json, {"slack_file_id": "F0CASE001"})
        self.assertEqual(rows[0].source_node_id, "n1")

    def test_the_token_goes_only_to_the_address_slack_returned(self) -> None:
        harness = _Harness(self)
        run_bot_operation(
            _ctx(
                {"slackOperation": "downloadFile", "slackFile": "$slackEvent.event"},
                {"$slackEvent.event": EVENT},
            ),
            "cred",
            CONFIG,
        )

        fetched = [str(request.url) for request in harness.requests]
        self.assertEqual(fetched, [PDF_URL, DOCX_URL])
        self.assertNotIn("https://evil.example/steal", fetched + harness.guarded)
        for request in harness.requests:
            self.assertEqual(request.headers["authorization"], "Bearer xoxb-test")

    def test_a_download_address_off_slack_is_never_called(self) -> None:
        infos = {"F0CASE001": _file_info("F0CASE001", "claim.pdf", "https://evil.example/x.pdf")}
        harness = _Harness(self, infos)
        with self.assertRaisesRegex(ValueError, "outside files.slack.com"):
            run_bot_operation(
                _ctx({"slackOperation": "downloadFile", "slackFile": "F0CASE001"}), "cred", CONFIG
            )
        self.assertEqual(harness.requests, [])
        self.assertEqual(harness.guarded, [])

    def test_lookalike_slack_hosts_are_refused(self) -> None:
        for url in (
            "http://files.slack.com/a.pdf",
            "https://files.slack.com.evil.example/a.pdf",
            "https://user@files.slack.com/a.pdf",
            "https://files.slack.com:8443/a.pdf",
        ):
            with self.assertRaises(ValueError):
                slack_files.require_slack_file_host(url, "a.pdf")
        slack_files.require_slack_file_host(PDF_URL, "claim.pdf")

    def test_ids_links_objects_and_lists_name_the_same_files(self) -> None:
        values: list[object] = [
            "F0CASE001, F0CASE002",
            "https://acme.slack.com/files/U0LAWYER1/F0CASE001/claim.pdf\nF0CASE002",
            [{"id": "F0CASE001"}, {"slack_file_id": "F0CASE002", "id": str(uuid.uuid4())}],
            {"event": EVENT},
            json.dumps(["F0CASE001", "F0CASE002"]),
        ]
        for value in values:
            with self.subTest(value=value):
                source = slack_files.source_of("xoxb", value)
                self.assertEqual(source.file_ids, ["F0CASE001", "F0CASE002"])

    def test_a_message_link_reads_the_message_first(self) -> None:
        harness = _Harness(self)
        harness.messages = [{**EVENT, "channel": None}]
        source = slack_files.source_of(
            "xoxb", "https://acme.slack.com/archives/C0LEGAL01/p1700000000000100"
        )

        method, payload, kwargs = harness.calls[0]
        self.assertEqual(method, "conversations.history")
        self.assertEqual(payload["latest"], "1700000000.000100")
        self.assertEqual(payload["oldest"], "1700000000.000100")
        self.assertEqual(kwargs, {"read": True})
        self.assertEqual(source.file_ids, ["F0CASE001", "F0CASE002"])
        self.assertEqual(source.channel, "C0LEGAL01")
        self.assertEqual(source.text, EVENT["text"])

    def test_a_reply_link_is_found_in_its_thread(self) -> None:
        harness = _Harness(self)
        reply = {**EVENT, "ts": "1700000500.000200", "thread_ts": "1700000000.000100"}
        harness.messages = [EVENT, reply]
        source = slack_files.source_of(
            "xoxb",
            "https://acme.slack.com/archives/C0LEGAL01/p1700000500000200"
            "?thread_ts=1700000000.000100&cid=C0LEGAL01",
        )

        method, payload, _kwargs = harness.calls[0]
        self.assertEqual(method, "conversations.replies")
        self.assertEqual(payload["ts"], "1700000000.000100")
        self.assertEqual(source.ts, "1700000500.000200")

    def test_a_message_without_files_keeps_its_text(self) -> None:
        harness = _Harness(self)
        message = {**EVENT, "files": []}
        output = run_bot_operation(
            _ctx({"slackOperation": "downloadFile", "slackFile": "$m"}, {"$m": message}),
            "cred",
            CONFIG,
        )

        self.assertEqual(output["count"], 0)
        self.assertEqual(output["files"], [])
        self.assertEqual(output["text"], EVENT["text"])
        self.assertNotIn("files.info", harness.methods())

    def test_input_that_names_nothing_fails(self) -> None:
        _Harness(self)
        with self.assertRaisesRegex(ValueError, "no message or file"):
            run_bot_operation(
                _ctx({"slackOperation": "downloadFile", "slackFile": "the case file"}),
                "cred",
                CONFIG,
            )

    def test_files_slack_cannot_hand_over_fail_by_name(self) -> None:
        cases = {
            "a link to Google Drive": {"is_external": True, "external_type": "Google Drive"},
            "no longer available": {"mode": "hidden_by_limit"},
            "larger than": {"size": 500 * 1024 * 1024},
            "cannot be downloaded": {"url_private_download": "", "url_private": ""},
        }
        for message, extra in cases.items():
            with self.subTest(message=message):
                infos = {"F0CASE001": _file_info("F0CASE001", "claim.pdf", PDF_URL, **extra)}
                harness = _Harness(self, infos)
                with self.assertRaisesRegex(ValueError, message):
                    run_bot_operation(
                        _ctx({"slackOperation": "downloadFile", "slackFile": "F0CASE001"}),
                        "cred",
                        CONFIG,
                    )
                self.assertEqual(harness.requests, [])

    def test_a_sign_in_page_instead_of_the_file_names_the_scope(self) -> None:
        for response in (
            httpx.Response(302, headers={"location": "https://slack.com/signin"}),
            httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
        ):
            with self.subTest(status=response.status_code):
                harness = _Harness(self)
                harness.responses[PDF_URL] = response
                with self.assertRaisesRegex(ValueError, "files:read"):
                    run_bot_operation(
                        _ctx({"slackOperation": "downloadFile", "slackFile": "F0CASE001"}),
                        "cred",
                        CONFIG,
                    )
                self.assertEqual(harness.stored_files(), [])

    def test_a_body_over_the_limit_stops_the_download(self) -> None:
        harness = _Harness(self)
        harness.responses[PDF_URL] = httpx.Response(200, content=b"x" * 2048)
        with patch.object(slack_files, "_CHUNK_BYTES", 512):
            with patch("app.config.settings.file_max_size_mb", 0):
                with self.assertRaisesRegex(ValueError, "larger than"):
                    slack_files.download_files(
                        _ctx({"slackFile": "F0CASE001"}),
                        "xoxb",
                    )
        self.assertEqual(harness.stored_files(), [])

    def test_one_failing_file_leaves_none_behind(self) -> None:
        harness = _Harness(self)
        harness.db.commit.side_effect = RuntimeError("database went away")
        with self.assertRaises(RuntimeError):
            run_bot_operation(
                _ctx(
                    {"slackOperation": "downloadFile", "slackFile": "$e"},
                    {"$e": EVENT},
                ),
                "cred",
                CONFIG,
            )
        harness.db.rollback.assert_called_once()
        self.assertEqual(harness.stored_files(), [])

    def test_a_later_download_failure_stores_nothing(self) -> None:
        harness = _Harness(self)
        harness.responses[DOCX_URL] = httpx.Response(500)
        with self.assertRaisesRegex(ValueError, "HTTP 500"):
            run_bot_operation(
                _ctx({"slackOperation": "downloadFile", "slackFile": "$e"}, {"$e": EVENT}),
                "cred",
                CONFIG,
            )
        harness.db.add.assert_not_called()
        self.assertEqual(harness.stored_files(), [])

    def test_at_most_ten_files(self) -> None:
        _Harness(self)
        ids = ", ".join(f"F0CASE{index:03d}" for index in range(11))
        with self.assertRaisesRegex(ValueError, "at most 10"):
            run_bot_operation(
                _ctx({"slackOperation": "downloadFile", "slackFile": ids}), "cred", CONFIG
            )


def _drive_ref(name: str, content: bytes = b"%PDF-report") -> DriveFileRef:
    path = Path(tempfile.mkdtemp()) / name
    path.write_bytes(content)
    return DriveFileRef(
        id=uuid.uuid4(),
        name=name,
        mime="application/pdf",
        size=len(content),
        created_at=None,
        source="Slack node",
        workflow_id=WORKFLOW,
        shared=False,
        storage_path=path,
    )


class TestSendFiles(unittest.TestCase):
    def _send(self, data: dict, values: dict[str, object] | None = None) -> dict:
        base = {"slackOperation": "sendFile", "slackChannel": "C0LEGAL02"}
        return run_bot_operation(_ctx({**base, **data}, values), "cred", CONFIG)

    def test_files_go_up_and_are_shared_in_one_message(self) -> None:
        harness = _Harness(self)
        refs = [_drive_ref("analysis.pdf"), _drive_ref("claim.pdf")]
        with patch(
            "app.services.file_sandbox.manifest.resolve_files", return_value=refs
        ) as resolve:
            output = self._send(
                {
                    "slackUploadFile": "$files.file_ids",
                    "slackThreadTs": "1700000000.000100",
                    "message": "**Approved** analysis",
                },
                {"$files.file_ids": [str(ref.id) for ref in refs]},
            )

        self.assertEqual(resolve.call_args.args[2], [str(ref.id) for ref in refs])
        self.assertEqual(resolve.call_args.kwargs["scope"].workflow_ids, frozenset({WORKFLOW}))
        tickets = [c for c in harness.calls if c[0] == "files.getUploadURLExternal"]
        self.assertEqual(
            [(payload, kwargs) for _m, payload, kwargs in tickets],
            [
                ({"filename": "analysis.pdf", "length": "11"}, {"form": True}),
                ({"filename": "claim.pdf", "length": "11"}, {"form": True}),
            ],
        )
        complete = [c for c in harness.calls if c[0] == "files.completeUploadExternal"]
        self.assertEqual(len(complete), 1)
        payload = complete[0][1]
        self.assertEqual(payload["channel_id"], "C0LEGAL02")
        self.assertEqual(payload["thread_ts"], "1700000000.000100")
        self.assertEqual(payload["initial_comment"], "*Approved* analysis")
        self.assertEqual(
            [item["title"] for item in payload["files"]], ["analysis.pdf", "claim.pdf"]
        )
        self.assertEqual(output["count"], 2)
        self.assertEqual(output["channel"], "C0LEGAL02")
        self.assertEqual(output["files"][0]["id"], str(refs[0].id))

    def test_the_upload_carries_the_bytes_and_no_token(self) -> None:
        harness = _Harness(self)
        with patch(
            "app.services.file_sandbox.manifest.resolve_files",
            return_value=[_drive_ref("analysis.pdf")],
        ):
            self._send({"slackUploadFile": "drive-id"})

        self.assertEqual(len(harness.requests), 1)
        upload = harness.requests[0]
        self.assertEqual(upload.url.host, "files.slack.com")
        self.assertNotIn("authorization", upload.headers)
        self.assertIn(b"%PDF-report", upload.content)

    def test_a_file_outside_the_run_is_not_sent(self) -> None:
        harness = _Harness(self)
        with patch(
            "app.services.file_sandbox.manifest.resolve_files",
            side_effect=FileAccessError("File not found or not accessible: other-id"),
        ):
            with self.assertRaisesRegex(ValueError, "not found or not accessible"):
                self._send({"slackUploadFile": "other-id"})
        self.assertNotIn("files.getUploadURLExternal", harness.methods())
        self.assertEqual(harness.requests, [])

    def test_an_upload_address_off_slack_is_never_called(self) -> None:
        harness = _Harness(self)
        harness._call = MagicMock(  # type: ignore[method-assign]
            return_value={"ok": True, "upload_url": "https://evil.example/up", "file_id": "F0X1234"}
        )
        with patch.object(slack, "call_slack", side_effect=harness._call):
            with patch(
                "app.services.file_sandbox.manifest.resolve_files",
                return_value=[_drive_ref("analysis.pdf")],
            ):
                with self.assertRaisesRegex(ValueError, "outside files.slack.com"):
                    self._send({"slackUploadFile": "drive-id"})
        self.assertEqual(harness.requests, [])

    def test_files_are_required(self) -> None:
        _Harness(self)
        with self.assertRaisesRegex(ValueError, "Slack files is required"):
            self._send({"slackUploadFile": ""})


class TestFormCalls(unittest.TestCase):
    def test_form_calls_post_a_form_with_the_token_header(self) -> None:
        seen: list[httpx.Request] = []

        def serve(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True, "upload_url": "u", "file_id": "F1"})

        client = httpx.Client(transport=httpx.MockTransport(serve))
        with patch.object(ssrf_guard, "get_guarded_http_client", return_value=client):
            body = slack.call_slack(
                "xoxb-test",
                "files.getUploadURLExternal",
                {"filename": "a.pdf", "length": "3"},
                form=True,
            )

        self.assertEqual(body["file_id"], "F1")
        self.assertEqual(seen[0].headers["content-type"], "application/x-www-form-urlencoded")
        self.assertEqual(seen[0].content, b"filename=a.pdf&length=3")
        self.assertEqual(seen[0].headers["authorization"], "Bearer xoxb-test")
