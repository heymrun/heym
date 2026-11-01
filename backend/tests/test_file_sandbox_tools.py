"""File tools: toolbox dispatch, Agent node wiring and the Code node's Files field."""

import tempfile
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.code_python_executor import CodeExecutionResult
from app.services.file_sandbox import detect, tools
from app.services.file_sandbox.executor import SandboxOutcome
from app.services.file_sandbox.instructions import agent_file_instructions
from app.services.file_sandbox.manifest import DriveFileRef, FileAccessError
from app.services.file_sandbox.scope import RunFileScope
from app.services.file_sandbox.tools import (
    CLEAR_WORKSPACE_TOOL,
    FileToolbox,
    agent_tool_defs,
    tool_schemas,
)
from app.services.file_sandbox.workspace import FileWorkspace
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import code_node
from app.services.workflow_executor import WorkflowExecutor


class _Session:
    def __enter__(self) -> "_Session":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _ref(path: Path, name: str = "q3.xlsx") -> DriveFileRef:
    return DriveFileRef(
        id=uuid.uuid4(),
        name=name,
        mime="application/vnd.ms-excel",
        size=path.stat().st_size,
        created_at=datetime.now(timezone.utc),
        source="Chat",
        workflow_id=None,
        shared=False,
        storage_path=path,
    )


class ToolboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.source = self.dir / "q3.xlsx"
        self.source.write_bytes(b"xlsx")
        self.ref = _ref(self.source)
        self.actor = uuid.uuid4()
        self.workspace = FileWorkspace(self.dir / "ws", owner_id=self.actor)
        self.mounted: list[list[DriveFileRef]] = []
        self.toolbox = FileToolbox(
            self.workspace,
            self.actor,
            source_label="Chat",
            include_clear=True,
            on_mount=self.mounted.append,
        )
        patches = [
            patch.object(FileToolbox, "_session", return_value=_Session()),
            patch.object(tools, "resolve_files", return_value=[self.ref]),
            patch.object(tools, "still_accessible", side_effect=lambda _db, _u, ids: set(ids)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_inspect_mounts_once_and_marks_content_untrusted(self) -> None:
        outcome = SandboxOutcome(success=True, result={"kind": "xlsx"})
        with patch.object(tools, "run_in_sandbox", return_value=outcome) as run:
            first = self.toolbox.call("inspect_file", {"file": "q3.xlsx", "sheet": "Sales"})
            self.toolbox.call("inspect_file", {"file": "q3.xlsx"})
        self.assertTrue(first["untrusted_file_content"])
        self.assertEqual(first["summary"], {"kind": "xlsx"})
        payload = run.call_args_list[0].args[1]
        self.assertEqual(payload["mode"], "inspect")
        self.assertEqual(payload["options"], {"sheet": "Sales"})
        self.assertEqual(payload["target"]["path"], f"/input/{self.ref.id.hex}/q3.xlsx")
        self.assertEqual(len(self.mounted), 1, "a second call must not re-mount or re-audit")

    def test_run_stores_outputs_without_exposing_tokens(self) -> None:
        def _run(workspace: FileWorkspace, _payload: dict) -> SandboxOutcome:
            (workspace.out_dir / "total.csv").write_text("total\n45\n")
            return SandboxOutcome(success=True, stdout="45\n")

        stored = [{"id": "f1", "name": "total.csv", "download_path": "/api/files/f1/download"}]
        with (
            patch.object(tools, "run_in_sandbox", side_effect=_run),
            patch.object(tools, "store_outputs", return_value=(stored, [])) as store,
        ):
            result = self.toolbox.call("run_python", {"code": "print(45)", "files": ["q3.xlsx"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "45\n")
        self.assertEqual(result["generated_files"], stored)
        self.assertEqual(store.call_args.kwargs["owner_id"], self.actor)
        self.assertNotIn("token", str(result).lower())
        self.assertNotIn("/dl/", str(result))

    def test_truncated_stdout_is_explained(self) -> None:
        outcome = SandboxOutcome(success=True, stdout="x", stdout_dropped_chars=500)
        with patch.object(tools, "run_in_sandbox", return_value=outcome):
            result = self.toolbox.call("run_python", {"code": "print('x' * 501)"})
        self.assertIn("500 more characters", result["stdout_truncated"])

    def test_access_errors_come_back_as_tool_errors(self) -> None:
        with patch.object(
            tools,
            "resolve_files",
            side_effect=FileAccessError("File not found or not accessible: x"),
        ):
            result = self.toolbox.call("inspect_file", {"file": "x"})
        self.assertEqual(result, {"error": "File not found or not accessible: x"})

    def test_sandbox_failures_never_raise_into_the_model_loop(self) -> None:
        with patch.object(tools, "run_in_sandbox", side_effect=RuntimeError("no docker")):
            result = self.toolbox.call("run_python", {"code": "print(1)"})
        self.assertEqual(result, {"error": "no docker"})

    def test_a_file_missing_from_storage_is_a_tool_error(self) -> None:
        broken = DriveFileRef(**{**self.ref.__dict__, "storage_path": None})
        with patch.object(tools, "resolve_files", return_value=[broken]):
            result = self.toolbox.call("inspect_file", {"file": "q3.xlsx"})
        self.assertIn("could not be prepared", result["error"])

    def test_empty_code_and_too_many_files_are_refused(self) -> None:
        self.assertIn("error", self.toolbox.call("run_python", {"code": " "}))
        many = [f"f{i}.csv" for i in range(25)]
        self.assertIn(
            "at most", self.toolbox.call("run_python", {"code": "1", "files": many})["error"]
        )

    def test_clear_deletes_the_workspace(self) -> None:
        self.workspace.ensure()
        self.assertEqual(self.toolbox.call(CLEAR_WORKSPACE_TOOL, {}), {"cleared": True})
        self.assertFalse(self.workspace.exists())

    def test_clear_is_not_offered_without_include_clear(self) -> None:
        toolbox = FileToolbox(self.workspace, self.actor, source_label="Agent")
        self.assertIn("error", toolbox.call(CLEAR_WORKSPACE_TOOL, {}))


class SchemaTests(unittest.TestCase):
    def test_chat_schemas_include_clear_and_agent_defs_do_not(self) -> None:
        chat = [s["function"]["name"] for s in tool_schemas(include_clear=True)]
        self.assertEqual(chat, ["list_files", "inspect_file", "run_python", "clear_workspace"])
        toolbox = MagicMock()
        defs = agent_tool_defs(toolbox)
        self.assertEqual([d["name"] for d in defs], ["list_files", "inspect_file", "run_python"])
        self.assertTrue(all(d["_source"] == "file_sandbox" for d in defs))
        self.assertTrue(all(d["_file_toolbox"] is toolbox for d in defs))

    def test_unified_executor_dispatches_to_the_toolbox(self) -> None:
        from app.services.llm_service import _unified_tool_executor

        toolbox = MagicMock()
        toolbox.call.return_value = {"generated_files": [{"id": "f1"}]}
        output = _unified_tool_executor(
            {"_source": "file_sandbox", "_file_toolbox": toolbox}, "run_python", {"code": "1"}, 30
        )
        toolbox.call.assert_called_once_with("run_python", {"code": "1"})
        self.assertEqual(output["_generated_files"], [{"id": "f1"}])


_RUN_WORKFLOW = uuid.uuid4()


def _agent_executor(actor: uuid.UUID | None) -> WorkflowExecutor:
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor.actor_user_id = actor
    executor.workflow_id = _RUN_WORKFLOW
    executor.file_scope = RunFileScope().including_workflow(_RUN_WORKFLOW)
    return executor


class SandboxModuleTests(unittest.TestCase):
    def test_the_converter_ocr_ships_into_the_sandbox(self) -> None:
        from app.services.file_sandbox.executor import module_sources

        self.assertEqual(set(module_sources()), {"heym_files", "heym_inspector", "heym_ocr"})
        self.assertIn("def pdf_to_text(", module_sources()["heym_ocr"])

    def test_a_module_with_dataclasses_installs(self) -> None:
        import sys

        from app.services.file_sandbox import runner

        source = (
            "from __future__ import annotations\n"
            "from dataclasses import dataclass\n\n"
            "@dataclass\nclass Page:\n    page: int\n    text: str\n"
        )
        try:
            runner._install_modules({"heym_test_module": source})
            page = sys.modules["heym_test_module"].Page(1, "x")
        finally:
            sys.modules.pop("heym_test_module", None)
        self.assertEqual(page.page, 1)


class DetectTests(unittest.TestCase):
    def test_candidates_come_from_nested_values_and_text(self) -> None:
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        found = detect.file_id_candidates(
            {"Upload": {"file": {"id": str(a), "name": "q3.xlsx"}}},
            [{"files": [str(b).upper()]}],
            f"Summarize file {c} please",
            {"google_file_id": "1AbCdEf", "count": 3},
        )
        self.assertEqual(found, {a, b, c})

    def test_candidates_are_capped(self) -> None:
        text = " ".join(str(uuid.uuid4()) for _ in range(80))
        self.assertEqual(len(detect.file_id_candidates(text)), 50)

    def test_supported_types_by_extension_then_mime(self) -> None:
        for name in ("a.pdf", "b.XLSX", "c.csv", "d.docx", "e.json", "f.jsonl", "g.md"):
            self.assertTrue(detect.is_analyzable(name, None), name)
        for name in ("a.png", "b.zip", "c.mp4", "d.exe"):
            self.assertFalse(detect.is_analyzable(name, "application/pdf"), name)
        self.assertTrue(detect.is_analyzable("export", "text/csv; charset=utf-8"))
        self.assertFalse(detect.is_analyzable("photo", "image/png"))

    def test_only_supported_files_with_stored_content_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stored = Path(tmp) / "q3.xlsx"
            stored.write_bytes(b"x")
            kept = _ref(stored)
            image = _ref(stored, name="photo.png")
            missing = replace(
                kept, id=uuid.uuid4(), name="gone.csv", storage_path=Path(tmp) / "gone.csv"
            )
            unusable = replace(kept, id=uuid.uuid4(), storage_path=None)
            rows = [kept, image, missing, unusable]
            scope = RunFileScope(file_ids=frozenset({kept.id}))
            with patch.object(detect, "accessible_files_by_id", return_value=rows) as lookup:
                result = detect.analyzable_input_files(MagicMock(), uuid.uuid4(), {kept.id}, scope)
        self.assertEqual(result, [kept])
        self.assertIs(lookup.call_args.kwargs["scope"], scope)

    def test_a_failed_lookup_leaves_the_agent_unchanged(self) -> None:
        from sqlalchemy.exc import OperationalError

        failure = OperationalError("select", {}, Exception("down"))
        with patch("app.db.session.SessionLocal", side_effect=failure):
            toolbox = detect.agent_input_toolbox(
                (str(uuid.uuid4()),),
                uuid.uuid4(),
                scope=RunFileScope(),
                source_label="A",
                workflow_id=None,
            )
        self.assertIsNone(toolbox)

    def test_scope_grows_with_each_workflow_it_covers(self) -> None:
        parent, child = uuid.uuid4(), uuid.uuid4()
        scope = RunFileScope().including_workflow(str(parent))
        self.assertEqual(scope.workflow_ids, {parent})
        self.assertIs(scope.including_workflow(parent), scope)
        self.assertIs(scope.including_workflow(None), scope)
        self.assertIs(scope.including_workflow("not-a-uuid"), scope)
        self.assertEqual(scope.including_workflow(child).workflow_ids, {parent, child})

    def test_executor_scope_covers_its_workflow_and_keeps_the_parents(self) -> None:
        parent, child, handed = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        top = WorkflowExecutor(nodes=[], edges=[], workflow_id=parent)
        self.assertEqual(top.file_scope, RunFileScope(workflow_ids=frozenset({parent})))
        chat = RunFileScope(file_ids=frozenset({handed}))
        sub = WorkflowExecutor(
            nodes=[],
            edges=[],
            workflow_id=child,
            file_scope=RunFileScope(
                workflow_ids=top.file_scope.workflow_ids, file_ids=chat.file_ids
            ),
        )
        self.assertEqual(sub.file_scope.workflow_ids, {parent, child})
        self.assertEqual(sub.file_scope.file_ids, {handed})
        self.assertEqual(WorkflowExecutor(nodes=[], edges=[]).file_scope, RunFileScope())

    def test_instructions_name_the_input_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q3.xlsx"
            path.write_bytes(b"x")
            ref = _ref(path)
        text = agent_file_instructions([ref])
        self.assertIn('"q3.xlsx"', text)
        self.assertIn(str(ref.id), text)
        self.assertNotIn("Files in this input", agent_file_instructions())


class AgentWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        stored = Path(self._tmp.name) / "q3.xlsx"
        stored.write_bytes(b"x")
        self.ref = _ref(stored)
        root = Path(self._tmp.name) / "sandbox"
        self._root = patch("app.services.file_sandbox.workspace.sandbox_root", return_value=root)
        self._root.start()

    def tearDown(self) -> None:
        self._root.stop()
        self._tmp.cleanup()

    def _run(
        self, executor: WorkflowExecutor, inputs: dict, node_data: dict, *, files: list
    ) -> tuple[MagicMock, MagicMock]:
        finder = MagicMock(return_value=files)
        with (
            patch("app.db.session.SessionLocal", return_value=_Session()),
            patch.object(detect, "analyzable_input_files", finder),
            patch.object(WorkflowExecutor, "_run_agent_node", return_value={"text": "ok"}) as run,
        ):
            executor._execute_agent_node("a1", inputs, node_data)
        return run, finder

    def test_input_without_a_file_id_skips_the_lookup(self) -> None:
        run, finder = self._run(
            _agent_executor(uuid.uuid4()), {"In": {"text": "hello"}}, {"label": "A"}, files=[]
        )
        finder.assert_not_called()
        self.assertNotIn("file_toolbox", run.call_args.kwargs)

    def test_an_id_that_is_not_an_analyzable_file_leaves_the_agent_unchanged(self) -> None:
        inputs = {"In": {"execution_id": str(uuid.uuid4())}}
        run, finder = self._run(_agent_executor(uuid.uuid4()), inputs, {}, files=[])
        finder.assert_called_once()
        self.assertNotIn("file_toolbox", run.call_args.kwargs)

    def test_a_file_in_the_input_gives_the_agent_the_tools(self) -> None:
        actor = uuid.uuid4()
        inputs = {"Upload": {"file": {"id": str(self.ref.id), "name": "q3.xlsx"}}}
        run, finder = self._run(
            _agent_executor(actor), inputs, {"label": "Reader"}, files=[self.ref]
        )
        self.assertEqual(
            finder.call_args.args[1:],
            (actor, {self.ref.id}, RunFileScope(workflow_ids=frozenset({_RUN_WORKFLOW}))),
        )
        toolbox = run.call_args.kwargs["file_toolbox"]
        self.assertEqual(toolbox.actor_id, actor)
        self.assertEqual(toolbox.source_label, "Reader")
        self.assertEqual(toolbox.input_files, [self.ref])
        self.assertEqual(toolbox.workflow_id, _RUN_WORKFLOW)
        self.assertEqual(toolbox.scope, RunFileScope(file_ids=frozenset({self.ref.id})))
        self.assertFalse(toolbox.include_clear)
        self.assertFalse(toolbox.workspace.exists())

    def test_a_file_id_in_the_resolved_prompt_counts(self) -> None:
        executor = _agent_executor(uuid.uuid4())
        node_data = {"userMessage": "$Upload.file.id"}
        with patch.object(WorkflowExecutor, "_resolve_template", return_value=str(self.ref.id)):
            run, finder = self._run(executor, {}, node_data, files=[self.ref])
        self.assertEqual(finder.call_args.args[2], {self.ref.id})
        self.assertIn("file_toolbox", run.call_args.kwargs)

    def test_without_an_actor_there_is_no_lookup(self) -> None:
        inputs = {"Upload": {"file": {"id": str(self.ref.id)}}}
        run, finder = self._run(_agent_executor(None), inputs, {}, files=[self.ref])
        finder.assert_not_called()
        self.assertNotIn("file_toolbox", run.call_args.kwargs)

    def test_workspace_is_deleted_when_the_agent_fails(self) -> None:
        executor = _agent_executor(uuid.uuid4())
        seen: list[FileToolbox] = []

        def _boom(*_args: object, file_toolbox: FileToolbox, **_kw: object) -> dict:
            seen.append(file_toolbox)
            file_toolbox.workspace.ensure()
            raise RuntimeError("model failed")

        inputs = {"Upload": {"file": {"id": str(self.ref.id)}}}
        with (
            patch("app.db.session.SessionLocal", return_value=_Session()),
            patch.object(detect, "analyzable_input_files", return_value=[self.ref]),
            patch.object(WorkflowExecutor, "_run_agent_node", side_effect=_boom),
        ):
            with self.assertRaises(RuntimeError):
                executor._execute_agent_node("a1", inputs, {"label": "Reader"})
        self.assertTrue(seen)
        self.assertFalse(seen[0].workspace.exists())


def _code_context(node_data: dict, actor: uuid.UUID | None = None) -> NodeExecutionContext:
    executor = MagicMock()
    executor.evaluate_message_template.side_effect = lambda template, *_a, **_k: template
    executor.workflow_id = None
    executor.file_scope = RunFileScope(workflow_ids=frozenset({_RUN_WORKFLOW}))
    if actor is None:
        executor._require_actor_user_id.side_effect = ValueError("requires actor_user_id")
    else:
        executor._require_actor_user_id.return_value = actor
    return NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "n1", "type": "code", "data": node_data},
        node_type="code",
        node_data=node_data,
        node_label="extract",
    )


class CodeNodeFilesTests(unittest.TestCase):
    CODE = "def main(params):\n    return 1\n"

    def test_ids_are_normalized_from_every_shape(self) -> None:
        self.assertEqual(code_node._file_ids("a, b\nc"), ["a", "b", "c"])
        self.assertEqual(code_node._file_ids([{"id": "a"}, "b", {"file_id": "c"}]), ["a", "b", "c"])
        self.assertEqual(code_node._file_ids({"id": "a", "name": "x.pdf"}), ["a"])
        self.assertEqual(code_node._file_ids(["a", "a"]), ["a"])
        self.assertEqual(code_node._file_ids(None), [])

    def test_expression_is_resolved_with_its_type(self) -> None:
        ctx = _code_context({"codeSource": self.CODE, "codeFiles": "$Upload.file"}, uuid.uuid4())
        ctx.executor.resolve_expression.return_value = {"id": "file-1", "name": "q3.xlsx"}
        self.assertEqual(code_node._resolve_file_refs(ctx), ["file-1"])
        self.assertTrue(ctx.executor.resolve_expression.call_args.kwargs["preserve_type"])

    def test_without_files_the_plain_path_runs_unchanged(self) -> None:
        ctx = _code_context({"codeSource": self.CODE, "codeFiles": "  "})
        with patch.object(
            code_node, "execute_code", return_value=CodeExecutionResult(result=1)
        ) as plain:
            output = code_node.execute(ctx)
        plain.assert_called_once()
        self.assertNotIn("files", output)

    def test_files_run_as_the_actor_and_return_drive_files(self) -> None:
        from app.services.file_sandbox import code_node as files_module

        actor = uuid.uuid4()
        ctx = _code_context({"codeSource": self.CODE, "codeFiles": "id-1"}, actor)
        result = files_module.CodeFilesResult(result={"total": 45}, files=[{"id": "out"}])
        with patch.object(files_module, "execute_code_with_files", return_value=result) as run:
            output = code_node.execute(ctx)
        self.assertEqual(run.call_args.kwargs["actor_id"], actor)
        self.assertEqual(run.call_args.kwargs["file_refs"], ["id-1"])
        self.assertIs(run.call_args.kwargs["scope"], ctx.executor.file_scope)
        self.assertEqual(run.call_args.kwargs["source_label"], "extract")
        self.assertEqual(output["result"], {"total": 45})
        self.assertEqual(output["files"], [{"id": "out"}])

    def test_files_without_an_actor_are_refused(self) -> None:
        ctx = _code_context({"codeSource": self.CODE, "codeFiles": "id-1"})
        with self.assertRaises(ValueError):
            code_node.execute(ctx)


if __name__ == "__main__":
    unittest.main()
