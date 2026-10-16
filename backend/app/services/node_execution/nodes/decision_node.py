from __future__ import annotations

import json
from importlib import import_module
from typing import Any

from app.services.decision_images import PreparedImage, prepare_image
from app.services.decision_models import (
    DecisionProviderError,
    DecisionRequestError,
    build_decision_body,
    call_decision_model,
    load_decision_credential,
)
from app.services.image_input import load_image_bytes
from app.services.node_execution.base import NodeExecutionContext
from app.services.ssrf_guard import SsrfBlockedError


def _resolve(executor: Any, template: object, inputs: dict, node_id: str) -> Any:
    """Resolve one configuration value, keeping a lone expression's own type.

    `state` accepts a string, an object or an array, so `$input` must arrive as the
    object it is rather than flattened into text.
    """
    if not isinstance(template, str) or "$" not in template:
        return template
    if executor._is_single_dollar_expression(template.strip()):
        return executor.resolve_expression(template.strip(), inputs, node_id, preserve_type=True)
    return executor._resolve_template(template, inputs, node_id)


def _resolve_questions(executor: Any, questions: list, inputs: dict, node_id: str) -> list[dict]:
    resolved: list[dict] = []
    for question in questions or []:
        if not isinstance(question, dict):
            resolved.append(question)
            continue
        row = dict(question)
        for key in ("instructions", "criteriaTrue", "criteriaFalse"):
            if key in row:
                row[key] = _resolve(executor, row.get(key), inputs, node_id)
        options = row.get("options")
        if isinstance(options, list):
            row["options"] = [
                {
                    "key": option.get("key"),
                    "description": _resolve(executor, option.get("description"), inputs, node_id),
                }
                if isinstance(option, dict)
                else option
                for option in options
            ]
        levels = row.get("levels")
        if isinstance(levels, list):
            row["levels"] = [_resolve(executor, level, inputs, node_id) for level in levels]
        resolved.append(row)
    return resolved


def _load_images(executor: Any, rows: list, inputs: dict, node_id: str) -> list[PreparedImage]:
    """Resolve, fetch and prepare each image row, naming the row in any failure."""
    prepared: list[PreparedImage] = []
    for row in rows or []:
        if not isinstance(row, dict):
            raise DecisionRequestError("Decision node has a malformed image row")
        name = str(row.get("name") or "").strip()
        if not name:
            raise DecisionRequestError("Every decision image needs a name")
        source = _resolve(executor, row.get("source"), inputs, node_id)
        if source is None or (isinstance(source, str) and not source.strip()):
            raise DecisionRequestError(f"Image '{name}' resolved to nothing")
        if not isinstance(source, str):
            raise DecisionRequestError(
                f"Image '{name}' must resolve to a URL, a data URL or base64 text"
            )
        try:
            raw, _mime_type = load_image_bytes(source.strip(), subject="Decision image URL")
        except SsrfBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - any fetch or decode failure names the row
            raise DecisionRequestError(f"Image '{name}': {exc}") from exc
        prepared.append(prepare_image(name, raw))
    return prepared


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the decision node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    NodeTraceableExecutionError = _workflow_executor.NodeTraceableExecutionError  # noqa: N806
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    credential_id = str(node_data.get("credentialId") or "").strip()
    if not credential_id:
        raise ValueError("Decision node requires a decision credential")

    timeout = float(node_data.get("requestTimeoutSeconds") or 60)

    try:
        if bool(node_data.get("customBodyEnabled")):
            raw_body = str(node_data.get("customBody") or "").strip()
            if not raw_body:
                raise DecisionRequestError("Custom request body is empty")
            resolved_body = self._resolve_template(raw_body, inputs, node_id)
            try:
                body = json.loads(resolved_body)
            except (json.JSONDecodeError, ValueError) as exc:
                raise DecisionRequestError(f"Custom request body is not valid JSON: {exc}") from exc
            if not isinstance(body, dict):
                raise DecisionRequestError("Custom request body must be a JSON object")
        else:
            images = (
                _load_images(self, node_data.get("images") or [], inputs, node_id)
                if bool(node_data.get("imagesEnabled"))
                else []
            )
            body = build_decision_body(
                model=str(node_data.get("model") or ""),
                state=_resolve(self, node_data.get("state"), inputs, node_id),
                questions=_resolve_questions(
                    self, node_data.get("questions") or [], inputs, node_id
                ),
                images=images,
            )

        credential = load_decision_credential(credential_id)
    except DecisionRequestError as exc:
        raise ValueError(str(exc)) from exc

    trace_context = self._build_llm_trace_context(credential_id, node_id)

    def _recorded_trace_id() -> str | None:
        """The id `record_llm_trace` appended for this call, if it wrote one."""
        if trace_context is None or not trace_context.trace_ids:
            return None
        return str(trace_context.trace_ids[-1])

    try:
        response = call_decision_model(
            base_url=credential["base_url"],
            api_key=credential["api_key"],
            body=body,
            timeout=timeout,
            trace_context=trace_context,
        )
    except DecisionProviderError as exc:
        # A failed call is still traced, so keep the execution log linked to it.
        trace_id = _recorded_trace_id()
        if trace_id:
            raise NodeTraceableExecutionError(str(exc), trace_id) from exc
        raise ValueError(str(exc)) from exc

    output = dict(response)
    trace_id = _recorded_trace_id()
    if trace_id:
        # The executor pops this into node metadata, which draws the Traces link.
        output["_trace_id"] = trace_id
    return output
