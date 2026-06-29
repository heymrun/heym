from __future__ import annotations

import copy
from importlib import import_module
from typing import Any

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the llm node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    NodeTraceableExecutionError = _workflow_executor.NodeTraceableExecutionError  # noqa: N806
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data
    node_label = ctx.node_label

    combined_input = ""
    for data in self._visible_inputs(inputs).values():
        if isinstance(data, dict) and "text" in data:
            combined_input += str(data["text"]) + " "
        else:
            combined_input += str(data) + " "
    combined_input = combined_input.strip()

    credential_id = node_data.get("credentialId")
    model = node_data.get("model", "")
    system_instruction_template = node_data.get("systemInstruction", "")
    user_message_template = node_data.get("userMessage", "$input.text")
    temperature = node_data.get("temperature", 0.7)
    reasoning_effort = node_data.get("reasoningEffort")
    max_tokens = node_data.get("maxTokens")
    json_output_enabled = bool(node_data.get("jsonOutputEnabled", False))
    json_output_schema = node_data.get("jsonOutputSchema", "")
    batch_mode_enabled = bool(node_data.get("batchModeEnabled", False))
    output_type = node_data.get("outputType", "text")
    image_size = node_data.get("imageSize", "1024x1024")
    image_quality = node_data.get("imageQuality", "auto")
    image_input_enabled = bool(node_data.get("imageInputEnabled", False))
    image_input_template = node_data.get("imageInput", "")

    system_instruction = (
        self._resolve_template(system_instruction_template, inputs, node_id)
        if system_instruction_template
        else None
    )

    if json_output_enabled and json_output_schema:
        schema_hint = (
            f"\n\nIMPORTANT: You MUST respond with valid JSON that follows this "
            f"exact structure:\n{json_output_schema}\n"
            "Do NOT use any other JSON structure. Match the field names exactly."
        )
        if system_instruction:
            system_instruction = system_instruction + schema_hint
        else:
            system_instruction = schema_hint.strip()

    if batch_mode_enabled:
        stripped_user_message_template = str(user_message_template or "").strip()
        if stripped_user_message_template.startswith("$"):
            user_message = self.resolve_expression(
                stripped_user_message_template,
                inputs,
                node_id,
                preserve_type=True,
            )
        else:
            user_message = self._resolve_template(user_message_template, inputs, node_id)
    else:
        user_message = self._resolve_template(user_message_template, inputs, node_id)
        if not user_message:
            user_message = combined_input

    image_input = None
    if image_input_enabled:
        resolved_image_input = self.resolve_expression(
            image_input_template.strip(), inputs, node_id
        )
        if resolved_image_input:
            image_input = resolved_image_input

    guardrails_enabled = bool(node_data.get("guardrailsEnabled", False))
    guardrails_config = (
        {
            "enabled": True,
            "categories": node_data.get("guardrailsCategories") or [],
            "severity": node_data.get("guardrailsSeverity", "medium"),
            "credential_id": node_data.get("guardrailCredentialId") or "",
            "model": node_data.get("guardrailModel") or "",
        }
        if guardrails_enabled
        else None
    )

    fallback_credential_id = (node_data.get("fallbackCredentialId") or "").strip() or None
    fallback_model = (node_data.get("fallbackModel") or "").strip() or None
    batch_status_signature: tuple[object, ...] | None = None

    def batch_status_callback(progress: dict[str, Any]) -> None:
        nonlocal batch_status_signature
        signature = (
            progress.get("status"),
            progress.get("rawStatus"),
            progress.get("total"),
            progress.get("completed"),
            progress.get("failed"),
        )
        if signature == batch_status_signature:
            return
        batch_status_signature = signature
        self._handle_llm_batch_status_update(
            node_id=node_id,
            node_label=node_label,
            payload=progress,
        )

    def batch_should_abort() -> str | None:
        try:
            self.check_cancelled()
        except Exception as exc:
            return str(exc)
        return None

    output = self._execute_llm_node(
        credential_id=credential_id,
        node_id=node_id,
        model=model,
        system_instruction=system_instruction,
        user_message=user_message,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
        json_output_enabled=json_output_enabled,
        json_output_schema=json_output_schema,
        image_input=image_input,
        output_type=output_type,
        image_size=image_size,
        image_quality=image_quality,
        guardrails_config=guardrails_config,
        fallback_credential_id=fallback_credential_id,
        fallback_model=fallback_model,
        batch_mode_enabled=batch_mode_enabled,
        on_batch_status_update=batch_status_callback if batch_mode_enabled else None,
        should_abort=batch_should_abort if batch_mode_enabled else None,
        request_timeout=float(node_data.get("requestTimeoutSeconds") or 60),
    )
    trace_id = self._pop_internal_trace_id(output)
    if output.get("error"):
        if trace_id:
            raise NodeTraceableExecutionError(f"LLM error: {output.get('error')}", trace_id)
        raise ValueError(f"LLM error: {output.get('error')}")
    if json_output_enabled:
        llm_output = output
        if batch_mode_enabled:
            parsed_results: list[dict[str, Any]] = []
            parsed_values: list[object] = []
            for raw_item in llm_output.get("results") or []:
                item = copy.deepcopy(raw_item)
                if item.get("status") == "success":
                    try:
                        parsed_item = self._parse_json_output(str(item.get("text", "")))
                        item["parsed"] = parsed_item
                        parsed_values.append(parsed_item)
                    except Exception as exc:
                        item["status"] = "error"
                        item["error"] = str(exc)
                parsed_results.append(item)
            output = dict(llm_output)
            output["results"] = parsed_results
            output["parsedResults"] = parsed_values
            output["completed"] = sum(
                1 for item in parsed_results if item.get("status") == "success"
            )
            output["failed"] = sum(1 for item in parsed_results if item.get("status") != "success")
        else:
            parsed = self._parse_json_output(str(output.get("text", "")))
            if isinstance(parsed, dict):
                output = dict(parsed)
            else:
                output = {"value": parsed}
        if llm_output.get("fallbackUsed") is not None:
            output["fallbackUsed"] = llm_output["fallbackUsed"]
        if llm_output.get("model"):
            output["model"] = llm_output["model"]
    self._restore_internal_trace_id(output, trace_id)
    return output
