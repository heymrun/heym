"""Chat build mode tools: save, test-run and finish a workflow from the dashboard chat.

One `ChatBuildSession` belongs to one chat turn that may build. The chat engine
(`stream_dashboard_chat`) offers its tools and hands their calls here. Saves go through
`workflow_save`, like the editor's, and are audited here in the API layer: chat turns run
on the instance that received the request, so the audit trail stays where AGENTS.md wants it.
"""

import json
import uuid
from dataclasses import dataclass, field
from threading import Event
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_assistant import (
    _CREDENTIAL_CHOICES_SCHEMA,
    _DATA_TABLE_CHOICES_SCHEMA,
    FileAttachment,
    _build_saved_workflow_payload,
    _builder_credential_mode,
    _extract_generated_workflow_config,
    _find_injection_field,
    _load_installed_plugins,
    _sanitize_generated_workflow_nodes,
    _saved_workflow_extra,
    get_workflows_for_user_with_inputs,
    run_execute_workflow_tool,
)
from app.api.workflows import extract_input_fields_from_workflow, get_workflow_for_user
from app.db.models import Credential, User, Workflow
from app.services import template_service
from app.services.audit_log import audit
from app.services.chat_build_mode import (
    AI_BUILDER_TOOL_NAMES,
    BUDGET_SPENT_MESSAGE,
    BUILD_TOOL_NAMES,
    FINISH_TOOL,
    MAX_BUILD_TEST_RUNS,
    RUN_WORKFLOW_TEST_TOOL,
    SAVE_WORKFLOW_TOOL,
    BuildProgress,
    BuildRequest,
    build_mode_instructions,
    build_run_report,
)
from app.services.credential_catalog import (
    CredentialPromptMode,
    format_credentials_prompt,
    load_credential_catalog,
)
from app.services.dashboard_widget_policy import dashboard_widget_blocked_nodes_error
from app.services.data_table_catalog import (
    DataTablePromptMode,
    format_data_tables_prompt,
    load_data_table_catalog,
)
from app.services.generated_credentials import (
    apply_generated_credentials,
    parse_credential_choices,
    requires_credentials_payload,
)
from app.services.generated_data_tables import (
    apply_generated_data_tables,
    parse_data_table_choices,
    requires_data_table_payload,
)
from app.services.workflow_access import user_can_write_workflow
from app.services.workflow_dsl_prompt import build_assistant_prompt
from app.services.workflow_save import (
    WorkflowSnapshot,
    add_workflow_version,
    announce_workflow_saved,
)

SAVE_WORKFLOW_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SAVE_WORKFLOW_TOOL,
        "description": (
            "Save the complete workflow in the Workflow DSL format: create it, or update the "
            "target workflow when the turn has one. Pass every node and edge, not a diff."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {
                    "type": "string",
                    "description": (
                        "Id of a workflow saved earlier in this conversation, to change it "
                        "instead of creating a new one. Omit it when the turn has a target."
                    ),
                },
                "workflow": {
                    "type": "object",
                    "description": "The workflow: name, description, nodes and edges.",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "nodes": {"type": "array", "items": {"type": "object"}},
                        "edges": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["name", "nodes", "edges"],
                },
                "credential_choices": _CREDENTIAL_CHOICES_SCHEMA,
                "data_table_choices": _DATA_TABLE_CHOICES_SCHEMA,
            },
            "required": ["workflow"],
        },
    },
}

RUN_WORKFLOW_TEST_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RUN_WORKFLOW_TEST_TOOL,
        "description": (
            "Run the saved workflow once with sample inputs and get a run report. Runs are "
            f"real. At most {MAX_BUILD_TEST_RUNS} test runs per turn."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "inputs": {
                    "type": "object",
                    "description": "Sample values keyed by the workflow's input field keys.",
                },
                "expect": {
                    "type": "string",
                    "description": "One sentence describing what a successful run returns.",
                },
            },
            "required": ["inputs", "expect"],
        },
    },
}

FINISH_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": FINISH_TOOL,
        "description": (
            "End the turn once the latest test run of the latest save shows the request is "
            "done. The chat shows the summary on a Verified card."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One sentence on what the workflow now does.",
                },
            },
            "required": ["summary"],
        },
    },
}


@dataclass(frozen=True)
class BuildToolOutcome:
    """One build tool call: the result for the model, the step row and extra stream events."""

    result: str
    summary: str
    status: str
    events: list[dict[str, Any]] = field(default_factory=list)
    finished_summary: str | None = None


def _error(message: str) -> BuildToolOutcome:
    return BuildToolOutcome(
        result=json.dumps({"status": "error", "error": message}),
        summary=f"Error: {message}",
        status="error",
    )


class ChatBuildSession:
    """The build tools of one chat turn and what they have done."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        user: User,
        request: BuildRequest,
        selected_credential: Credential,
        model: str,
        credential_mode: CredentialPromptMode,
        public_base_url: str,
        cancel_event: Event | None,
        llm_session_id: str | None,
        attachment: FileAttachment | None = None,
    ) -> None:
        self.db = db
        self.user = user
        self.request = request
        self.selected_credential = selected_credential
        self.model = model
        self.credential_mode = credential_mode
        self.public_base_url = public_base_url
        self.cancel_event = cancel_event
        # Every model request and test run in the turn carries one non-empty session id.
        self.llm_session_id = llm_session_id or str(uuid.uuid4())
        self.attachment = attachment
        self.progress = BuildProgress(workflow_id=request.target_workflow_id)

    @property
    def builder_mode(self) -> CredentialPromptMode:
        return _builder_credential_mode(self.credential_mode)

    async def prompt(self) -> str:
        """The build mode instructions and the Workflow DSL reference for this user."""
        target = await self._target_workflow()
        current_workflow = (
            {
                "id": str(target.id),
                "name": target.name,
                "description": target.description,
                "nodes": target.nodes or [],
                "edges": target.edges or [],
            }
            if target is not None
            else None
        )
        templates = await template_service.list_node_templates(self.db, self.user, None)
        catalog = await load_credential_catalog(self.db, self.user.id)
        table_catalog = await load_data_table_catalog(self.db, self.user.id)
        reference = build_assistant_prompt(
            current_workflow,
            await get_workflows_for_user_with_inputs(self.db, self.user.id),
            None,
            available_node_templates=[
                {
                    "id": str(t.id),
                    "name": t.name,
                    "description": t.description,
                    "tags": list(t.tags or []),
                    "node_type": t.node_type,
                    "node_data": dict(t.node_data or {}),
                }
                for t in templates
            ],
            installed_plugins=await _load_installed_plugins(self.db),
            credentials_prompt=format_credentials_prompt(catalog, self.builder_mode),
            data_tables_prompt=format_data_tables_prompt(
                table_catalog, DataTablePromptMode.APPLY_CHOICES
            ),
        )
        instructions = build_mode_instructions(
            target.name if target is not None else None,
            target.id if target is not None else None,
        )
        return f"{instructions}\n## Workflow DSL reference\n\n{reference}"

    def tools(self, base_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The chat's own tools without the AI Builder, plus what build mode allows now."""
        tools = [t for t in base_tools if t["function"]["name"] not in AI_BUILDER_TOOL_NAMES]
        if not self.progress.budget_spent:
            return tools + [
                SAVE_WORKFLOW_TOOL_SCHEMA,
                RUN_WORKFLOW_TEST_TOOL_SCHEMA,
                FINISH_TOOL_SCHEMA,
            ]
        if self.progress.finish_refusal() is None:
            return tools + [FINISH_TOOL_SCHEMA]
        return tools

    def handles(self, name: str) -> bool:
        return name in BUILD_TOOL_NAMES

    def display_args(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Arguments for the step row, the stored message and the trace, without the whole DSL."""
        if name != SAVE_WORKFLOW_TOOL:
            return args
        workflow = args.get("workflow") if isinstance(args.get("workflow"), dict) else {}
        nodes = workflow.get("nodes")
        edges = workflow.get("edges")
        return {
            "name": workflow.get("name"),
            "nodes": len(nodes) if isinstance(nodes, list) else 0,
            "edges": len(edges) if isinstance(edges, list) else 0,
        }

    def step_label(self, name: str) -> str:
        if name == SAVE_WORKFLOW_TOOL:
            return "Saving the workflow..."
        if name == RUN_WORKFLOW_TEST_TOOL:
            attempt = min(self.progress.runs_used + 1, MAX_BUILD_TEST_RUNS)
            return f"Testing the workflow · attempt {attempt}/{MAX_BUILD_TEST_RUNS}..."
        return "Finishing..."

    async def call(self, name: str, args: dict[str, Any]) -> BuildToolOutcome:
        if name == SAVE_WORKFLOW_TOOL:
            return await self._save(args)
        if name == RUN_WORKFLOW_TEST_TOOL:
            return await self._run_test(args)
        return await self._finish(args)

    async def _target_workflow(self) -> Workflow | None:
        if self.progress.workflow_id is None:
            return None
        return await get_workflow_for_user(self.db, self.progress.workflow_id, self.user.id)

    async def _save(self, args: dict[str, Any]) -> BuildToolOutcome:
        workflow_arg = args.get("workflow")
        if not isinstance(workflow_arg, dict):
            return _error("Pass the workflow as an object with name, nodes and edges.")
        try:
            config = _extract_generated_workflow_config(json.dumps(workflow_arg), "Chat build")
        except ValueError as exc:
            return _error(str(exc))

        requested = self._requested_workflow_id(args.get("workflow_id"))
        if isinstance(requested, BuildToolOutcome):
            return requested
        workflow_id = requested or self.progress.workflow_id
        existing: Workflow | None = None
        if workflow_id is not None:
            existing = await get_workflow_for_user(self.db, workflow_id, self.user.id)
            if existing is None:
                return _error("Workflow not found or no access")
            if not await user_can_write_workflow(self.db, existing, self.user.id):
                return _error("You have read-only access to this workflow")

        catalog = await load_credential_catalog(self.db, self.user.id)
        table_catalog = await load_data_table_catalog(self.db, self.user.id)
        nodes = _sanitize_generated_workflow_nodes(
            config["nodes"],
            owned_credential_ids={str(credential.id) for credential in catalog},
            selected_credential=self.selected_credential,
            selected_model=self.model,
            user_id=self.user.id,
        )
        previous_nodes = existing.nodes if existing is not None else None
        credential_pass = apply_generated_credentials(
            nodes,
            catalog=catalog,
            choices=[]
            if self.builder_mode is CredentialPromptMode.OFF
            else parse_credential_choices(args.get("credential_choices")),
            previous_nodes=previous_nodes,
            mode=self.builder_mode,
        )
        if credential_pass.needs and self.builder_mode is not CredentialPromptMode.OFF:
            payload = requires_credentials_payload(credential_pass.needs)
            return BuildToolOutcome(
                result=json.dumps(payload), summary="Needs credentials", status="pending"
            )
        table_pass = apply_generated_data_tables(
            credential_pass.nodes,
            catalog=table_catalog,
            choices=parse_data_table_choices(args.get("data_table_choices")),
            previous_nodes=previous_nodes,
        )
        if table_pass.needs:
            payload = requires_data_table_payload(table_pass.needs)
            return BuildToolOutcome(
                result=json.dumps(payload), summary="Needs a data table", status="pending"
            )
        nodes = table_pass.nodes
        edges = config["edges"]

        version_number: int | None = None
        if existing is not None:
            if getattr(existing, "kind", "workflow") == "dashboard_widget":
                blocked = dashboard_widget_blocked_nodes_error(nodes)
                if blocked is not None:
                    return _error(blocked)
            before = WorkflowSnapshot.capture(existing)
            existing.name = config["name"]
            existing.description = config["description"]
            existing.nodes = nodes
            existing.edges = edges
            if before.nodes != nodes or before.edges != edges:
                version_number = await add_workflow_version(self.db, existing, before, self.user.id)
            workflow = existing
        else:
            workflow = Workflow(
                id=uuid.uuid4(),
                name=config["name"],
                description=config["description"],
                owner_id=self.user.id,
                nodes=nodes,
                edges=edges,
            )
            self.db.add(workflow)
        await self.db.commit()
        await self.db.refresh(workflow)
        await announce_workflow_saved(workflow, self.user.id, created=existing is None)
        audit(
            action="workflow.update" if existing is not None else "workflow.create",
            actor=self.user,
            target_type="workflow",
            target_id=workflow.id,
            target_name=workflow.name,
            source="chat_build",
            versioned=version_number is not None,
            nodes=len(workflow.nodes or []),
        )
        self.progress.record_save(workflow.id)

        extra = _saved_workflow_extra(credential_pass, self.builder_mode, table_pass) or {}
        # Edit History stores what a save replaced as version N; the saved state is N + 1.
        if existing is None:
            extra["version"] = 1
        elif version_number is not None:
            extra["version"] = version_number + 1
        extra["test_runs_left"] = MAX_BUILD_TEST_RUNS - self.progress.runs_used
        result = _build_saved_workflow_payload(
            workflow,
            nodes,
            edges,
            extract_input_fields_from_workflow(workflow),
            {},
            status_value="created" if existing is None else "saved",
            extra=extra,
        )
        if existing is None:
            summary = f'Created "{workflow.name}"'
        elif version_number is not None:
            summary = f'Saved "{workflow.name}" · version {extra["version"]}'
        else:
            summary = f'Saved "{workflow.name}" · no changes'
        event = {
            "type": "workflow_created",
            "workflow_id": str(workflow.id),
            "workflow_name": workflow.name,
            "workflow_description": workflow.description,
            "workflow_url": f"/workflows/{workflow.id}",
            "nodes": nodes,
            "edges": edges,
        }
        return BuildToolOutcome(result=result, summary=summary, status="success", events=[event])

    def _requested_workflow_id(self, raw: object) -> "uuid.UUID | BuildToolOutcome | None":
        """The workflow save_workflow should change, when the model names one."""
        if raw in (None, ""):
            return None
        try:
            requested = uuid.UUID(str(raw))
        except ValueError:
            return _error("workflow_id must be a workflow UUID.")
        target = self.request.target_workflow_id
        if target is not None and requested != target:
            return _error(f"This turn changes workflow {target}; pass that id or none.")
        return requested

    async def _run_test(self, args: dict[str, Any]) -> BuildToolOutcome:
        if self.progress.budget_spent:
            return BuildToolOutcome(
                result=json.dumps({"status": "refused", "error": BUDGET_SPENT_MESSAGE}),
                summary=f"Stopped after {MAX_BUILD_TEST_RUNS} test runs",
                status="error",
            )
        workflow = await self._target_workflow()
        if workflow is None:
            return _error("Save the workflow with save_workflow before testing it.")
        inputs = dict(args.get("inputs") or {}) if isinstance(args.get("inputs"), dict) else {}
        expect = str(args.get("expect") or "").strip()
        run_inputs = dict(inputs)
        if self.attachment is not None:
            field_keys = [f.key for f in extract_input_fields_from_workflow(workflow)]
            inject_key = _find_injection_field(field_keys, self.attachment.kind)
            if inject_key:
                run_inputs[inject_key] = self.attachment.content
        raw = await run_execute_workflow_tool(
            self.db,
            self.user.id,
            str(workflow.id),
            run_inputs,
            self.public_base_url,
            self.cancel_event,
            llm_session_id=self.llm_session_id,
        )
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"status": "error", "error": "The run returned no readable result."}
        if result.get("status") == "cancelled":
            return BuildToolOutcome(result=raw, summary="Cancelled", status="cancelled")
        attempt = self.progress.record_run(str(result.get("status") or "error"))
        report = build_run_report(result, attempt=attempt, inputs=inputs, expect=expect)
        report["test_runs_left"] = MAX_BUILD_TEST_RUNS - self.progress.runs_used
        if self.progress.budget_spent:
            report["budget_spent"] = BUDGET_SPENT_MESSAGE
        seconds = result.get("execution_time_ms")
        duration = f" in {float(seconds) / 1000:.1f}s" if isinstance(seconds, int | float) else ""
        status = report["status"]
        return BuildToolOutcome(
            result=json.dumps(report, default=str),
            summary=f"Attempt {attempt}/{MAX_BUILD_TEST_RUNS} · {status}{duration}",
            status="success" if status == "success" else "error",
        )

    async def _finish(self, args: dict[str, Any]) -> BuildToolOutcome:
        refusal = self.progress.finish_refusal()
        if refusal is not None:
            return _error(refusal)
        workflow = await self._target_workflow()
        if workflow is None:
            return _error("Workflow not found or no access")
        summary = str(args.get("summary") or "").strip() or (
            "The workflow is saved and its latest test run passed."
        )
        event = {
            "type": "verified",
            "summary": summary,
            "workflow_id": str(workflow.id),
            "workflow_name": workflow.name,
            "workflow_url": f"/workflows/{workflow.id}",
            "test_runs": self.progress.runs_used,
        }
        return BuildToolOutcome(
            result=json.dumps({"status": "verified", "summary": summary}),
            summary="Verified",
            status="success",
            events=[event],
            finished_summary=summary,
        )
