"""Chat side of the file sandbox: attachments, the tool group, workspace lifetime."""

import json
import os
import tempfile
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import ai_assistant, chat_files, chats
from app.api.ai_assistant import FileAttachment, _build_user_message, _find_injection_field
from app.api.chat_files import ChatFileTools
from app.models.chat_schemas import ChatFileAttachment, MessageCreate
from app.services.file_sandbox import chat_workspaces
from app.services.file_sandbox.manifest import DriveFileRef
from app.services.file_sandbox.scope import RunFileScope
from app.services.file_sandbox.workspace import FileWorkspace
from app.services.llm_trace import LLMTraceContext


class _RootedTestCase(TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for target in (
            "app.services.file_sandbox.workspace.sandbox_root",
            "app.services.file_sandbox.chat_workspaces.sandbox_root",
        ):
            patcher = patch(target, return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class WorkspaceLifetimeTests(_RootedTestCase):
    def _chat(self, user: uuid.UUID, conversation: uuid.UUID) -> FileWorkspace:
        workspace = FileWorkspace.for_chat(user, conversation)
        workspace.ensure()
        return workspace

    def test_deleting_a_chat_deletes_only_its_workspace(self) -> None:
        user = uuid.uuid4()
        doomed = self._chat(user, uuid.uuid4())
        kept = self._chat(user, uuid.uuid4())
        chat_workspaces.delete_chat_workspace(user, uuid.UUID(doomed.base.name))
        self.assertFalse(doomed.exists())
        self.assertTrue(kept.exists())

    def test_clearing_all_chats_leaves_other_users_alone(self) -> None:
        alice, bob = uuid.uuid4(), uuid.uuid4()
        self._chat(alice, uuid.uuid4())
        bobs = self._chat(bob, uuid.uuid4())
        chat_workspaces.delete_all_chat_workspaces(alice)
        self.assertFalse((self.root / "chats" / alice.hex).exists())
        self.assertTrue(bobs.exists())

    def test_sweep_removes_idle_workspaces_and_keeps_recent_ones(self) -> None:
        user = uuid.uuid4()
        idle = self._chat(user, uuid.uuid4())
        meta = json.loads((idle.base / "meta.json").read_text())
        meta["last_used_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        (idle.base / "meta.json").write_text(json.dumps(meta))
        recent = self._chat(user, uuid.uuid4())
        self.assertEqual(chat_workspaces.sweep_idle_chat_workspaces(), 1)
        self.assertFalse(idle.exists())
        self.assertTrue(recent.exists())

    def test_sweep_falls_back_to_mtime_without_meta(self) -> None:
        user = uuid.uuid4()
        orphan = self._chat(user, uuid.uuid4())
        (orphan.base / "meta.json").unlink()
        old = time.time() - 40 * 86400
        os.utime(orphan.base, (old, old))
        self.assertEqual(chat_workspaces.sweep_idle_chat_workspaces(), 1)


class AttachmentTests(IsolatedAsyncioTestCase):
    def _body(self, file_id: uuid.UUID) -> MessageCreate:
        return MessageCreate(
            content="Sum the Amount column",
            credential_id=str(uuid.uuid4()),
            model="gpt-5.5",
            attachment=ChatFileAttachment(name="spoofed.txt", kind="file", file_id=file_id),
        )

    async def test_a_foreign_file_id_is_refused(self) -> None:
        with patch.object(chats, "get_accessible_file", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as caught:
                await chats._attachment_data(MagicMock(), uuid.uuid4(), self._body(uuid.uuid4()))
        self.assertEqual(caught.exception.status_code, 404)

    async def test_name_size_and_mime_come_from_the_drive_row(self) -> None:
        file_id = uuid.uuid4()
        row = SimpleNamespace(id=file_id, filename="q3.xlsx", size_bytes=2048, mime_type="x/y")
        access = SimpleNamespace(file=row)
        with patch.object(chats, "get_accessible_file", AsyncMock(return_value=access)):
            data = await chats._attachment_data(MagicMock(), uuid.uuid4(), self._body(file_id))
        self.assertEqual(
            data,
            {
                "name": "q3.xlsx",
                "kind": "file",
                "content": "",
                "file_id": str(file_id),
                "size": 2048,
                "mime": "x/y",
            },
        )
        self.assertEqual(FileAttachment.model_validate(data).injection_value(), str(file_id))

    async def test_text_attachments_pass_through(self) -> None:
        body = MessageCreate(
            content="hi",
            credential_id="c",
            model="m",
            attachment=ChatFileAttachment(name="a.txt", kind="text", content="hello"),
        )
        data = await chats._attachment_data(MagicMock(), uuid.uuid4(), body)
        self.assertEqual(data["content"], "hello")

    def test_drive_file_message_never_carries_content(self) -> None:
        attachment = FileAttachment(
            name="q3.xlsx", kind="file", file_id=uuid.uuid4(), size=10, content="SHOULD NOT"
        )
        message = _build_user_message("Sum it", attachment)
        self.assertIn("[ATTACHED DRIVE FILE: q3.xlsx", message["content"])
        self.assertNotIn("SHOULD NOT", message["content"])

    def test_text_and_images_still_go_to_their_fields(self) -> None:
        self.assertEqual(_find_injection_field(["query", "text"], "text"), "text")
        self.assertEqual(_find_injection_field(["text", "image_url"], "image"), "image_url")


class FeedSampleFileTests(IsolatedAsyncioTestCase):
    """Chat hands its file to the File Upload trigger, never to a text field."""

    def _workflow(self, *nodes: dict) -> SimpleNamespace:
        return SimpleNamespace(nodes=list(nodes))

    async def test_without_an_upload_trigger_nothing_is_passed(self) -> None:
        workflow = self._workflow({"id": "s", "type": "textInput", "data": {"label": "start"}})
        lookup = AsyncMock()
        with patch.object(ai_assistant, "get_accessible_file", lookup):
            nodes, scope, note = await ai_assistant._feed_sample_file(
                MagicMock(), uuid.uuid4(), workflow, uuid.uuid4(), "http://h"
            )
        lookup.assert_not_awaited()
        self.assertIs(nodes, workflow.nodes)
        self.assertIsNone(scope)
        self.assertFalse(note["passed"])
        self.assertIn("fileUploadTrigger", note["note"])

    async def test_the_file_reaches_the_trigger_and_only_it_opens(self) -> None:
        file_id = uuid.uuid4()
        trigger = {"id": "t", "type": "fileUploadTrigger", "data": {"label": "Upload"}}
        workflow = self._workflow(trigger, {"id": "c", "type": "code", "data": {}})
        row = SimpleNamespace(id=file_id, filename="q3.xlsx", mime_type="x/y", size_bytes=4)
        found = AsyncMock(return_value=SimpleNamespace(file=row))
        with patch.object(ai_assistant, "get_accessible_file", found):
            nodes, scope, note = await ai_assistant._feed_sample_file(
                MagicMock(), uuid.uuid4(), workflow, file_id, "http://h/"
            )
        fed = next(node for node in nodes if node["id"] == "t")["data"]["_initial_inputs"]
        self.assertEqual(
            fed["file"],
            {
                "id": str(file_id),
                "name": "q3.xlsx",
                "mime": "x/y",
                "size": 4,
                "download_url": f"http://h/api/files/{file_id}",
            },
        )
        self.assertNotIn("_initial_inputs", trigger["data"])
        self.assertEqual(scope, RunFileScope(file_ids=frozenset({file_id})))
        self.assertEqual(note, {"passed": True, "trigger": "Upload", "name": "q3.xlsx"})

    async def test_a_file_the_user_cannot_reach_is_not_passed(self) -> None:
        workflow = self._workflow({"id": "t", "type": "fileUploadTrigger", "data": {}})
        with patch.object(ai_assistant, "get_accessible_file", AsyncMock(return_value=None)):
            nodes, scope, note = await ai_assistant._feed_sample_file(
                MagicMock(), uuid.uuid4(), workflow, uuid.uuid4(), "http://h"
            )
        self.assertIs(nodes, workflow.nodes)
        self.assertIsNone(scope)
        self.assertFalse(note["passed"])


class ChatFileToolsTests(_RootedTestCase):
    def test_audits_each_new_mount_from_the_api_layer(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="a@example.com")
        tools = ChatFileTools(user=user, conversation_id=uuid.uuid4())
        ref = DriveFileRef(
            id=uuid.uuid4(),
            name="q3.xlsx",
            mime=None,
            size=1,
            created_at=None,
            source=None,
            workflow_id=None,
            shared=True,
            storage_path=Path("/nowhere"),
        )
        with patch.object(chat_files, "audit") as audit:
            tools._audit_mounts([ref])
        kwargs = audit.call_args.kwargs
        self.assertEqual(kwargs["action"], "drive.chat_mount")
        self.assertEqual(kwargs["target_id"], ref.id)
        self.assertTrue(kwargs["shared"])

    def test_workspace_block_describes_inputs_and_scratch(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="a@example.com")
        tools = ChatFileTools(user=user, conversation_id=uuid.uuid4())
        self.assertEqual(tools.workspace_block(), "")
        tools.workspace.ensure()
        (tools.workspace.work_dir / "sales.pkl").write_bytes(b"xx")
        self.assertIn("/work/sales.pkl (2 bytes)", tools.workspace_block())

    def test_long_code_is_clipped_for_display(self) -> None:
        shown = ChatFileTools.display_args("run_python", {"code": "x" * 9000, "files": ["a"]})
        self.assertLess(len(shown["code"]), 4100)
        self.assertEqual(shown["files"], ["a"])


def _tool_call(name: str, arguments: dict[str, Any], call_id: str) -> MagicMock:
    call = MagicMock()
    call.id = call_id
    call.function.name = name
    call.function.arguments = json.dumps(arguments)
    message = MagicMock(content=None, tool_calls=[call])
    usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    return MagicMock(choices=[MagicMock(message=message)], usage=usage)


def _text(text: str) -> MagicMock:
    usage = MagicMock(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content=text, tool_calls=None))], usage=usage
    )


class StreamDispatchTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(ai_assistant, "record_llm_trace"))
        self.stack.enter_context(patch.object(ai_assistant, "record_run_history"))

    async def asyncTearDown(self) -> None:
        self.stack.close()

    async def test_file_tools_are_offered_and_dispatched(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="a@example.com", user_rules=None)
        files = ChatFileTools(user=user, conversation_id=uuid.uuid4())
        files.toolbox = MagicMock()
        files.toolbox.call.return_value = {
            "untrusted_file_content": True,
            "summary": {"kind": "xlsx"},
            "file": {"name": "q3.xlsx"},
        }
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _tool_call("inspect_file", {"file": "q3.xlsx"}, "c1"),
            _text("It has one sheet."),
        ]
        db = MagicMock()
        db.commit = AsyncMock()
        events = []
        async for chunk in ai_assistant.stream_dashboard_chat(
            client,
            "gpt-5.5",
            "system",
            [{"role": "user", "content": "What is in q3.xlsx?"}],
            db,
            user,
            "OpenAI",
            "http://localhost",
            LLMTraceContext(
                user_id=user.id,
                credential_id=uuid.uuid4(),
                node_label="Dashboard Chat",
                source="dashboard_chat",
                session_id="c",
            ),
            Event(),
            files=files,
        ):
            if chunk.startswith("data: "):
                events.append(json.loads(chunk[6:].strip()))
        offered = [
            t["function"]["name"]
            for t in client.chat.completions.create.call_args_list[0].kwargs["tools"]
        ]
        self.assertIn("inspect_file", offered)
        self.assertIn("clear_workspace", offered)
        files.toolbox.call.assert_called_once_with("inspect_file", {"file": "q3.xlsx"})
        start = next(e for e in events if e["type"] == "tool_start")
        self.assertEqual(start["label"], 'Inspecting "q3.xlsx"...')
        end = next(e for e in events if e["type"] == "tool_end")
        self.assertEqual(end["response_summary"], "q3.xlsx · xlsx")
        self.assertEqual(end["status"], "success")


class ChatUploadSourceTests(IsolatedAsyncioTestCase):
    async def test_chat_uploads_are_labelled_chat_in_drive(self) -> None:
        import io

        from fastapi import UploadFile

        from app.api import files as files_api

        row = SimpleNamespace(id=uuid.uuid4(), filename="q3.xlsx", mime_type="x/y")
        db = MagicMock()
        db.commit = AsyncMock()
        with (
            patch.object(files_api, "build_public_base_url", return_value="https://heym.run"),
            patch.object(files_api, "read_upload_file_limited", AsyncMock(return_value=b"x")),
            patch.object(files_api, "store_file", AsyncMock(return_value=row)) as store,
            patch.object(files_api, "create_access_token", AsyncMock()),
            patch.object(files_api, "audit"),
            patch.object(files_api, "_refresh_file_response_relations", AsyncMock()),
            patch.object(files_api, "_file_to_response", return_value="ok"),
        ):
            await files_api.upload_file(
                request=MagicMock(),
                file=UploadFile(filename="q3.xlsx", file=io.BytesIO(b"x")),
                share_with_my_teams=False,
                source="chat",
                user=SimpleNamespace(id=uuid.uuid4()),
                db=db,
            )
        self.assertEqual(store.call_args.kwargs["source_node_label"], "Chat")


class DeleteHookTests(IsolatedAsyncioTestCase):
    async def test_deleting_a_conversation_deletes_its_workspace(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        conversation_id = uuid.uuid4()
        db = MagicMock()
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        with (
            patch.object(chats, "_get_conversation_or_404", AsyncMock(return_value=object())),
            patch.object(chats, "delete_chat_workspace") as remove,
        ):
            await chats.delete_conversation(conversation_id, current_user=user, db=db)
        remove.assert_called_once_with(user.id, conversation_id)

    async def test_clearing_conversations_deletes_all_workspaces(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        with patch.object(chats, "delete_all_chat_workspaces") as remove:
            await chats.clear_conversations(current_user=user, db=db)
        remove.assert_called_once_with(user.id)


if __name__ == "__main__":
    import unittest

    unittest.main()
