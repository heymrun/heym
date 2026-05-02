import asyncio
import contextlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, AsyncGenerator, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import compute_analytics_stats, upsert_workflow_analytics_snapshot
from app.api.deps import get_current_user
from app.api.schedules import fetch_schedule_events_for_user
from app.api.workflows import (
    collect_referenced_workflows,
    extract_input_fields_from_workflow,
    extract_output_node_from_workflow,
    get_credentials_context,
    get_recent_executions_for_user,
    get_workflow_for_user,
)
from app.db.models import (
    Credential,
    CredentialShare,
    CredentialType,
    ExecutionHistory,
    GlobalVariable,
    HITLRequest,
    Team,
    TeamMember,
    User,
    Workflow,
    WorkflowShare,
    WorkflowTeamShare,
)
from app.db.session import get_db
from app.services import template_service
from app.services.encryption import decrypt_config
from app.services.hitl_service import (
    build_hitl_resolved_output,
    build_public_base_url,
    ensure_hitl_request_is_actionable,
    get_hitl_request_by_token,
    persist_pending_hitl_execution,
    resume_hitl_request_in_background,
)
from app.services.llm_provider import is_reasoning_model
from app.services.llm_trace import LLMTraceContext, record_llm_trace
from app.services.run_history import record_run_history
from app.services.schedule_range import resolve_schedule_tool_range
from app.services.timezone_utils import get_configured_timezone
from app.services.workflow_dsl_prompt import build_assistant_prompt
from app.services.workflow_executor import WorkflowCancelledError, execute_workflow

router = APIRouter()
logger = logging.getLogger(__name__)

GOOGLE_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


CANVAS_ASK_SYSTEM_PROMPT = """You are a helpful AI assistant integrated into the Heym workflow editor canvas. \
You can see the user's current workflow (nodes and edges) when provided, and you answer questions about it conversationally.

You can help with:
- Explaining what nodes do and how the workflow is structured
- Answering questions about Heym features, node types, expressions, and best practices
- Suggesting improvements or alternatives without modifying the canvas
- Debugging logic or helping understand execution flow

Do NOT generate workflow JSON or DSL output. Respond in plain language only.
Respond in the same language the user uses."""


class AIAssistantRequest(BaseModel):
    credential_id: uuid.UUID
    model: str
    message: str
    current_workflow: dict | None = None
    conversation_history: list[dict] | None = None
    available_workflows: list[dict] | None = None
    ask_mode: bool = False


class FileAttachment(BaseModel):
    name: str
    kind: Literal["text", "image", "pdf"]
    content: str  # plain text for text/pdf, base64 data URL for images


class DashboardChatRequest(BaseModel):
    credential_id: uuid.UUID
    model: str
    message: str
    conversation_history: list[dict] | None = None
    chat_surface: Literal["dashboard", "documentation"] | None = None
    user_rules: str | None = None
    client_local_datetime: str | None = None
    attachment: FileAttachment | None = None


class FixTranscriptionRequest(BaseModel):
    credential_id: uuid.UUID
    model: str
    text: str


class FixTranscriptionResponse(BaseModel):
    fixed_text: str


MAX_DASHBOARD_CHAT_HISTORY = 25


def _get_dashboard_chat_node_label(
    chat_surface: Literal["dashboard", "documentation"] | None,
) -> str:
    if chat_surface == "documentation":
        return "Documentation Chat"
    return "Dashboard Chat"


_ATTACHMENT_ROUTING_INSTRUCTIONS = (
    "When the user has attached a file, route its content to the most appropriate "
    "workflow input field when calling a workflow tool:\n"
    '- Image attachment → fields named "image", "base64", "photo", "picture", or similar\n'
    '- Text/PDF attachment → fields named "text", "document", "content", "file", "data", or similar\n'
    "- If no dedicated field exists → embed the content in the primary message/query/input field"
)


_IMAGE_FIELD_KEYWORDS = {"image", "base64", "photo", "picture", "img"}
_TEXT_FIELD_KEYWORDS = {"text", "document", "content", "file", "data"}


def _find_injection_field(input_fields: list[str], kind: str) -> str | None:
    """Return the best input field key to inject an attachment into, or None."""
    keywords = _IMAGE_FIELD_KEYWORDS if kind == "image" else _TEXT_FIELD_KEYWORDS
    for field in input_fields:
        if any(kw in field.lower() for kw in keywords):
            return field
    return input_fields[0] if input_fields else None


def _build_user_message(message: str, attachment: FileAttachment | None) -> dict:
    """Build the user role message dict.

    For text/PDF: embeds content inline so the LLM can use it directly.
    For images: embeds only metadata (not the base64) to avoid context overflow on
    non-vision models. The actual image bytes are auto-injected into the workflow input
    field by the execute_workflow tool handler at call time.
    """
    if attachment is None:
        return {"role": "user", "content": message}
    if attachment.kind == "image":
        embedded = (
            f"{message}\n\n"
            f"[ATTACHED IMAGE: {attachment.name}]\n"
            f"IMPORTANT: Do NOT include image data or any image field in the workflow inputs — "
            f"the image is handled server-side automatically. "
            f"Only include the non-image input fields (e.g. text, query, instruction) in your execute_workflow call."
        )
        return {"role": "user", "content": embedded}
    embedded = f"{message}\n\n[ATTACHED FILE: {attachment.name}]\n{attachment.content}"
    return {"role": "user", "content": embedded}


def _load_agents_md_content() -> str:
    """Load AGENTS.md content for Heym platform context in dashboard chat."""
    paths = [
        Path("/app/AGENTS.md"),  # Docker
        Path(__file__).resolve().parent.parent.parent.parent / "AGENTS.md",  # Local dev
    ]
    for p in paths:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                pass
    return ""


DASHBOARD_CHAT_SYSTEM_PROMPT = """You are an assistant that helps the user with their workflows. You can:
1. List available workflows (how many, their names, descriptions, and input fields) when the user asks (e.g. "how many workflows?", "list workflows", "available tools").
2. Answer questions about what is inside a workflow (e.g. "what is in the backlog?", "what do the sticky notes say?", "what tasks are in workflow X?") without running it: use list_workflows to find the workflow by name, then get_workflow_definition(workflow_id) to get its content (nodes, sticky notes, labels), and answer from that. Do not execute in these cases.
3. Execute a workflow by ID with given inputs only when the user clearly wants to run one or when the answer cannot be given from workflow metadata or content alone (e.g. "send WhatsApp message to X saying Y", "run the birthday workflow", "when is the next birthday?").
4. When the user only asks what workflows exist, what they do, or what inputs they need, use list_workflows and answer from that information—do not execute. Only call execute_workflow when the user explicitly wants to run something or when you need the runtime result (e.g. next birthday date) to answer.
5. When the user asks about execution or analytics statistics (e.g. how many requests today, how many runs in the last 24 hours, error rate), use get_analytics_stats with the appropriate time_range (24h for today, 7d for last week, 30d, or all). You may pass an optional workflow_id to filter by one workflow (get id from list_workflows). Summarize the result in the user's language.
6. When the user asks for details of what ran or what came in (e.g. what ran, show details, list recent runs), use get_recent_executions with the appropriate time_range and optionally limit. Summarize the list (workflow name, time, status, brief output) in the user's language.
6a. When the user asks about scheduled cron runs, the calendar, or when workflows will run (today, this week, this month, upcoming times), use get_schedule_events with view_window day, week, or month, optional reference_date (YYYY-MM-DD), include_shared false for owned-only or true to include shared workflows, or start_iso/end_iso for a custom range. Summarize events (workflow name and time) in the user's language.
7. When a workflow is waiting for human review and the user says to approve, continue, edit, or refuse it, use resolve_hitl_review. Prefer the latest pending request_id or review_url from recent tool results in the conversation.
8. When the user asks you to wait, monitor, or check again for a workflow that is still running or pending, use wait_for_execution_update instead of repeatedly polling yourself. Default to 5 seconds between checks and at most 5 checks unless the user explicitly asks otherwise.
9. If execute_workflow or wait_for_execution_update returns a pending workflow with review details, explain that pending state in the same language as the user, include the review link as a markdown link, briefly summarize the blocked step, and show the three direct chat reply options: approve, edit: ..., and reject.
10. Never say you cannot approve, edit, reject, or continue a pending workflow from chat when resolve_hitl_review can handle it. If a recent assistant message contains a review link, you can reuse that link to resolve the review on the next user turn.

CRITICAL - Workflow-first behavior: You receive a list of available workflows at the start. When the user asks for ANY information (sports, weather, news, match schedules, birthdays, etc.), FIRST check if a workflow can answer. Match user intent to workflow names and descriptions (e.g. "when is the next match" / "Fenerbahce match" -> workflow named "Fenerbahce next match" or similar; "weather" -> weather workflow). If a workflow matches, call execute_workflow immediately with appropriate inputs (often empty {} for workflows with no required inputs). NEVER say "I don't have access" without first checking workflows—many questions can be answered by running a workflow.

Respond in the same language the user uses. Be concise and helpful. When you run a workflow, summarize the result for the user. When a workflow is pending human review, your reply must include the review link and the direct chat options to approve, edit, or reject.

If a tool returns an error or no relevant data, do not invent an answer. Say clearly that you do not have that information (e.g. "I don't have this information"). Base your answers only on data from the tools (workflows, analytics, execution results); when you do not know something, say so.

When the user asks for something you cannot do with your tools (e.g. console logs, server logs) AND no workflow matches, say clearly that you do not have access to that, then offer what you can do in a short numbered list. Always include: (1) I can show recent runs, (2) I can show analytics stats, (3) I can show scheduled cron times (day/week/month), (4) I can run a workflow and show its result, (5) I can list workflows and you can talk about them or ask me to run one, (6) I can list your teams. End with something like: Which would you like?

11. When the user asks about teams (e.g. "my teams", "which teams am I in?", "who is in team X?"), use get_teams. Optionally pass team_name to filter by name.
12. When the user asks about Heym features, nodes, expressions, workflows, or how to use the platform, use search_documentation. Call search_documentation at most 2 times per user message. Use one comprehensive query first (e.g. "canvas features", "portal"). Only call again with a different query if the first returns no relevant docs. In your response, cite the documentation with markdown links: [Document Title](/docs/category/slug). Example: [LLM Node](/docs/nodes/llm-node). When the documentation contains a video tag (e.g. `<video src="/features/showcase/..."`), include it in your response so the user can watch a demo directly in chat. Respond in the user's language.\""""

DASHBOARD_CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_workflows",
            "description": "List all workflows the user has access to. Use this when the user asks how many workflows there are, to list available workflows, or to show available tools. Returns id, name, description, and input_fields for each workflow.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_workflow",
            "description": 'Execute a workflow by ID with the given inputs. Use this when the user wants to run a specific workflow (e.g. send a message, run a birthday reminder). You must know the workflow id from list_workflows. inputs should be an object matching the workflow\'s input_fields (e.g. {"text": "hello"} for a single text input).',
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "UUID of the workflow to execute",
                    },
                    "inputs": {
                        "type": "object",
                        "description": 'Input values keyed by field name (e.g. {"text": "message content"})',
                    },
                },
                "required": ["workflow_id", "inputs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_hitl_review",
            "description": "Approve, edit, or refuse a pending Human-in-the-Loop review for a workflow run. Use this when the user says to approve, continue, edit, or reject a workflow that is waiting for human review.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "HITL request UUID from a recent tool result, if available.",
                    },
                    "review_url": {
                        "type": "string",
                        "description": "Optional public review URL from a recent tool result. Use this if request_id is unavailable.",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["accept", "edit", "refuse"],
                        "description": "Decision to apply to the pending review.",
                    },
                    "edited_text": {
                        "type": "string",
                        "description": "Required when action is edit. Replacement Markdown/instructions approved by the human.",
                    },
                    "refusal_reason": {
                        "type": "string",
                        "description": "Optional reason when action is refuse.",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_for_execution_update",
            "description": "Wait and re-check a workflow execution status. Use this when the user asks you to keep monitoring a running or pending workflow. Default to 5 seconds between checks and at most 5 checks unless the user says otherwise.",
            "parameters": {
                "type": "object",
                "properties": {
                    "execution_history_id": {
                        "type": "string",
                        "description": "Execution history UUID of the workflow run to monitor.",
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "Seconds to wait between checks. Default 5.",
                    },
                    "max_checks": {
                        "type": "integer",
                        "description": "Maximum number of checks to perform before returning. Default 5.",
                    },
                },
                "required": ["execution_history_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_workflow_definition",
            "description": "Get workflow content without running it. Use list_workflows first to find workflow_id. By default returns summary (nodes, sticky notes, cron, http URLs). When user asks for specific details (crawler URL, selectors, LLM prompts, agent tools, node parameters), pass full_details=true to get complete DSL with all node data. Do not execute the workflow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "UUID of the workflow whose content to read",
                    },
                    "full_details": {
                        "type": "boolean",
                        "description": "If true, returns full DSL (all node data: crawlerUrl, crawlerSelectors, llm userMessage, agent tools, etc.). Use when user asks for specific details (URL, selectors, parameters, prompts). Default false returns summary only.",
                        "default": False,
                    },
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_analytics_stats",
            "description": "Get execution/analytics statistics (total runs, success/error counts and rates, latencies). Use when the user asks about execution stats (e.g. 'how many requests today?', 'how many runs in the last 24 hours?', 'error rate?'). For 'today' use time_range 24h. Optional workflow_id to filter by one workflow (get id from list_workflows).",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "Optional UUID of the workflow to filter stats; omit for all workflows",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Time range: 24h (last 24 hours / today), 7d, 30d, or all",
                        "enum": ["24h", "7d", "30d", "all"],
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_executions",
            "description": "List recent workflow runs and chat runs with details (workflow name, time, status, brief output). Use when the user asks what ran or what came in (e.g. 'what ran?', 'show details', 'list recent runs', 'what ran in the last 24 hours?').",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_range": {
                        "type": "string",
                        "description": "Time window: 24h, 7d, 30d, or all",
                        "enum": ["24h", "7d", "30d", "all"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of items to return (default 30, max 50)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documentation",
            "description": "Search Heym platform documentation. Returns full markdown content of up to 5 matching docs. Use when the user asks about features, nodes, expressions, workflows, or how to use the app. Call at most 2 times per message. Use one comprehensive query (e.g. 'canvas features', 'portal', 'LLM node'). Always cite docs in your response with links like [Title](/docs/category/slug).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g. 'LLM node', 'expression DSL', 'cron trigger', 'credentials')",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_global_variables",
            "description": "Get global variables from the user's Global Variable Store. Use when the user asks about variables, their values, or wants to query/read stored variables (e.g. 'what are my variables?', 'what is the apiKey value?', 'list global variables'). Pass name to get a specific variable's value; omit to list all variable names and types.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Optional. Variable name to get. If omitted, returns list of all variables (name, type).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_teams",
            "description": "List teams the user is a member of. Use when the user asks about teams (e.g. 'my teams', 'which teams am I in?', 'who is in team X?', 'list my teams'). Optional team_name to filter by name (case-insensitive partial match). Returns team id, name, description, member count, and member emails for each team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "Optional. Filter teams by name (partial, case-insensitive).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schedule_events",
            "description": "List upcoming cron schedule occurrences for workflows (same data as the Scheduled calendar). Use when the user asks what is scheduled, when workflows run, this day/week/month, calendar, or upcoming cron runs. Pass view_window day, week, or month (aligned with the dashboard Scheduled tab). Optional reference_date as YYYY-MM-DD (defaults to today in the app timezone). Or pass start_iso and end_iso (ISO-8601) together for a custom range (max 62 days). Set include_shared to false for owned workflows only, true to include workflows shared with the user (default true).",
            "parameters": {
                "type": "object",
                "properties": {
                    "view_window": {
                        "type": "string",
                        "enum": ["day", "week", "month"],
                        "description": "Calendar window: day, week (Monday-Sunday), or month. Ignored if start_iso and end_iso are both set.",
                    },
                    "reference_date": {
                        "type": "string",
                        "description": "Optional anchor date YYYY-MM-DD for view_window. Omit to use today in the configured app timezone.",
                    },
                    "start_iso": {
                        "type": "string",
                        "description": "Optional range start (ISO-8601). Must be used with end_iso.",
                    },
                    "end_iso": {
                        "type": "string",
                        "description": "Optional range end (ISO-8601). Must be used with start_iso.",
                    },
                    "include_shared": {
                        "type": "boolean",
                        "description": "If true (default), include workflows shared with the user. If false, only workflows owned by the user.",
                        "default": True,
                    },
                },
                "required": [],
            },
        },
    },
]


async def get_credential_for_user(
    credential_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> Credential | None:
    result = await db.execute(
        select(Credential).where(Credential.id == credential_id, Credential.owner_id == user.id)
    )
    credential = result.scalar_one_or_none()

    if credential:
        return credential

    shared_result = await db.execute(
        select(Credential)
        .join(CredentialShare, CredentialShare.credential_id == Credential.id)
        .where(Credential.id == credential_id, CredentialShare.user_id == user.id)
    )
    return shared_result.scalar_one_or_none()


def get_openai_client(
    credential_type: CredentialType,
    config: dict,
) -> tuple[OpenAI, str]:
    """Build an OpenAI client and provider label for the given credential type."""
    if credential_type == CredentialType.google:
        return OpenAI(api_key=config.get("api_key"), base_url=GOOGLE_OPENAI_BASE_URL), "Google"

    if credential_type == CredentialType.custom:
        base_url = config.get("base_url", "").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = base_url + "/v1"
        return OpenAI(api_key=config.get("api_key"), base_url=base_url), "Custom"

    return OpenAI(api_key=config.get("api_key")), "OpenAI"


async def get_workflows_for_user_with_inputs(
    db: AsyncSession, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return list of workflows with id, name, description, input_fields, output_node for dashboard chat."""
    team_shared_ids = (
        select(WorkflowTeamShare.workflow_id)
        .join(TeamMember, TeamMember.team_id == WorkflowTeamShare.team_id)
        .where(TeamMember.user_id == user_id)
    )
    result = await db.execute(
        select(Workflow)
        .where(
            or_(
                Workflow.owner_id == user_id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(WorkflowShare.user_id == user_id)
                ),
                Workflow.id.in_(team_shared_ids),
            )
        )
        .order_by(Workflow.updated_at.desc())
    )
    workflows = result.scalars().all()
    out: list[dict[str, Any]] = []
    for w in workflows:
        input_fields = extract_input_fields_from_workflow(w)
        output_node = extract_output_node_from_workflow(w)
        out.append(
            {
                "id": str(w.id),
                "name": w.name,
                "description": w.description,
                "input_fields": [f.model_dump(by_alias=True) for f in input_fields],
                "output_node": output_node.model_dump() if output_node else None,
            }
        )
    return out


def _format_workflows_for_prompt(workflows: list[dict[str, Any]]) -> str:
    """Format workflow list for injection into dashboard chat system prompt."""
    if not workflows:
        return ""
    lines: list[str] = []
    for w in workflows:
        name = w.get("name") or "Unnamed"
        w_id = w.get("id") or ""
        desc = w.get("description") or ""
        inputs = w.get("input_fields") or []
        input_keys = [f.get("key") or f.get("name", "") for f in inputs if isinstance(f, dict)]
        parts = [f"- {name!r} (id: {w_id})"]
        if desc:
            parts.append(f"  description: {desc}")
        if input_keys:
            parts.append(f"  inputs: {input_keys}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


async def run_execute_workflow_tool(
    db: AsyncSession,
    user_id: uuid.UUID,
    workflow_id_str: str,
    inputs: dict[str, Any],
    public_base_url: str,
    cancel_event: Event | None = None,
) -> str:
    """Execute a workflow and return JSON string result for tool. Raises no exception; errors are returned in the result."""
    if cancel_event is not None and cancel_event.is_set():
        return json.dumps({"status": "cancelled", "error": "Execution cancelled"})

    try:
        wid = uuid.UUID(workflow_id_str)
    except ValueError:
        return json.dumps({"status": "error", "error": "Invalid workflow_id"})

    workflow = await get_workflow_for_user(db, wid, user_id)
    if workflow is None:
        return json.dumps({"status": "error", "error": "Workflow not found or no access"})

    if not workflow.nodes:
        return json.dumps({"status": "error", "error": "Workflow has no nodes"})

    workflow_cache = await collect_referenced_workflows(db, workflow.nodes)
    credentials_context = await get_credentials_context(db, user_id)

    enriched_inputs = {
        "headers": {},
        "query": {},
        "body": inputs,
    }

    try:
        execution_result = await asyncio.to_thread(
            execute_workflow,
            workflow_id=workflow.id,
            nodes=workflow.nodes,
            edges=workflow.edges or [],
            inputs=enriched_inputs,
            workflow_cache=workflow_cache,
            test_run=False,
            credentials_context=credentials_context,
            trace_user_id=user_id,
            cancel_event=cancel_event,
        )
        history_entry_id: str | None = None
        if execution_result.status == "pending":
            history_entry, _ = await persist_pending_hitl_execution(
                db=db,
                workflow=workflow,
                enriched_inputs=enriched_inputs,
                execution_result=execution_result,
                trigger_source="dashboard_chat",
                credentials_owner_id=user_id,
                trace_user_id=user_id,
                public_base_url=public_base_url,
            )
            history_entry_id = str(history_entry.id)
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
                status=execution_result.status,
                execution_time_ms=execution_result.execution_time_ms,
            )
        else:
            history_entry = ExecutionHistory(
                workflow_id=workflow.id,
                inputs=enriched_inputs,
                outputs=execution_result.outputs,
                node_results=execution_result.node_results,
                status=execution_result.status,
                execution_time_ms=execution_result.execution_time_ms,
                trigger_source="dashboard_chat",
            )
            db.add(history_entry)
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
                status=execution_result.status,
                execution_time_ms=execution_result.execution_time_ms,
            )
            for sub_exec in execution_result.sub_workflow_executions:
                sub_history = ExecutionHistory(
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    inputs=sub_exec.inputs,
                    outputs=sub_exec.outputs,
                    node_results=sub_exec.node_results,
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                    trigger_source=sub_exec.trigger_source,
                )
                db.add(sub_history)
                await upsert_workflow_analytics_snapshot(
                    db,
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    owner_id=None,
                    workflow_name_snapshot=sub_exec.workflow_name or "Sub-workflow",
                    status=sub_exec.status,
                    execution_time_ms=sub_exec.execution_time_ms,
                )
            await db.flush()
            history_entry_id = str(history_entry.id)

        def _nr_to_dict(r: Any) -> dict:
            if isinstance(r, dict):
                return r
            return {
                "node_id": getattr(r, "node_id", ""),
                "node_label": getattr(r, "node_label", ""),
                "node_type": getattr(r, "node_type", ""),
                "status": getattr(r, "status", ""),
                "output": getattr(r, "output", {}),
                "execution_time_ms": getattr(r, "execution_time_ms", 0),
                "error": getattr(r, "error", None),
            }

        node_results_serializable = [_nr_to_dict(r) for r in execution_result.node_results]
        pending_review = _extract_pending_review_from_execution_data(
            execution_result.outputs,
            node_results_serializable,
        )
        return json.dumps(
            {
                "status": execution_result.status,
                "outputs": execution_result.outputs,
                "node_results": node_results_serializable,
                "execution_time_ms": execution_result.execution_time_ms,
                "execution_history_id": history_entry_id,
                "pending_review": pending_review,
                "error": getattr(execution_result, "error", None),
            },
            default=str,
        )
    except WorkflowCancelledError:
        return json.dumps({"status": "cancelled", "error": "Execution cancelled"})
    except Exception as e:
        logger.exception("Dashboard chat execute_workflow failed")
        return json.dumps({"status": "error", "error": str(e)})


async def resolve_hitl_review_tool(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    action: str,
    request_id: str | None = None,
    review_url: str | None = None,
    edited_text: str | None = None,
    refusal_reason: str | None = None,
) -> str:
    """Resolve a pending HITL request and resume it in the background."""
    hitl_request: HITLRequest | None = None

    if request_id:
        try:
            request_uuid = uuid.UUID(request_id)
        except ValueError:
            return json.dumps({"status": "error", "error": "Invalid request_id"})
        result = await db.execute(select(HITLRequest).where(HITLRequest.id == request_uuid))
        hitl_request = result.scalar_one_or_none()
    elif review_url:
        token = urlparse(review_url).path.rstrip("/").split("/")[-1].strip()
        if not token:
            return json.dumps({"status": "error", "error": "Invalid review_url"})
        hitl_request = await get_hitl_request_by_token(db, token)
    else:
        return json.dumps(
            {
                "status": "error",
                "error": "request_id or review_url is required to resolve HITL review",
            }
        )

    if hitl_request is None:
        return json.dumps({"status": "error", "error": "Review request not found"})

    workflow = await get_workflow_for_user(db, hitl_request.workflow_id, user_id)
    if workflow is None:
        return json.dumps({"status": "error", "error": "Workflow not found or no access"})

    try:
        ensure_hitl_request_is_actionable(hitl_request)
    except HTTPException as exc:
        return json.dumps({"status": "error", "error": str(exc.detail)})

    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"accept", "edit", "refuse"}:
        return json.dumps({"status": "error", "error": "Invalid action"})
    if normalized_action == "edit" and not (edited_text or "").strip():
        return json.dumps({"status": "error", "error": "edited_text is required for edit action"})

    hitl_request.decision = normalized_action
    hitl_request.edited_text = (edited_text or "").strip() or None
    hitl_request.refusal_reason = (refusal_reason or "").strip() or None
    hitl_request.status = "resolved"
    hitl_request.resolved_at = datetime.now(timezone.utc)
    hitl_request.resume_error = None
    hitl_request.resolved_output = build_hitl_resolved_output(hitl_request)
    await db.flush()
    await db.commit()

    asyncio.create_task(resume_hitl_request_in_background(hitl_request.id))
    return json.dumps(
        {
            "status": "resolved",
            "request_id": str(hitl_request.id),
            "execution_history_id": str(hitl_request.execution_history_id),
            "workflow_name": hitl_request.workflow_name,
            "agent_label": hitl_request.agent_label,
            "decision": normalized_action,
        }
    )


async def wait_for_execution_update_tool(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    execution_history_id: str,
    interval_seconds: int = 5,
    max_checks: int = 5,
) -> str:
    """Wait and re-check a workflow execution history entry."""
    try:
        history_uuid = uuid.UUID(execution_history_id)
    except ValueError:
        return json.dumps({"status": "error", "error": "Invalid execution_history_id"})

    safe_interval_seconds = min(max(int(interval_seconds or 5), 1), 30)
    safe_max_checks = min(max(int(max_checks or 5), 1), 10)

    checks: list[dict[str, Any]] = []
    latest_history: ExecutionHistory | None = None

    for attempt in range(1, safe_max_checks + 1):
        if attempt > 1:
            await asyncio.sleep(safe_interval_seconds)

        result = await db.execute(
            select(ExecutionHistory).where(ExecutionHistory.id == history_uuid)
        )
        latest_history = result.scalar_one_or_none()
        if latest_history is None:
            return json.dumps({"status": "error", "error": "Execution history not found"})

        workflow = await get_workflow_for_user(db, latest_history.workflow_id, user_id)
        if workflow is None:
            return json.dumps({"status": "error", "error": "Workflow not found or no access"})

        checks.append(
            {
                "attempt": attempt,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "status": latest_history.status,
            }
        )
        if latest_history.status not in {"pending", "running"}:
            break

    if latest_history is None:
        return json.dumps({"status": "error", "error": "Execution history not found"})

    workflow = await get_workflow_for_user(db, latest_history.workflow_id, user_id)
    workflow_name = workflow.name if workflow else ""
    pending_review = _extract_pending_review_from_execution_data(
        latest_history.outputs or {},
        latest_history.node_results or [],
    )
    return json.dumps(
        {
            "status": latest_history.status,
            "execution_history_id": str(latest_history.id),
            "workflow_id": str(latest_history.workflow_id),
            "workflow_name": workflow_name,
            "checks_performed": len(checks),
            "interval_seconds": safe_interval_seconds,
            "checks": checks,
            "outputs": latest_history.outputs or {},
            "node_results": latest_history.node_results or [],
            "pending_review": pending_review,
            "execution_time_ms": latest_history.execution_time_ms,
            "started_at": latest_history.started_at.isoformat()
            if latest_history.started_at
            else None,
        },
        default=str,
    )


def _build_workflow_content_summary(workflow: Workflow) -> dict[str, Any]:
    """Build a short content summary of a workflow for LLM context (nodes, sticky notes, cron, etc.)."""
    nodes_out: list[dict[str, Any]] = []
    node_list = workflow.nodes if isinstance(workflow.nodes, list) else []
    for n in node_list:
        if not isinstance(n, dict):
            continue
        node_type = n.get("type") or "unknown"
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        label = data.get("label", "")
        entry: dict[str, Any] = {"type": node_type, "label": label}
        if node_type == "sticky":
            entry["note"] = data.get("note") or ""
        elif node_type == "cron":
            entry["cron_expression"] = data.get("cronExpression") or ""
        elif node_type == "wait":
            duration = data.get("duration")
            if duration is not None:
                entry["duration_seconds"] = duration
        elif node_type == "sendEmail":
            to_addr = data.get("to") or ""
            if to_addr:
                entry["to"] = to_addr
        elif node_type == "http":
            curl = data.get("curl") or ""
            if curl:
                entry["curl"] = curl[:500] + ("..." if len(curl) > 500 else "")
        nodes_out.append(entry)
    edges_out: list[dict[str, str]] = []
    edge_list = workflow.edges if isinstance(workflow.edges, list) else []
    for e in edge_list:
        if not isinstance(e, dict):
            continue
        edges_out.append(
            {
                "source": str(e.get("source", "")),
                "target": str(e.get("target", "")),
            }
        )
    return {
        "name": workflow.name,
        "nodes": nodes_out,
        "edges": edges_out,
    }


def _build_workflow_full_dsl(workflow: Workflow) -> dict[str, Any]:
    """Return full workflow DSL (nodes + edges with all data) for detailed queries."""
    nodes = workflow.nodes if isinstance(workflow.nodes, list) else []
    edges = workflow.edges if isinstance(workflow.edges, list) else []
    return {
        "name": workflow.name,
        "description": workflow.description or "",
        "nodes": nodes,
        "edges": edges,
    }


async def get_workflow_definition_tool(
    db: AsyncSession,
    user_id: uuid.UUID,
    workflow_id_str: str,
    full_details: bool = False,
) -> str:
    """Return workflow content as JSON string for dashboard chat tool. No execution."""
    try:
        wid = uuid.UUID(workflow_id_str)
    except ValueError:
        return json.dumps({"error": "Invalid workflow_id"})
    workflow = await get_workflow_for_user(db, wid, user_id)
    if workflow is None:
        return json.dumps({"error": "Workflow not found or no access"})
    if full_details:
        content = _build_workflow_full_dsl(workflow)
    else:
        content = _build_workflow_content_summary(workflow)
    return json.dumps(content, default=str)


def _unwrap_stored_value(stored: dict) -> object:
    """Unwrap value from stored dict."""
    if isinstance(stored, dict) and "v" in stored:
        return stored["v"]
    return stored


async def get_global_variables_tool(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str | None = None,
) -> str:
    """Return global variables for dashboard chat tool. List all or get one by name."""
    result = await db.execute(
        select(GlobalVariable)
        .where(GlobalVariable.owner_id == user_id)
        .order_by(GlobalVariable.name.asc())
    )
    variables = result.scalars().all()
    if name:
        for v in variables:
            if v.name == name:
                return json.dumps(
                    {"value": _unwrap_stored_value(v.value), "value_type": v.value_type},
                    default=str,
                )
        return json.dumps({"error": f"Variable '{name}' not found"})
    out = [
        {
            "name": v.name,
            "value": _unwrap_stored_value(v.value),
            "value_type": v.value_type,
        }
        for v in variables
    ]
    return json.dumps({"variables": out}, default=str)


async def get_teams_tool(
    db: AsyncSession,
    user_id: uuid.UUID,
    team_name: str | None = None,
) -> str:
    """Return teams the user is a member of for dashboard chat tool."""
    stmt = (
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id)
        .order_by(Team.created_at.desc())
    )
    if team_name and team_name.strip():
        term = f"%{team_name.strip().lower()}%"
        stmt = stmt.where(Team.name.ilike(term))
    result = await db.execute(stmt)
    teams = result.scalars().unique().all()

    out: list[dict[str, Any]] = []
    for team in teams:
        members_result = await db.execute(
            select(TeamMember, User)
            .join(User, User.id == TeamMember.user_id)
            .where(TeamMember.team_id == team.id)
        )
        members = [{"email": u.email, "name": u.name or ""} for _tm, u in members_result.all()]
        out.append(
            {
                "id": str(team.id),
                "name": team.name,
                "description": team.description or "",
                "member_count": len(members),
                "members": members,
            }
        )
    return json.dumps({"teams": out, "count": len(out)}, default=str)


MAX_DASHBOARD_CHAT_TOOL_ROUNDS = 33

IMAGE_PLACEHOLDER = "[image omitted - see workflow execution in UI]"


def _is_base64_image(s: str) -> bool:
    """Check if string looks like base64 image data."""
    if not isinstance(s, str) or len(s) < 100:
        return False
    return s.startswith("data:image/") or (
        s.startswith("/9j/") or s.startswith("iVBOR")  # JPEG/PNG base64
    )


def _extract_images_from_outputs(obj: Any) -> list[str]:
    """Recursively extract base64 image strings from workflow outputs and return as data URLs (deduplicated)."""
    out: list[str] = []
    seen: set[str] = set()

    def _collect(o: Any) -> None:
        if isinstance(o, str):
            if _is_base64_image(o):
                url = o if o.startswith("data:image/") else f"data:image/png;base64,{o}"
                if url not in seen:
                    seen.add(url)
                    out.append(url)
        elif isinstance(o, dict):
            for v in o.values():
                _collect(v)
        elif isinstance(o, list):
            for v in o:
                _collect(v)

    _collect(obj)
    return out


def _sanitize_for_llm_context(obj: Any) -> Any:
    """Recursively replace base64 image strings with placeholder to avoid context overflow."""
    if isinstance(obj, str):
        return IMAGE_PLACEHOLDER if _is_base64_image(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_llm_context(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_llm_context(v) for v in obj]
    return obj


def _extract_pending_review_from_candidate(candidate: Any) -> dict[str, str] | None:
    if not isinstance(candidate, dict):
        return None

    review_url = str(candidate.get("reviewUrl") or "").strip()
    if not review_url:
        return None

    payload: dict[str, str] = {
        "summary": str(candidate.get("summary") or "").strip(),
        "draft_text": str(candidate.get("draftText") or "").strip(),
        "review_url": review_url,
    }
    request_id = str(candidate.get("requestId") or "").strip()
    expires_at = str(candidate.get("expiresAt") or "").strip()

    if request_id:
        payload["request_id"] = request_id
    if expires_at:
        payload["expires_at"] = expires_at

    return payload


def _extract_pending_review_from_execution_data(
    outputs: Any, node_results: Any
) -> dict[str, str] | None:
    if isinstance(outputs, dict):
        for value in outputs.values():
            payload = _extract_pending_review_from_candidate(value)
            if payload:
                return payload

    if isinstance(node_results, list):
        for node_result in node_results:
            if not isinstance(node_result, dict):
                continue
            payload = _extract_pending_review_from_candidate(node_result.get("output"))
            if payload:
                return payload

    return None


def _sanitize_tool_result_for_llm(result_json: str, tool_name: str) -> str:
    """Sanitize tool result before sending to LLM: strip base64 images, cap size."""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return result_json[:8000] + ("..." if len(result_json) > 8000 else "")

    if (
        tool_name in {"execute_workflow", "wait_for_execution_update"}
        and isinstance(data, dict)
        and data.get("status") == "pending"
    ):
        pending_review = data.get("pending_review")
        if isinstance(pending_review, dict):
            compact_pending = {
                "status": "pending",
                "execution_history_id": data.get("execution_history_id"),
                "workflow_id": data.get("workflow_id"),
                "workflow_name": data.get("workflow_name"),
                "pending_review": pending_review,
            }
            return json.dumps(_sanitize_for_llm_context(compact_pending), default=str)

    sanitized = _sanitize_for_llm_context(data)
    out = json.dumps(sanitized, default=str)

    # Cap at ~24k tokens (~96k chars) to leave room for system prompt + history
    max_chars = 96_000
    if len(out) > max_chars:
        summary = _summarize_tool_result(tool_name, result_json)
        out = json.dumps({"truncated": True, "summary": summary, "original_length": len(out)})
    return out


def _extract_pending_hitl_review_payload(result_json: str) -> dict[str, str] | None:
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict) or data.get("status") != "pending":
        return None

    top_level_pending = data.get("pending_review")
    if isinstance(top_level_pending, dict):
        review_url = str(top_level_pending.get("review_url") or "").strip()
        if review_url:
            return {
                "summary": str(top_level_pending.get("summary") or "").strip(),
                "draft_text": str(top_level_pending.get("draft_text") or "").strip(),
                "review_url": review_url,
            }

    outputs = data.get("outputs") or {}
    if isinstance(outputs, dict):
        for value in outputs.values():
            payload = _extract_pending_review_from_candidate(value)
            if payload:
                return payload

    node_results = data.get("node_results") or []
    if isinstance(node_results, list):
        for node_result in node_results:
            if not isinstance(node_result, dict):
                continue
            payload = _extract_pending_review_from_candidate(node_result.get("output"))
            if payload:
                return payload

    return None


def _summarize_tool_result(tool_name: str, result_json: str) -> str:
    """Turn tool result JSON into a short summary for run history steps."""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return result_json[:200] + ("..." if len(result_json) > 200 else "")
    if tool_name == "list_workflows":
        count = data.get("count", 0) if isinstance(data, dict) else 0
        return f"{count} workflow(s) listed"
    if tool_name == "execute_workflow":
        if not isinstance(data, dict):
            return str(data)[:200]
        status = data.get("status", "")
        err = data.get("error")
        if err:
            return f"Error: {str(err)[:150]}"
        if status == "success":
            outputs = data.get("outputs") or {}
            if isinstance(outputs, dict) and outputs:
                parts = [f"Status: {status}"]
                for k, v in list(outputs.items())[:2]:
                    vstr = str(v)[:80] + ("..." if len(str(v)) > 80 else "")
                    parts.append(f"{k}: {vstr}")
                return " · ".join(parts)
            return "Workflow completed successfully"
        return f"Status: {status}"
    if tool_name == "resolve_hitl_review":
        if not isinstance(data, dict):
            return str(data)[:200]
        if data.get("error"):
            return f"Error: {str(data.get('error'))[:150]}"
        decision = str(data.get("decision") or "").strip()
        workflow_name = str(data.get("workflow_name") or "").strip()
        if workflow_name and decision:
            return f"HITL review resolved: {workflow_name} ({decision})"
        return f"Status: {str(data.get('status') or '')[:80]}"
    if tool_name == "wait_for_execution_update":
        if not isinstance(data, dict):
            return str(data)[:200]
        if data.get("error"):
            return f"Error: {str(data.get('error'))[:150]}"
        status = str(data.get("status") or "").strip()
        checks_performed = int(data.get("checks_performed") or 0)
        workflow_name = str(data.get("workflow_name") or "").strip()
        if workflow_name and status:
            return f"Execution status after {checks_performed} check(s): {workflow_name} ({status})"
        return f"Status: {status}"
    if tool_name == "get_workflow_definition":
        if not isinstance(data, dict):
            return str(data)[:200]
        if data.get("error"):
            return f"Error: {str(data.get('error'))[:150]}"
        name = data.get("name", "")
        nodes = data.get("nodes") or []
        n = len(nodes) if isinstance(nodes, list) else 0
        return f"Workflow content retrieved: {name!r} ({n} node(s))"
    if tool_name == "get_analytics_stats":
        if not isinstance(data, dict):
            return str(data)[:200]
        total = data.get("total_executions", 0) or 0
        rate = data.get("success_rate", 0) or 0
        return f"Analytics: {total} executions, {rate:.0f}% success"
    if tool_name == "get_recent_executions":
        if isinstance(data, list):
            return f"{len(data)} recent execution(s) listed"
        if isinstance(data, dict) and "executions" in data:
            return f"{len(data.get('executions', []))} recent execution(s) listed"
        return result_json[:150] + ("..." if len(result_json) > 150 else "")
    if tool_name == "search_documentation":
        if isinstance(data, dict) and "results" in data:
            results = data.get("results", [])
            return f"{len(results)} doc(s) found"
        if isinstance(data, dict) and "error" in data:
            return f"Error: {str(data.get('error'))[:150]}"
        return result_json[:200] + ("..." if len(result_json) > 200 else "")
    if tool_name == "get_teams":
        if isinstance(data, dict) and "teams" in data:
            count = len(data.get("teams", []))
            return f"{count} team(s) listed"
        if isinstance(data, dict) and "error" in data:
            return f"Error: {str(data.get('error'))[:150]}"
        return result_json[:150] + ("..." if len(result_json) > 150 else "")
    if tool_name == "get_global_variables":
        if isinstance(data, dict) and "error" in data:
            return f"Error: {str(data.get('error'))[:150]}"
        if isinstance(data, dict) and "variables" in data:
            vars_list = data.get("variables", [])
            return f"{len(vars_list)} variable(s)"
        if isinstance(data, dict) and "value" in data:
            return "Variable value retrieved"
        return result_json[:200] + ("..." if len(result_json) > 200 else "")
    if tool_name == "get_schedule_events":
        if isinstance(data, dict) and "error" in data:
            return f"Error: {str(data.get('error'))[:150]}"
        if isinstance(data, dict) and "total" in data:
            return f"{int(data.get('total') or 0)} scheduled occurrence(s)"
        return result_json[:200] + ("..." if len(result_json) > 200 else "")
    return result_json[:200] + ("..." if len(result_json) > 200 else "")


async def stream_dashboard_chat(
    client: OpenAI,
    model: str,
    system_prompt: str,
    messages: list[dict],
    db: AsyncSession,
    user: User,
    provider: str,
    public_base_url: str,
    trace_context: LLMTraceContext | None = None,
    cancel_event: Event | None = None,
    attachment: FileAttachment | None = None,
) -> AsyncGenerator[str, None]:
    """Run dashboard chat with tool use: loop non-streaming calls with tools until no tool_calls, then yield final content."""
    user_id = user.id
    is_reasoning = is_reasoning_model(model)
    base_kwargs: dict[str, Any] = {
        "model": model,
        "tools": DASHBOARD_CHAT_TOOLS,
        "stream": False,
    }
    if not is_reasoning:
        base_kwargs["temperature"] = 0.3

    messages_to_use = list(messages)
    rounds = 0
    start_time = time.time()
    response_parts: list[str] = []
    run_steps: list[dict[str, Any]] = []
    last_user_message = messages[-1].get("content", "") if messages else ""
    last_trace_request: dict[str, Any] | None = None

    def _record_dashboard_run(status: str, elapsed_ms: float) -> None:
        record_run_history(
            user_id=user_id,
            run_type="dashboard_chat",
            workflow_id=None,
            inputs={"message": last_user_message},
            outputs={"text": "".join(response_parts)},
            status=status,
            execution_time_ms=elapsed_ms,
            trigger_source="dashboard_chat",
            steps=run_steps,
        )

    try:
        while rounds < MAX_DASHBOARD_CHAT_TOOL_ROUNDS:
            if cancel_event is not None and cancel_event.is_set():
                elapsed_ms = (time.time() - start_time) * 1000
                _record_dashboard_run("cancelled", round(elapsed_ms, 2))
                return
            rounds += 1
            kwargs = {
                **base_kwargs,
                "messages": [{"role": "system", "content": system_prompt}] + messages_to_use,
            }
            last_trace_request = {**kwargs, "messages": kwargs["messages"]}
            round_start = time.time()
            response = client.chat.completions.create(**kwargs)
            round_elapsed_ms = (time.time() - round_start) * 1000
            choice = response.choices[0] if response.choices else None
            if not choice:
                elapsed_ms = (time.time() - start_time) * 1000
                if trace_context:
                    record_llm_trace(
                        context=trace_context,
                        request_type="chat.completions",
                        request=last_trace_request,
                        response={"model": model},
                        model=model,
                        provider=provider,
                        error="No response",
                        elapsed_ms=round(round_elapsed_ms, 2),
                    )
                _record_dashboard_run("error", round(elapsed_ms, 2))
                yield f"data: {json.dumps({'type': 'error', 'message': 'No response'})}\n\n"
                return

            msg = choice.message
            if trace_context:
                usage = getattr(response, "usage", None)
                record_llm_trace(
                    context=trace_context,
                    request_type="chat.completions",
                    request=last_trace_request,
                    response={
                        "content": msg.content or "",
                        "tool_calls": len(msg.tool_calls) if msg.tool_calls else 0,
                        "model": model,
                    },
                    model=model,
                    provider=provider,
                    error=None,
                    elapsed_ms=round(round_elapsed_ms, 2),
                    prompt_tokens=usage.prompt_tokens if usage else None,
                    completion_tokens=usage.completion_tokens if usage else None,
                    total_tokens=usage.total_tokens if usage else None,
                )
            if not msg.tool_calls:
                if cancel_event is not None and cancel_event.is_set():
                    elapsed_ms = (time.time() - start_time) * 1000
                    _record_dashboard_run("cancelled", round(elapsed_ms, 2))
                    return
                if msg.content:
                    response_parts.append(msg.content)
                    yield f"data: {json.dumps({'type': 'content', 'text': msg.content})}\n\n"
                final_text = "".join(response_parts)
                total_elapsed_ms = (time.time() - start_time) * 1000
                tool_steps_ms = sum(s.get("execution_time_ms", 0) for s in run_steps)
                assistant_step_ms = max(0, round(total_elapsed_ms - tool_steps_ms, 2))
                run_steps.append(
                    {
                        "label": "Assistant response",
                        "tool": None,
                        "request": {},
                        "response_summary": final_text,
                        "execution_time_ms": assistant_step_ms,
                    }
                )
                elapsed_ms = total_elapsed_ms
                _record_dashboard_run("success", round(elapsed_ms, 2))
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            messages_to_use.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                name = tc.function.name
                if cancel_event is not None and cancel_event.is_set():
                    elapsed_ms = (time.time() - start_time) * 1000
                    _record_dashboard_run("cancelled", round(elapsed_ms, 2))
                    return
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                if name == "list_workflows":
                    step_label = "Listing workflows..."
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    workflows = await get_workflows_for_user_with_inputs(db, user_id)
                    result = json.dumps({"count": len(workflows), "workflows": workflows})
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {},
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "execute_workflow":
                    workflow_id_str = args.get("workflow_id", "") or ""
                    step_label = "Running workflow..."
                    w = None
                    try:
                        wid = uuid.UUID(workflow_id_str)
                        w = await get_workflow_for_user(db, wid, user_id)
                        if w and w.name:
                            step_label = f'Running workflow "{w.name}"...'
                    except (ValueError, TypeError):
                        pass
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    inputs = dict(args.get("inputs") or {})
                    # Auto-inject attachment content into the matching workflow input field.
                    # The LLM only received metadata for images (no base64 in its context),
                    # so we inject the actual content here before execution.
                    if attachment is not None and w is not None:
                        field_keys = [f.key for f in extract_input_fields_from_workflow(w)]
                        inject_key = _find_injection_field(field_keys, attachment.kind)
                        if inject_key:
                            inputs[inject_key] = attachment.content
                    result = await run_execute_workflow_tool(
                        db,
                        user_id,
                        workflow_id_str,
                        inputs,
                        public_base_url,
                        cancel_event,
                    )
                    if cancel_event is not None and cancel_event.is_set():
                        elapsed_ms = (time.time() - start_time) * 1000
                        _record_dashboard_run("cancelled", round(elapsed_ms, 2))
                        return
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {
                                "workflow_id": workflow_id_str,
                                "inputs": args.get("inputs") or {},
                            },
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                    pending_review = _extract_pending_hitl_review_payload(result)
                    if pending_review:
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "type": "workflow_pending",
                                    **pending_review,
                                }
                            )
                            + "\n\n"
                        )
                    try:
                        data = json.loads(result)
                        if isinstance(data, dict) and data.get("status") == "success":
                            outputs = data.get("outputs") or {}
                            node_results = data.get("node_results") or []
                            # Scan both outputs and node_results (Playwright screenshots live in node outputs)
                            to_scan: dict[str, Any] = {"outputs": outputs}
                            if node_results:
                                to_scan["node_results"] = node_results
                            images = _extract_images_from_outputs(to_scan)
                            if images:
                                yield f"data: {json.dumps({'type': 'tool_output', 'tool': name, 'images': images})}\n\n"
                    except (json.JSONDecodeError, TypeError):
                        pass
                elif name == "resolve_hitl_review":
                    step_label = "Resolving human review..."
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    result = await resolve_hitl_review_tool(
                        db,
                        user_id,
                        action=str(args.get("action") or ""),
                        request_id=str(args.get("request_id") or "").strip() or None,
                        review_url=str(args.get("review_url") or "").strip() or None,
                        edited_text=str(args.get("edited_text") or "").strip() or None,
                        refusal_reason=str(args.get("refusal_reason") or "").strip() or None,
                    )
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": args,
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "wait_for_execution_update":
                    execution_history_id = str(args.get("execution_history_id") or "").strip()
                    interval_seconds_raw = args.get("interval_seconds")
                    max_checks_raw = args.get("max_checks")
                    interval_seconds = (
                        interval_seconds_raw if isinstance(interval_seconds_raw, int) else 5
                    )
                    max_checks = max_checks_raw if isinstance(max_checks_raw, int) else 5
                    step_label = "Waiting for workflow update..."
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    result = await wait_for_execution_update_tool(
                        db,
                        user_id,
                        execution_history_id=execution_history_id,
                        interval_seconds=interval_seconds,
                        max_checks=max_checks,
                    )
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {
                                "execution_history_id": execution_history_id,
                                "interval_seconds": interval_seconds,
                                "max_checks": max_checks,
                            },
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "get_workflow_definition":
                    workflow_id_str = args.get("workflow_id", "") or ""
                    full_details = bool(args.get("full_details", False))
                    step_label = "Reading workflow content..."
                    try:
                        wid = uuid.UUID(workflow_id_str)
                        w = await get_workflow_for_user(db, wid, user_id)
                        if w and w.name:
                            step_label = f'Reading "{w.name}" content...'
                    except (ValueError, TypeError):
                        pass
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    result = await get_workflow_definition_tool(
                        db, user_id, workflow_id_str, full_details=full_details
                    )
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {
                                "workflow_id": workflow_id_str,
                                "full_details": full_details,
                            },
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "get_analytics_stats":
                    workflow_id_str = args.get("workflow_id") or ""
                    time_range = args.get("time_range") or "24h"
                    wid: uuid.UUID | None = None
                    if workflow_id_str:
                        try:
                            wid = uuid.UUID(workflow_id_str)
                        except (ValueError, TypeError):
                            wid = None
                    step_label = "Fetching analytics..."
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    stats = await compute_analytics_stats(db, user_id, wid, time_range)
                    result = json.dumps(stats.model_dump(), default=str)
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {
                                "workflow_id": workflow_id_str or None,
                                "time_range": time_range,
                            },
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "get_recent_executions":
                    time_range = args.get("time_range") or "24h"
                    limit_raw = args.get("limit")
                    limit = 30
                    if isinstance(limit_raw, int) and 1 <= limit_raw <= 50:
                        limit = limit_raw
                    since_hours_map = {"24h": 24, "7d": 168, "30d": 720, "all": None}
                    since_hours = since_hours_map.get(time_range, 24)
                    step_label = "Listing recent executions..."
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    executions = await get_recent_executions_for_user(
                        db, user_id, limit=limit, since_hours=since_hours
                    )
                    result = json.dumps(executions, default=str)
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {"time_range": time_range, "limit": limit},
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "search_documentation":
                    query = args.get("query", "") or ""
                    step_label = "Searching documentation..."
                    if query:
                        step_label = f'Searching docs for "{query[:40]}{"..." if len(query) > 40 else ""}"...'
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    try:
                        from app.services.doc_index import DocIndexService

                        svc = DocIndexService.get_instance()
                        results = svc.search(query, top_k=5)
                        result = json.dumps({"results": results}, default=str)
                    except Exception as e:
                        logger.exception("search_documentation failed")
                        result = json.dumps({"error": str(e)})
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {"query": query},
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "get_global_variables":
                    var_name = args.get("name") or None
                    if isinstance(var_name, str) and not var_name.strip():
                        var_name = None
                    step_label = "Querying global variables..."
                    if var_name:
                        step_label = f'Getting variable "{var_name}"...'
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    result = await get_global_variables_tool(db, user_id, name=var_name)
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {"name": var_name} if var_name else {},
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "get_teams":
                    team_name_filter = args.get("team_name") or None
                    if isinstance(team_name_filter, str) and not team_name_filter.strip():
                        team_name_filter = None
                    step_label = "Listing teams..."
                    if team_name_filter:
                        step_label = f'Searching teams for "{team_name_filter[:30]}..."'
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    result = await get_teams_tool(db, user_id, team_name=team_name_filter)
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": (
                                {"team_name": team_name_filter} if team_name_filter else {}
                            ),
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                elif name == "get_schedule_events":
                    view_window = args.get("view_window")
                    if isinstance(view_window, str):
                        view_window = view_window.strip().lower()
                    reference_date_str = args.get("reference_date")
                    if isinstance(reference_date_str, str) and not reference_date_str.strip():
                        reference_date_str = None
                    start_iso = args.get("start_iso")
                    end_iso = args.get("end_iso")
                    raw_include = args.get("include_shared", True)
                    if isinstance(raw_include, bool):
                        include_shared = raw_include
                    elif isinstance(raw_include, str):
                        include_shared = raw_include.strip().lower() in ("1", "true", "yes")
                    else:
                        include_shared = True
                    step_label = "Loading scheduled runs..."
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    try:
                        tz = get_configured_timezone()
                        range_start, range_end = resolve_schedule_tool_range(
                            view_window if isinstance(view_window, str) else None,
                            str(reference_date_str) if reference_date_str else None,
                            str(start_iso).strip() if start_iso else None,
                            str(end_iso).strip() if end_iso else None,
                            tz,
                        )
                        schedule_resp = await fetch_schedule_events_for_user(
                            db,
                            user,
                            range_start,
                            range_end,
                            include_shared,
                        )
                        result = json.dumps(
                            {
                                "events": [e.model_dump(mode="json") for e in schedule_resp.events],
                                "total": schedule_resp.total,
                                "range_start": range_start.isoformat(),
                                "range_end": range_end.isoformat(),
                                "include_shared": include_shared,
                            },
                            default=str,
                        )
                    except ValueError as err:
                        result = json.dumps({"error": str(err)})
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {
                                "view_window": view_window,
                                "reference_date": reference_date_str,
                                "start_iso": start_iso,
                                "end_iso": end_iso,
                                "include_shared": include_shared,
                            },
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                else:
                    step_label = f"Running {name}..."
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    result = json.dumps({"error": f"Unknown tool: {name}"})
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": args,
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
                content_for_llm = _sanitize_tool_result_for_llm(result, name)
                messages_to_use.append(
                    {"role": "tool", "content": content_for_llm, "tool_call_id": tc.id}
                )

        elapsed_ms = (time.time() - start_time) * 1000
        if trace_context:
            record_llm_trace(
                context=trace_context,
                request_type="chat.completions",
                request=last_trace_request,
                response={"text": "".join(response_parts), "model": model},
                model=model,
                provider=provider,
                error="Too many tool rounds",
                elapsed_ms=round(elapsed_ms, 2),
            )
        _record_dashboard_run("error", round(elapsed_ms, 2))
        yield f"data: {json.dumps({'type': 'error', 'message': 'Too many tool rounds'})}\n\n"
    except Exception as e:
        if cancel_event is not None and cancel_event.is_set():
            elapsed_ms = (time.time() - start_time) * 1000
            _record_dashboard_run("cancelled", round(elapsed_ms, 2))
            return
        logger.exception("Dashboard chat stream failed")
        elapsed_ms = (time.time() - start_time) * 1000
        if trace_context:
            record_llm_trace(
                context=trace_context,
                request_type="chat.completions",
                request=last_trace_request,
                response={"text": "".join(response_parts), "model": model},
                model=model,
                provider=provider,
                error=str(e),
                elapsed_ms=round(elapsed_ms, 2),
            )
        _record_dashboard_run("error", round(elapsed_ms, 2))
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


async def stream_llm_response(
    client: OpenAI,
    model: str,
    system_prompt: str,
    messages: list[dict],
    provider: str,
    trace_context: LLMTraceContext | None = None,
    run_type: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream assistant responses while optionally recording a trace and run history."""
    all_messages = [{"role": "system", "content": system_prompt}]
    all_messages.extend(messages)

    is_reasoning = is_reasoning_model(model)

    kwargs = {
        "model": model,
        "messages": all_messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    if not is_reasoning:
        kwargs["temperature"] = 0.1

    trace_request = {**kwargs, "messages": all_messages}
    response_parts: list[str] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    start_time = time.time()

    try:
        stream = client.chat.completions.create(**kwargs)

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                response_parts.append(content)
                yield f"data: {json.dumps({'type': 'content', 'text': content})}\n\n"
            if chunk.usage:
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens
                total_tokens = chunk.usage.total_tokens

        elapsed_ms = (time.time() - start_time) * 1000
        if trace_context:
            record_llm_trace(
                context=trace_context,
                request_type="chat.completions.stream",
                request=trace_request,
                response={"text": "".join(response_parts), "model": model},
                model=model,
                provider=provider,
                error=None,
                elapsed_ms=round(elapsed_ms, 2),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
        if run_type and trace_context:
            record_run_history(
                user_id=trace_context.user_id,
                run_type=run_type,
                workflow_id=trace_context.workflow_id,
                inputs={"message": messages[-1].get("content", "") if messages else ""},
                outputs={"text": "".join(response_parts)},
                status="success",
                execution_time_ms=round(elapsed_ms, 2),
                trigger_source=trace_context.source,
            )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        if trace_context:
            record_llm_trace(
                context=trace_context,
                request_type="chat.completions.stream",
                request=trace_request,
                response={"text": "".join(response_parts), "model": model},
                model=model,
                provider=provider,
                error=str(e),
                elapsed_ms=round(elapsed_ms, 2),
            )
        if run_type and trace_context:
            record_run_history(
                user_id=trace_context.user_id,
                run_type=run_type,
                workflow_id=trace_context.workflow_id,
                inputs={"message": messages[-1].get("content", "") if messages else ""},
                outputs={"text": "".join(response_parts)},
                status="error",
                execution_time_ms=round(elapsed_ms, 2),
                trigger_source=trace_context.source,
            )
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.post("/workflow-assistant")
async def workflow_assistant_stream(
    request: AIAssistantRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    credential = await get_credential_for_user(request.credential_id, current_user, db)

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    client, provider = get_openai_client(credential.type, config)

    node_templates = await template_service.list_node_templates(db, current_user, None)
    node_template_payload = [
        {
            "id": str(t.id),
            "name": t.name,
            "description": t.description,
            "tags": list(t.tags or []),
            "node_type": t.node_type,
            "node_data": dict(t.node_data or {}),
        }
        for t in node_templates
    ]

    if request.ask_mode:
        system_prompt = CANVAS_ASK_SYSTEM_PROMPT
        if request.current_workflow:
            wf_summary = json.dumps(request.current_workflow, ensure_ascii=False)
            system_prompt += f"\n\nCurrent workflow context:\n```json\n{wf_summary}\n```"
        if node_template_payload:
            names_block = "\n".join(
                f"- {x['name']} ({x['node_type']})" for x in node_template_payload[:50]
            )
            system_prompt += (
                "\n\nNode templates available in the editor palette (Templates section):\n"
                + names_block
                + "\n"
            )
    else:
        system_prompt = build_assistant_prompt(
            request.current_workflow,
            request.available_workflows,
            current_user.user_rules,
            available_node_templates=node_template_payload,
        )

    logger.debug(
        "\n" + "=" * 60 + "\n"
        "[AI ASSISTANT REQUEST]\n"
        f"Model: {request.model}\n"
        f"Ask Mode: {request.ask_mode}\n"
        f"User Message: {request.message}\n"
        f"System Prompt Length: {len(system_prompt)} chars\n"
        f"System Prompt:\n{system_prompt}\n" + "=" * 60
    )

    messages = []
    if request.conversation_history:
        messages.extend(request.conversation_history)
    messages.append({"role": "user", "content": request.message})

    workflow_id = None
    if request.current_workflow:
        wf_id = request.current_workflow.get("id")
        if wf_id:
            workflow_id = uuid.UUID(wf_id) if isinstance(wf_id, str) else wf_id

    trace_context = LLMTraceContext(
        user_id=current_user.id,
        credential_id=credential.id,
        workflow_id=workflow_id,
        node_label="AI Ask" if request.ask_mode else "AI Builder",
        source="assistant",
    )

    return StreamingResponse(
        stream_llm_response(
            client,
            request.model,
            system_prompt,
            messages,
            provider,
            trace_context,
            run_type="workflow_assistant",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/dashboard-chat")
async def dashboard_chat_stream(
    http_request: Request,
    request: DashboardChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    credential = await get_credential_for_user(request.credential_id, current_user, db)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    client, provider = get_openai_client(credential.type, config)

    history = request.conversation_history or []
    if len(history) > MAX_DASHBOARD_CHAT_HISTORY:
        history = history[-MAX_DASHBOARD_CHAT_HISTORY:]
    messages: list[dict] = list(history)
    messages.append(_build_user_message(request.message, request.attachment))

    trace_context = LLMTraceContext(
        user_id=current_user.id,
        credential_id=credential.id,
        workflow_id=None,
        node_label=_get_dashboard_chat_node_label(request.chat_surface),
        source="dashboard_chat",
    )

    workflows = await get_workflows_for_user_with_inputs(db, current_user.id)
    workflows_block = _format_workflows_for_prompt(workflows)

    agents_md = _load_agents_md_content()
    system_prompt = DASHBOARD_CHAT_SYSTEM_PROMPT
    if agents_md:
        system_prompt = (
            "## Heym Platform Context\n\n"
            "Use the following Heym platform documentation to answer questions about the platform, structure, commands, code style, and conventions:\n\n"
            + agents_md
            + "\n\n---\n\n"
            + system_prompt
        )
    if workflows_block:
        system_prompt = (
            system_prompt
            + "\n\nAvailable workflows (always check these first when user asks for information):\n"
            + workflows_block
        )
    if request.user_rules and request.user_rules.strip():
        system_prompt = (
            system_prompt
            + "\n\nUser preferences / custom instructions (follow these when relevant):\n"
            + request.user_rules.strip()
        )
    if request.client_local_datetime and request.client_local_datetime.strip():
        system_prompt = (
            system_prompt
            + "\n\nCurrent user local date and time: "
            + request.client_local_datetime.strip()
        )
    if request.attachment:
        system_prompt = system_prompt + "\n\n" + _ATTACHMENT_ROUTING_INSTRUCTIONS
    public_base_url = build_public_base_url(http_request)
    cancel_event = Event()

    async def cancel_on_disconnect() -> None:
        try:
            while not cancel_event.is_set():
                if await http_request.is_disconnected():
                    cancel_event.set()
                    return
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            return

    async def event_generator() -> AsyncGenerator[str, None]:
        watcher = asyncio.create_task(cancel_on_disconnect())
        try:
            async for chunk in stream_dashboard_chat(
                client,
                request.model,
                system_prompt,
                messages,
                db,
                current_user,
                provider,
                public_base_url,
                trace_context,
                cancel_event,
                request.attachment,
            ):
                if cancel_event.is_set():
                    break
                yield chunk
        finally:
            cancel_event.set()
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


FIX_TRANSCRIPTION_PROMPT = """You are a text correction assistant. Your task is to fix speech-to-text transcription errors.

Rules:
1. Fix spelling mistakes and typos
2. Fix grammar and punctuation errors
3. Preserve the original meaning and intent
4. Keep the same language as the input
5. Do not add or remove information
6. Return ONLY the corrected text, nothing else

Common words (keywords when fixing transcription): Workflow , input , output, ai , agents , assistant.

Input text to fix:"""


@router.post("/fix-transcription", response_model=FixTranscriptionResponse)
async def fix_transcription(
    request: FixTranscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FixTranscriptionResponse:
    credential = await get_credential_for_user(request.credential_id, current_user, db)

    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    client, _ = get_openai_client(credential.type, config)

    is_reasoning = is_reasoning_model(request.model)
    system_prompt = f"{FIX_TRANSCRIPTION_PROMPT} /nothink"

    kwargs = {
        "model": request.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.text},
        ],
        "extra_body": {"disable_reasoning": True},
    }

    if not is_reasoning:
        kwargs["temperature"] = 0.3

    response = client.chat.completions.create(**kwargs)
    fixed_text = response.choices[0].message.content or request.text

    return FixTranscriptionResponse(fixed_text=fixed_text.strip())
