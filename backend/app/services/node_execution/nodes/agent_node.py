from __future__ import annotations

import copy
import time
from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the agent node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    NodeResult = _workflow_executor.NodeResult  # noqa: N806
    NodeTraceableExecutionError = _workflow_executor.NodeTraceableExecutionError  # noqa: N806
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    start_time = ctx.start_time
    node_type = ctx.node_type
    node_data = ctx.node_data
    node_label = ctx.node_label

    agent_guardrails_enabled = bool(node_data.get("guardrailsEnabled", False))
    agent_guardrails_config = (
        {
            "enabled": True,
            "categories": node_data.get("guardrailsCategories") or [],
            "severity": node_data.get("guardrailsSeverity", "medium"),
            "credential_id": node_data.get("guardrailCredentialId") or "",
            "model": node_data.get("guardrailModel") or "",
        }
        if agent_guardrails_enabled
        else None
    )
    agent_json_output_enabled = bool(node_data.get("jsonOutputEnabled", False))
    hitl_enabled = bool(node_data.get("hitlEnabled", False))
    if hitl_enabled and agent_json_output_enabled:
        raise ValueError("HITL is not supported when JSON output is enabled on the agent node.")
    output = self._execute_agent_node(
        node_id, inputs, node_data, guardrails_config=agent_guardrails_config
    )
    trace_id = self._pop_internal_trace_id(output)
    pending_meta = output.pop("_hitl_pending", None)
    if agent_json_output_enabled and not output.get("error"):
        agent_output = output
        parsed = self._parse_json_output(str(output.get("text", "")))
        if isinstance(parsed, dict):
            output = dict(parsed)
        else:
            output = {"value": parsed}
        if agent_output.get("fallbackUsed") is not None:
            output["fallbackUsed"] = agent_output["fallbackUsed"]
        if agent_output.get("model"):
            output["model"] = agent_output["model"]
        self._restore_internal_trace_id(output, trace_id)
    if output.get("error"):
        if trace_id:
            raise NodeTraceableExecutionError(f"Agent error: {output.get('error')}", trace_id)
        raise ValueError(f"Agent error: {output.get('error')}")
    if hitl_enabled and isinstance(pending_meta, dict):
        summary = str(pending_meta.get("summary") or "").strip()
        if not summary:
            summary = f"{node_label} requires review."
        draft_text = str(pending_meta.get("draft_text") or output.get("text", "") or "")
        pending_output = {
            "decision": None,
            "summary": summary,
            "draftText": draft_text,
            "reviewUrl": None,
            "requestId": None,
            "expiresAt": None,
            "shareText": None,
            "shareMarkdown": None,
        }
        hitl_history = copy.deepcopy(output.get("hitlHistory") or [])
        if isinstance(hitl_history, list) and hitl_history:
            pending_output["hitlHistory"] = hitl_history
        execution_time_ms = (time.time() - start_time) * 1000
        pending_result = NodeResult(
            node_id=node_id,
            node_label=node_label,
            node_type=node_type,
            status="pending",
            output=pending_output,
            execution_time_ms=execution_time_ms,
            metadata={
                "hitl": {
                    "summary": summary,
                    "draft_text": draft_text,
                    "original_agent_output": copy.deepcopy(output),
                    "resume_mode": str(pending_meta.get("resume_mode") or "inject_output"),
                    "review_mode": str(pending_meta.get("review_mode") or "tool_call"),
                    "blocked_action": str(pending_meta.get("blocked_action") or "").strip() or None,
                    "tool_name": str(pending_meta.get("tool_name") or "").strip() or None,
                    "tool_source": str(pending_meta.get("tool_source") or "").strip() or None,
                }
            },
        )
        if trace_id:
            pending_result.metadata["trace_id"] = trace_id
        if isinstance(hitl_history, list) and hitl_history:
            pending_result.metadata["hitl"]["history"] = hitl_history
        agent_state = pending_meta.get("agent_state")
        if isinstance(agent_state, dict) and agent_state:
            pending_result.metadata["hitl"]["agent_state"] = copy.deepcopy(agent_state)
        tool_arguments = pending_meta.get("tool_arguments")
        if isinstance(tool_arguments, dict):
            pending_result.metadata["hitl"]["approved_tool_call"] = {
                "tool_name": str(pending_meta.get("tool_name") or "").strip() or None,
                "tool_source": str(pending_meta.get("tool_source") or "").strip() or None,
                "tool_arguments": copy.deepcopy(tool_arguments),
                "match_strategy": str(pending_meta.get("match_strategy") or "exact_args"),
            }
        return pending_result
    self._restore_internal_trace_id(output, trace_id)
    return output
