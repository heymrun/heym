"""Unit tests for Skill Builder prompt and SSE behavior."""

import base64
import io
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

from app.api.skill_builder import (
    SkillBuilderAttachment,
    SkillBuilderFile,
    SkillBuilderRequest,
    SkillBuilderSkill,
    build_skill_builder_prompt,
    run_skill_builder,
)
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
