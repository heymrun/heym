"""Unit tests for Skill Builder prompt and SSE behavior."""

import base64
import io
import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zipfile import ZipFile

from app.api.skill_builder import (
    SkillBuilderAttachment,
    SkillBuilderFile,
    SkillBuilderRequest,
    SkillBuilderSkill,
    _initial_skill_files,
    apply_skill_file_tool,
    build_skill_builder_prompt,
    run_skill_builder,
    skill_builder_stream,
)
from app.db.models import CredentialType
from app.services.llm_trace import LLMTraceContext


def _make_docx_base64(document_xml: str) -> str:
    """Build a minimal DOCX-like zip containing word/document.xml."""

    buf = io.BytesIO()
    with ZipFile(buf, mode="w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class BuildSkillBuilderPromptTests(unittest.TestCase):
    """Verify prompt construction for new and edit flows."""

    def test_new_skill_prompt_contains_dsl_and_rules(self) -> None:
        prompt = build_skill_builder_prompt(None)

        self.assertIn("SKILL.md", prompt)
        self.assertIn("def execute(params: dict, files: dict) -> dict:", prompt)
        self.assertIn("reportlab", prompt)
        self.assertIn("NEVER embed fonts", prompt)
        self.assertIn("NEW skill", prompt)
        self.assertIn("only `.md` and `.py` files", prompt)
        self.assertIn("English only", prompt)

    def test_edit_skill_prompt_contains_existing_file_contents(self) -> None:
        skill = SkillBuilderSkill(
            name="pdf-generator",
            files=[
                SkillBuilderFile(
                    path="SKILL.md",
                    content="---\nname: pdf-generator\n---\nGenerates PDFs.",
                ),
                SkillBuilderFile(
                    path="main.py",
                    content="def execute(params, files):\n    return {'ok': True}\n",
                ),
            ],
        )

        prompt = build_skill_builder_prompt(skill)

        self.assertIn("pdf-generator", prompt)
        self.assertIn("Generates PDFs.", prompt)
        self.assertIn("main.py", prompt)
        self.assertIn("def execute(params, files)", prompt)

    def test_edit_skill_prompt_excludes_non_markdown_and_non_python_files(self) -> None:
        skill = SkillBuilderSkill(
            name="translator",
            files=[
                SkillBuilderFile(path="SKILL.md", content="---\nname: translator\n---"),
                SkillBuilderFile(
                    path="main.py", content="def execute(params, files):\n    return {}\n"
                ),
                SkillBuilderFile(path="notes.txt", content="should not be editable"),
            ],
        )

        prompt = build_skill_builder_prompt(skill)

        self.assertIn("SKILL.md", prompt)
        self.assertIn("main.py", prompt)
        self.assertNotIn("notes.txt", prompt)
        self.assertIn("excluded from the AI editing context", prompt)

    def test_edit_skill_prompt_lists_non_editable_attachment_paths(self) -> None:
        skill = SkillBuilderSkill(
            name="pdf-reader",
            files=[
                SkillBuilderFile(path="SKILL.md", content="---\nname: pdf-reader\n---"),
                SkillBuilderFile(
                    path="assets/main.py",
                    content=(
                        "from pathlib import Path\n"
                        "def execute(params, files):\n"
                        "    return {'size': (Path(__file__).parent / 'hello.pdf').stat().st_size}\n"
                    ),
                ),
            ],
            attachments=[
                SkillBuilderAttachment(
                    path="assets/hello.pdf",
                    encoding="base64",
                    mime_type="application/pdf",
                    size_bytes=128,
                )
            ],
        )

        prompt = build_skill_builder_prompt(skill)

        self.assertIn("assets/main.py", prompt)
        self.assertIn("assets/hello.pdf", prompt)
        self.assertIn("application/pdf", prompt)
        self.assertIn("Do not include these non-editable files", prompt)
        self.assertIn("If you move a Python file", prompt)

    def test_edit_skill_prompt_includes_docx_table_context_when_content_is_present(self) -> None:
        document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r/></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>Surname</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r/></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
        skill = SkillBuilderSkill(
            name="docx-form-filler",
            files=[
                SkillBuilderFile(path="SKILL.md", content="---\nname: docx-form-filler\n---"),
                SkillBuilderFile(
                    path="main.py",
                    content="def execute(params, files):\n    return {}\n",
                ),
            ],
            attachments=[
                SkillBuilderAttachment(
                    path="fill.docx",
                    encoding="base64",
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    size_bytes=512,
                    content=_make_docx_base64(document_xml),
                )
            ],
        )

        prompt = build_skill_builder_prompt(skill)

        self.assertIn("Included Attachment Context", prompt)
        self.assertIn("Table 1:", prompt)
        self.assertIn("Row 1: Name | <EMPTY runs=1>", prompt)
        self.assertIn("`Name` -> adjacent empty cell", prompt)
        self.assertIn("update it to write the value into the adjacent empty cell", prompt)

    def test_large_text_attachment_context_is_not_omitted_by_two_mb_gate(self) -> None:
        large_text = "alpha " * 400_000
        skill = SkillBuilderSkill(
            name="large-context",
            files=[SkillBuilderFile(path="SKILL.md", content="---\nname: large-context\n---")],
            attachments=[
                SkillBuilderAttachment(
                    path="large.txt",
                    encoding="text",
                    mime_type="text/plain",
                    size_bytes=len(large_text.encode()),
                    content=large_text,
                )
            ],
        )

        prompt = build_skill_builder_prompt(skill)

        self.assertIn("large.txt", prompt)
        self.assertIn("alpha alpha", prompt)
        self.assertNotIn("larger than 2 MB", prompt)
        self.assertNotIn("Content context omitted", prompt)

    def test_message_pdf_attachment_context_is_extracted(self) -> None:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Quarterly report text"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        attachment = SkillBuilderAttachment(
            path="report.pdf",
            encoding="base64",
            mime_type="application/pdf",
            size_bytes=128,
            content=base64.b64encode(b"%PDF fake").decode("ascii"),
        )

        with patch("pypdf.PdfReader", return_value=mock_reader):
            prompt = build_skill_builder_prompt(None, [attachment])

        self.assertIn("Uploaded Files For This Request", prompt)
        self.assertIn("report.pdf", prompt)
        self.assertIn("Page 1:", prompt)
        self.assertIn("Quarterly report text", prompt)


class RunSkillBuilderTests(unittest.IsolatedAsyncioTestCase):
    """Verify emitted SSE events for the skill builder loop."""

    async def _collect_events(self, generator) -> list[dict]:
        events: list[dict] = []
        async for line in generator:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    def _make_trace_context(self) -> LLMTraceContext:
        return LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            workflow_id=None,
            node_label="Skill Builder",
            source="skill_builder",
        )

    async def test_emits_text_chunk_and_done_without_tool_calls(self) -> None:
        fake_message = SimpleNamespace(content="Here is your skill.", tool_calls=None)
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=fake_message)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_response

        request = SkillBuilderRequest(
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            message="Create a hello world skill.",
        )

        with patch("app.api.skill_builder.record_llm_trace") as record_trace:
            events = await self._collect_events(
                run_skill_builder(fake_client, request, self._make_trace_context(), "OpenAI")
            )

        event_types = [event["type"] for event in events]
        self.assertIn("text_chunk", event_types)
        self.assertEqual(events[-1]["type"], "done")
        record_trace.assert_called_once()
        trace_kwargs = record_trace.call_args.kwargs
        self.assertEqual(trace_kwargs["context"].node_label, "Skill Builder")
        self.assertEqual(trace_kwargs["context"].source, "skill_builder")

    async def test_records_error_trace_with_skill_builder_label(self) -> None:
        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = RuntimeError("skill failed")

        request = SkillBuilderRequest(
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            message="Create a hello world skill.",
        )

        with patch("app.api.skill_builder.record_llm_trace") as record_trace:
            events = await self._collect_events(
                run_skill_builder(fake_client, request, self._make_trace_context(), "OpenAI")
            )

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["message"], "skill failed")
        record_trace.assert_called_once()
        trace_kwargs = record_trace.call_args.kwargs
        self.assertEqual(trace_kwargs["context"].node_label, "Skill Builder")
        self.assertEqual(trace_kwargs["context"].source, "skill_builder")
        self.assertEqual(trace_kwargs["error"], "skill failed")

    async def test_emits_skill_files_update_and_done_when_tool_is_called(self) -> None:
        files_payload = [
            {"path": "SKILL.md", "content": "---\nname: hello-skill\n---"},
            {
                "path": "main.py",
                "content": "def execute(params, files):\n    return {'msg': 'hi'}\n",
            },
        ]
        tool_call = SimpleNamespace(
            id="tool-call-1",
            function=SimpleNamespace(
                name="set_skill_files",
                arguments=json.dumps({"files": files_payload}),
            ),
        )
        first_response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))
            ],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
        second_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Done! Skill is ready.", tool_calls=None)
                )
            ],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [first_response, second_response]

        request = SkillBuilderRequest(
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            message="Build a hello skill.",
        )

        with patch("app.api.skill_builder.record_llm_trace"):
            events = await self._collect_events(
                run_skill_builder(fake_client, request, self._make_trace_context(), "OpenAI")
            )

        event_types = [event["type"] for event in events]
        self.assertIn("skill_files_update", event_types)
        self.assertIn("text_chunk", event_types)
        self.assertEqual(events[-1]["type"], "done")

        update_event = next(event for event in events if event["type"] == "skill_files_update")
        self.assertEqual(update_event["files"], files_payload)

    async def test_ignores_non_markdown_and_non_python_tool_files(self) -> None:
        files_payload = [
            {"path": "SKILL.md", "content": "---\nname: hello-skill\n---"},
            {"path": "notes.txt", "content": "ignore me"},
            {
                "path": "main.py",
                "content": "def execute(params, files):\n    return {'msg': 'hi'}\n",
            },
        ]
        tool_call = SimpleNamespace(
            id="tool-call-1",
            function=SimpleNamespace(
                name="set_skill_files",
                arguments=json.dumps({"files": files_payload}),
            ),
        )
        first_response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))
            ],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
        second_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Done.", tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [first_response, second_response]

        request = SkillBuilderRequest(
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            message="Build a hello skill.",
        )

        with patch("app.api.skill_builder.record_llm_trace"):
            events = await self._collect_events(
                run_skill_builder(fake_client, request, self._make_trace_context(), "OpenAI")
            )

        update_event = next(event for event in events if event["type"] == "skill_files_update")
        self.assertEqual(
            update_event["files"],
            [
                {"path": "SKILL.md", "content": "---\nname: hello-skill\n---"},
                {
                    "path": "main.py",
                    "content": "def execute(params, files):\n    return {'msg': 'hi'}\n",
                },
            ],
        )

        second_call_messages = fake_client.chat.completions.create.call_args_list[1].kwargs[
            "messages"
        ]
        self.assertEqual(second_call_messages[-1]["role"], "tool")
        self.assertIn("only accepts `.md` and `.py` files", second_call_messages[-1]["content"])

    async def test_ignores_macos_metadata_tool_files(self) -> None:
        files_payload = [
            {"path": "SKILL.md", "content": "---\nname: hello-skill\n---"},
            {"path": "__MACOSX/._main.py", "content": "ignore me"},
            {"path": ".DS_Store", "content": "ignore me"},
            {
                "path": "nested/../main.py",
                "content": "def execute(params, files):\n    return {'msg': 'hi'}\n",
            },
        ]
        tool_call = SimpleNamespace(
            id="tool-call-1",
            function=SimpleNamespace(
                name="set_skill_files",
                arguments=json.dumps({"files": files_payload}),
            ),
        )
        first_response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))
            ],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
        second_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Done.", tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [first_response, second_response]

        request = SkillBuilderRequest(
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            message="Build a hello skill.",
        )

        with patch("app.api.skill_builder.record_llm_trace"):
            events = await self._collect_events(
                run_skill_builder(fake_client, request, self._make_trace_context(), "OpenAI")
            )

        update_event = next(event for event in events if event["type"] == "skill_files_update")
        self.assertEqual(
            update_event["files"],
            [
                {"path": "SKILL.md", "content": "---\nname: hello-skill\n---"},
                {
                    "path": "nested/main.py",
                    "content": "def execute(params, files):\n    return {'msg': 'hi'}\n",
                },
            ],
        )


BIG_FONT_MODULE = "FONT_DATA = '" + ("QUJD" * 25_000) + "'\n"


def _tool_call(call_id: str, name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _response(content: str | None, tool_calls: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
    )


def _existing_skill() -> SkillBuilderSkill:
    return SkillBuilderSkill(
        name="translate-to-german",
        files=[
            SkillBuilderFile(path="SKILL.md", content="---\nname: translate-to-german\n---\n"),
            SkillBuilderFile(
                path="main.py",
                content="OUT = 'translation.de.pdf'\nDOCX = 'translation.de.docx'\n",
            ),
            SkillBuilderFile(path="embedded_font.py", content=BIG_FONT_MODULE),
        ],
    )


class SkillFileToolTests(unittest.TestCase):
    """Partial writes, exact replacements and deletes against the turn's files."""

    def _files(self) -> dict[str, str]:
        return _initial_skill_files(_existing_skill())

    def test_set_skill_files_keeps_files_it_leaves_out(self) -> None:
        files = self._files()

        outcome = apply_skill_file_tool(
            files,
            "set_skill_files",
            json.dumps({"files": [{"path": "SKILL.md", "content": "---\nname: x\n---\n"}]}),
        )

        self.assertEqual(outcome.changed_paths, ["SKILL.md"])
        self.assertEqual(files["SKILL.md"], "---\nname: x\n---\n")
        self.assertEqual(files["embedded_font.py"], BIG_FONT_MODULE)
        self.assertIn("main.py", files)
        self.assertIn("Other files are unchanged", outcome.result)

    def test_set_skill_files_with_unchanged_content_changes_nothing(self) -> None:
        files = self._files()

        outcome = apply_skill_file_tool(
            files,
            "set_skill_files",
            json.dumps({"files": [{"path": "main.py", "content": files["main.py"]}]}),
        )

        self.assertEqual(outcome.changed_paths, [])
        self.assertIn("nothing changed", outcome.result)

    def test_delete_paths_renames_a_file_but_never_removes_skill_md(self) -> None:
        files = self._files()

        outcome = apply_skill_file_tool(
            files,
            "set_skill_files",
            json.dumps(
                {
                    "files": [{"path": "scripts/main.py", "content": files["main.py"]}],
                    "delete_paths": ["main.py", "SKILL.md", "missing.py"],
                }
            ),
        )

        self.assertEqual(outcome.changed_paths, ["scripts/main.py"])
        self.assertEqual(outcome.deleted_paths, ["main.py"])
        self.assertNotIn("main.py", files)
        self.assertIn("SKILL.md", files)
        self.assertIn("`SKILL.md` cannot be deleted", outcome.result)
        self.assertIn("`missing.py` was not deleted", outcome.result)

    def test_edit_replaces_only_the_matched_text(self) -> None:
        files = self._files()

        outcome = apply_skill_file_tool(
            files,
            "edit_skill_file",
            json.dumps(
                {
                    "path": "main.py",
                    "edits": [
                        {"old_string": "translation.de.pdf", "new_string": "translation.en.pdf"},
                        {"old_string": "translation.de.docx", "new_string": "translation.en.docx"},
                    ],
                }
            ),
        )

        self.assertEqual(outcome.changed_paths, ["main.py"])
        self.assertEqual(
            files["main.py"], "OUT = 'translation.en.pdf'\nDOCX = 'translation.en.docx'\n"
        )
        self.assertEqual(files["embedded_font.py"], BIG_FONT_MODULE)

    def test_edit_is_all_or_nothing_when_a_later_edit_misses(self) -> None:
        files = self._files()
        before = files["main.py"]

        outcome = apply_skill_file_tool(
            files,
            "edit_skill_file",
            json.dumps(
                {
                    "path": "main.py",
                    "edits": [
                        {"old_string": "translation.de.pdf", "new_string": "translation.en.pdf"},
                        {"old_string": "not in the file", "new_string": "x"},
                    ],
                }
            ),
        )

        self.assertEqual(outcome.changed_paths, [])
        self.assertEqual(files["main.py"], before)
        self.assertIn("edit 2", outcome.result)
        self.assertIn("was not found", outcome.result)

    def test_edit_refuses_an_ambiguous_match_unless_replace_all(self) -> None:
        files = self._files()

        refused = apply_skill_file_tool(
            files,
            "edit_skill_file",
            json.dumps(
                {"path": "main.py", "edits": [{"old_string": ".de.", "new_string": ".en."}]}
            ),
        )
        self.assertEqual(refused.changed_paths, [])
        self.assertIn("occurs 2 times", refused.result)

        applied = apply_skill_file_tool(
            files,
            "edit_skill_file",
            json.dumps(
                {
                    "path": "main.py",
                    "edits": [{"old_string": ".de.", "new_string": ".en.", "replace_all": True}],
                }
            ),
        )
        self.assertEqual(applied.changed_paths, ["main.py"])
        self.assertNotIn(".de.", files["main.py"])

    def test_edit_refuses_missing_and_non_editable_files(self) -> None:
        files = self._files()
        edit = [{"old_string": "a", "new_string": "b"}]

        missing = apply_skill_file_tool(
            files, "edit_skill_file", json.dumps({"path": "helper.py", "edits": edit})
        )
        not_editable = apply_skill_file_tool(
            files, "edit_skill_file", json.dumps({"path": "font.ttf", "edits": edit})
        )

        self.assertIn("does not exist", missing.result)
        self.assertIn("only edits `.md` and `.py` files", not_editable.result)
        self.assertEqual(files, self._files())

    def test_invalid_arguments_change_nothing(self) -> None:
        files = self._files()

        outcome = apply_skill_file_tool(files, "edit_skill_file", "{not json")

        self.assertEqual(outcome.changed_paths, [])
        self.assertIn("not a valid JSON object", outcome.result)
        self.assertEqual(files, self._files())


class PartialSkillEditPromptTests(unittest.TestCase):
    """The prompt asks for targeted changes instead of the whole file set."""

    def test_edit_prompt_offers_targeted_edits(self) -> None:
        prompt = build_skill_builder_prompt(_existing_skill())

        self.assertIn("edit_skill_file", prompt)
        self.assertIn("never resend a file you did not change", prompt)
        self.assertNotIn("ALL editable", prompt)


class RunSkillBuilderPartialEditTests(unittest.IsolatedAsyncioTestCase):
    """The loop offers both file tools and reports the whole set plus what changed."""

    async def _collect_events(self, generator) -> list[dict]:
        events: list[dict] = []
        async for line in generator:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    def _trace_context(self) -> LLMTraceContext:
        return LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            workflow_id=None,
            node_label="Skill Builder",
            source="skill_builder",
        )

    async def test_edit_emits_whole_set_with_changed_paths(self) -> None:
        edit_call = _tool_call(
            "call-1",
            "edit_skill_file",
            {
                "path": "main.py",
                "edits": [{"old_string": "translation.de.pdf", "new_string": "translation.en.pdf"}],
            },
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [
            _response(None, [edit_call]),
            _response("Renamed the PDF output."),
        ]
        request = SkillBuilderRequest(
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            message="Translate to English instead.",
            existing_skill=_existing_skill(),
        )

        with patch("app.api.skill_builder.record_llm_trace"):
            events = await self._collect_events(
                run_skill_builder(fake_client, request, self._trace_context(), "OpenAI")
            )

        tools = fake_client.chat.completions.create.call_args_list[0].kwargs["tools"]
        self.assertEqual(
            [tool["function"]["name"] for tool in tools], ["set_skill_files", "edit_skill_file"]
        )
        update = next(event for event in events if event["type"] == "skill_files_update")
        self.assertEqual(update["changed_paths"], ["main.py"])
        self.assertEqual(update["deleted_paths"], [])
        by_path = {file["path"]: file["content"] for file in update["files"]}
        self.assertEqual(set(by_path), {"SKILL.md", "main.py", "embedded_font.py"})
        self.assertIn("translation.en.pdf", by_path["main.py"])
        self.assertEqual(by_path["embedded_font.py"], BIG_FONT_MODULE)
        self.assertEqual(events[-1]["type"], "done")

    async def test_refused_edit_emits_no_update_and_tells_the_model(self) -> None:
        edit_call = _tool_call(
            "call-1",
            "edit_skill_file",
            {"path": "main.py", "edits": [{"old_string": "absent", "new_string": "x"}]},
        )
        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [
            _response(None, [edit_call]),
            _response("I could not find that text."),
        ]
        request = SkillBuilderRequest(
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            message="Change it.",
            existing_skill=_existing_skill(),
        )

        with patch("app.api.skill_builder.record_llm_trace"):
            events = await self._collect_events(
                run_skill_builder(fake_client, request, self._trace_context(), "OpenAI")
            )

        self.assertNotIn("skill_files_update", [event["type"] for event in events])
        second_messages = fake_client.chat.completions.create.call_args_list[1].kwargs["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertIn("Nothing was changed", second_messages[-1]["content"])


class SkillBuilderKeepaliveTests(unittest.IsolatedAsyncioTestCase):
    """A slow model call must not leave the connection silent long enough for a proxy 502."""

    async def test_stream_sends_keepalives_while_the_model_call_blocks(self) -> None:
        def slow_create(**_kwargs: object) -> SimpleNamespace:
            time.sleep(0.3)
            return _response("Done.")

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = slow_create
        credential = SimpleNamespace(
            id=uuid.uuid4(), type=CredentialType.openai, encrypted_config="x"
        )
        request = SkillBuilderRequest(
            credential_id=credential.id, model="gpt-4o", message="Build a hello skill."
        )
        user = SimpleNamespace(id=uuid.uuid4())

        with (
            patch(
                "app.api.skill_builder.get_credential_for_user",
                AsyncMock(return_value=credential),
            ),
            patch("app.api.skill_builder.decrypt_config", return_value={}),
            patch(
                "app.api.skill_builder.resolve_model_binding",
                side_effect=lambda _c, _cfg, model, **kw: (
                    fake_client,
                    "OpenAI",
                    model,
                    kw["trace_context"],
                ),
            ),
            patch("app.api.skill_builder.record_llm_trace"),
            patch("app.api.skill_builder.SKILL_BUILDER_SSE_KEEPALIVE_SECONDS", 0.05),
        ):
            response = await skill_builder_stream(request, user, AsyncMock())
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertIn(": keepalive\n\n", chunks)
        self.assertLess(chunks.index(": keepalive\n\n"), len(chunks) - 1)
        self.assertTrue(chunks[-1].startswith("data: "))
        self.assertEqual(json.loads(chunks[-1][6:])["type"], "done")
