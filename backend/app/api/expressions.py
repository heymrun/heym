"""Expression evaluation API."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.workflows import get_credentials_context, get_workflow_for_user
from app.db.models import LLM_CREDENTIAL_TYPES, CredentialType, User, Workflow
from app.db.session import get_db
from app.services.credential_access import get_accessible_credential
from app.services.encryption import decrypt_config
from app.services.expression_evaluator import (
    EXPRESSION_MAX_LENGTH,
    ExpressionEvaluateResponse,
    ExpressionEvaluatorService,
    build_eval_context,
    build_vars_context,
    get_selected_loop_total,
)
from app.services.global_variables_service import get_global_variables_context
from app.services.hitl_service import build_public_base_url
from app.services.llm_service import execute_llm
from app.services.llm_trace import LLMTraceContext
from app.services.model_router import build_router_for_credential
from app.services.workflow_dsl_prompt import (
    DASHBOARD_WIDGET_PROMPT_HINT,
    WORKFLOW_DSL_SYSTEM_PROMPT,
)
from app.services.workflow_executor import mask_credentials_context

router = APIRouter()

# Enough room for brief reasoning plus long expressions; low values truncate completions and break parsing.
EXPRESSION_GENERATE_MAX_OUTPUT_TOKENS = 8192

# One keystroke can offer a full method list; cap the batch so a single request stays bounded.
COMPLETION_PREVIEW_MAX_EXPRESSIONS = 40
# Previews sit on one dropdown row, so keep them short instead of shipping whole payloads.
COMPLETION_PREVIEW_MAX_CHARS = 160


class NodeResultItem(BaseModel):
    """A node result supplied by the frontend canvas after a test run."""

    node_id: str
    label: str
    output: Any


class ExpressionContextRequest(BaseModel):
    """Evaluation context shared by the evaluate and completion-preview endpoints."""

    workflow_id: UUID
    current_node_id: str
    field_name: str | None = None
    input_body: Any = None
    selected_loop_iteration_index: int | None = None
    node_results: list[NodeResultItem] = Field(default_factory=list)


class ExpressionEvaluateRequest(ExpressionContextRequest):
    """Request payload for the unified expression evaluator endpoint."""

    expression: str = Field(..., max_length=EXPRESSION_MAX_LENGTH)


class ExpressionCompletionPreviewRequest(ExpressionContextRequest):
    """Candidate expressions from the autocomplete dropdown, one per suggestion row."""

    expressions: list[str] = Field(
        default_factory=list,
        max_length=COMPLETION_PREVIEW_MAX_EXPRESSIONS,
    )


class ExpressionCompletionPreviewItem(BaseModel):
    """Preview for one candidate; `preview` is null when the candidate has no answer."""

    expression: str
    preview: str | None = None
    result_type: str | None = None


class ExpressionCompletionPreviewResponse(BaseModel):
    """Previews in the same order as the requested expressions."""

    previews: list[ExpressionCompletionPreviewItem]


class ExpressionGeneratePriorAttempt(BaseModel):
    """When regenerating: previous expression plus how it behaved when evaluated."""

    expression: str = ""
    evaluation_error: str | None = None
    evaluated_result: Any | None = None


class ExpressionGenerateRequest(BaseModel):
    """Request payload for AI-assisted expression generation."""

    description: str = Field(default="")
    input_value: str | None = None
    workflow_id: UUID
    credential_id: UUID
    model: str
    current_node_id: str | None = None
    node_results: list[NodeResultItem] = Field(default_factory=list)
    prior_attempt: ExpressionGeneratePriorAttempt | None = None


class ExpressionGenerateResponse(BaseModel):
    """Response containing the generated expression string."""

    expression: str


def _build_node_context_string(node_results: list[NodeResultItem]) -> str:
    """Format node results into a compact context block for the LLM."""
    if not node_results:
        return (
            "No prior run data available. Generate based on node labels and workflow conventions."
        )
    lines = ["Available node outputs from the last workflow run:"]
    for item in node_results:
        output_preview = json.dumps(item.output, default=str)
        lines.append(f'\n- Node label: "{item.label}" (id: {item.node_id})')
        lines.append(f"  Output: {output_preview}")
    return "\n".join(lines)


def _normalize_generated_expression(response_text: str) -> str:
    """Extract a single Heym expression from an LLM response."""
    text = response_text.strip()
    if not text:
        raise ValueError("Generated response did not contain a Heym expression")

    if text.startswith("```"):
        lines = text.splitlines()
        body_lines = lines[1:] if len(lines) > 1 else []
        while body_lines and body_lines[-1].strip() == "```":
            body_lines = body_lines[:-1]
        text = "\n".join(body_lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, str):
        text = parsed.strip()
    elif isinstance(parsed, dict) and isinstance(parsed.get("expression"), str):
        text = parsed["expression"].strip()

    expression_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("$")]
    if expression_lines:
        return expression_lines[0]

    if text.startswith("$"):
        return text

    tail_line = re.search(r"(?m)^\s*(\$\S.*?)\s*$", text)
    if tail_line:
        candidate = tail_line.group(1).strip()
        if candidate.startswith("$"):
            return candidate

    inline = re.search(r"\$[^\n]+", text)
    if inline:
        return inline.group(0).strip()

    raise ValueError("Generated response did not contain a Heym expression")


def _finalize_generated_expression(expression: str) -> str:
    """Strip stray markdown/backticks LLMs sometimes append after the DSL."""
    s = expression.strip()
    while s.endswith("`"):
        s = s[:-1].rstrip()
    return s


def _format_variables_block(vars_ctx: dict[str, Any], global_ctx: dict[str, Any]) -> str:
    """Human-readable vars snapshot for the generation prompt."""
    lines: list[str] = []
    lines.append("### Workflow `$vars` namespace (pinned output or last-run output upstream)")
    lines.append(json.dumps(vars_ctx, default=str, indent=2) if vars_ctx else "<empty>")
    lines.append("")
    lines.append("### Global variables (`$global.<name>`)")
    lines.append(json.dumps(global_ctx, default=str, indent=2) if global_ctx else "<none>")
    return "\n".join(lines)


def _format_prior_attempt_block(prior: ExpressionGeneratePriorAttempt) -> str:
    """Tell the model what failed so regeneration explores a different expression."""
    err = prior.evaluation_error.strip() if isinstance(prior.evaluation_error, str) else ""
    result_preview = (
        json.dumps(prior.evaluated_result, default=str, indent=2)
        if prior.evaluated_result is not None
        else "<none>"
    )
    return (
        "\n\n---\n\n"
        "## Previous attempt — unsatisfactory\n\n"
        "The expression below was already tried. Treat it as incorrect or inadequate "
        "(wrong value, evaluator error, or mismatch with user intent). "
        "Try a genuinely different `$…` expression—different node path, variable, "
        "filtering, or structure—not a trivial duplicate.\n\n"
        f"Previous expression:\n{prior.expression.strip()}\n\n"
        f"Evaluator/runtime error:\n{err or '<none>'}\n\n"
        "Evaluated result value when evaluation succeeded structurally:\n"
        f"{result_preview}\n"
    )


async def _generate_expression(
    db: AsyncSession,
    request: ExpressionGenerateRequest,
    current_user: User,
) -> str:
    """Call the LLM to produce a single expression string from a plain-text description."""
    credential = await get_accessible_credential(
        db=db,
        credential_id=request.credential_id,
        user_id=current_user.id,
    )
    if not credential:
        raise ValueError("Credential not found")

    if credential.type not in LLM_CREDENTIAL_TYPES:
        raise ValueError("Credential must be OpenAI, Google, or Custom type")

    config = decrypt_config(credential.encrypted_config)
    router = build_router_for_credential(
        credential_id=str(credential.id),
        credential_name=credential.name,
        credential_type=credential.type.value,
        config=config,
    )
    api_key = config.get("api_key", "")
    base_url = config.get("base_url") if credential.type == CredentialType.custom else None

    workflow = await get_workflow_by_id(request.workflow_id, db, current_user)
    if workflow is None:
        raise ValueError("Workflow not found")

    workflow_nodes = list(workflow.nodes or [])
    workflow_edges = list(workflow.edges or [])
    canvas_results = [
        {"node_id": item.node_id, "label": item.label, "output": item.output}
        for item in request.node_results
    ]
    vars_ctx = build_vars_context(
        workflow_nodes,
        canvas_results,
        workflow_edges=workflow_edges,
        current_node_id=request.current_node_id,
    )
    global_ctx = await get_global_variables_context(db, current_user.id)
    vars_block = _format_variables_block(vars_ctx, global_ctx)

    generate_suffix = (
        "\n\n---\n\n"
        "## Expression Generation Task\n\n"
        "Given the workflow context below, return ONLY a single bare expression that satisfies "
        "the user's description. No explanation, no JSON, no markdown – just the expression string.\n"
        "The expression must follow the Heym expression DSL described above.\n"
        "Start the expression with `$`."
    )
    system_prompt = WORKFLOW_DSL_SYSTEM_PROMPT + generate_suffix
    if getattr(workflow, "kind", None) == "dashboard_widget":
        system_prompt += DASHBOARD_WIDGET_PROMPT_HINT

    node_context = _build_node_context_string(request.node_results)
    input_value = (request.input_value or "").strip()
    input_context = (
        f"Evaluator input value: {input_value}\n"
        "Treat this value as the user's current intent or draft expression."
        if input_value
        else "Evaluator input value: <empty>"
    )
    user_message = (
        f"{input_context}\n\nUser intent: {request.description.strip()}\n\n"
        f"{node_context}\n\n{vars_block}"
    )
    if request.prior_attempt is not None:
        user_message += _format_prior_attempt_block(request.prior_attempt)

    trace_temperature = 0.42 if request.prior_attempt is not None else 0.2

    trace_ctx = LLMTraceContext(
        user_id=current_user.id,
        credential_id=request.credential_id,
        workflow_id=request.workflow_id,
        node_id=request.current_node_id,
        source="expression_builder",
        node_label="Expression Builder",
    )
    result = await execute_llm(
        credential_type=credential.type.value,
        api_key=api_key,
        base_url=base_url,
        model=request.model,
        system_instruction=system_prompt,
        user_message=user_message,
        temperature=trace_temperature,
        max_tokens=EXPRESSION_GENERATE_MAX_OUTPUT_TOKENS,
        trace_context=trace_ctx,
        router=router,
    )
    raw = _normalize_generated_expression(result.get("text", ""))
    return _finalize_generated_expression(raw)


async def get_workflow_by_id(
    workflow_id: UUID,
    db: AsyncSession,
    user: User,
) -> Workflow | None:
    """Load a workflow only when the caller has access to it."""
    return await get_workflow_for_user(db, workflow_id, user.id)


@dataclass
class EvaluationSetup:
    """Everything needed to evaluate expressions for one canvas evaluation request."""

    service: ExpressionEvaluatorService
    context: dict[str, Any]
    workflow_nodes: list[Any]
    workflow_edges: list[Any]


async def build_evaluation_setup(
    request: ExpressionContextRequest,
    http_request: Request,
    db: AsyncSession,
    current_user: User,
) -> EvaluationSetup:
    """Load the workflow and build the evaluator context shared by both evaluate endpoints."""
    workflow = await get_workflow_by_id(request.workflow_id, db, current_user)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    workflow_nodes = list(workflow.nodes or [])
    workflow_edges = list(workflow.edges or [])
    canvas_results = [
        {
            "node_id": item.node_id,
            "label": item.label,
            "output": item.output,
        }
        for item in request.node_results
    ]
    context = build_eval_context(
        workflow_nodes,
        canvas_results,
        workflow_edges=workflow_edges,
        current_node_id=request.current_node_id,
        initial_inputs=request.input_body,
        selected_loop_iteration_index=request.selected_loop_iteration_index,
    )
    vars_context = build_vars_context(
        workflow_nodes,
        canvas_results,
        workflow_edges=workflow_edges,
        current_node_id=request.current_node_id,
    )

    credentials_owner_id = current_user.id if current_user else workflow.owner_id
    credentials_context = await get_credentials_context(db, credentials_owner_id)
    preview_credentials_context = mask_credentials_context(credentials_context)
    global_variables_context = await get_global_variables_context(db, credentials_owner_id)

    service = ExpressionEvaluatorService(
        workflow_nodes=workflow_nodes,
        workflow_edges=workflow_edges,
        credentials_context=preview_credentials_context,
        global_variables_context=global_variables_context,
        vars_context=vars_context,
        workflow_id=workflow.id,
        workflow_name=workflow.name or "",
        workflow_description=workflow.description or "",
        public_base_url=build_public_base_url(http_request),
    )
    return EvaluationSetup(
        service=service,
        context=context,
        workflow_nodes=workflow_nodes,
        workflow_edges=workflow_edges,
    )


def format_completion_preview(
    evaluated: ExpressionEvaluateResponse,
    expression: str,
) -> str | None:
    """Render a one-line example answer, or None when the candidate produced no answer."""
    if evaluated.error is not None or evaluated.result is None:
        return None

    value = evaluated.result
    # Unresolved references echo the source text back; that is not an answer worth showing.
    if isinstance(value, str) and value.strip() == expression.strip():
        return None

    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(value)

    collapsed = " ".join(rendered.split())
    if not collapsed:
        return None
    if len(collapsed) > COMPLETION_PREVIEW_MAX_CHARS:
        return collapsed[: COMPLETION_PREVIEW_MAX_CHARS - 1] + "…"
    return collapsed


@router.post(
    "/evaluate",
    response_model=ExpressionEvaluateResponse,
    status_code=status.HTTP_200_OK,
)
async def evaluate_expression(
    request: ExpressionEvaluateRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExpressionEvaluateResponse:
    """Evaluate an expression or template using pinned data and last-run node outputs."""
    setup = await build_evaluation_setup(request, http_request, db, current_user)
    response = setup.service.evaluate(
        request.expression,
        setup.context,
        current_node_id=request.current_node_id,
    )
    response.selected_loop_total = get_selected_loop_total(
        setup.workflow_nodes,
        setup.workflow_edges,
        request.current_node_id,
        setup.context,
        setup.service,
    )
    return response


@router.post(
    "/completion-previews",
    response_model=ExpressionCompletionPreviewResponse,
    status_code=status.HTTP_200_OK,
)
async def preview_completion_expressions(
    request: ExpressionCompletionPreviewRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExpressionCompletionPreviewResponse:
    """Evaluate autocomplete candidates so the dialog can show an example answer per suggestion."""
    if not request.expressions:
        return ExpressionCompletionPreviewResponse(previews=[])

    setup = await build_evaluation_setup(request, http_request, db, current_user)

    previews: list[ExpressionCompletionPreviewItem] = []
    for expression in request.expressions:
        candidate = expression.strip()
        if not candidate or len(candidate) > EXPRESSION_MAX_LENGTH:
            previews.append(ExpressionCompletionPreviewItem(expression=expression))
            continue

        try:
            evaluated = setup.service.evaluate(
                candidate,
                setup.context,
                current_node_id=request.current_node_id,
            )
        except Exception:
            # A broken candidate is expected here - it must leave its row blank, not fail the batch.
            previews.append(ExpressionCompletionPreviewItem(expression=expression))
            continue

        previews.append(
            ExpressionCompletionPreviewItem(
                expression=expression,
                preview=format_completion_preview(evaluated, candidate),
                result_type=evaluated.result_type if evaluated.error is None else None,
            )
        )

    return ExpressionCompletionPreviewResponse(previews=previews)


@router.post(
    "/generate",
    response_model=ExpressionGenerateResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_expression(
    request: ExpressionGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExpressionGenerateResponse:
    """Generate a Heym expression from a plain-text description using an LLM."""
    try:
        expression = await _generate_expression(db=db, request=request, current_user=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ExpressionGenerateResponse(expression=expression)
