from __future__ import annotations

import uuid
from concurrent.futures import Future
from importlib import import_module
from threading import Event, Thread

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the execute node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    SubWorkflowExecution = _workflow_executor.SubWorkflowExecution  # noqa: N806
    WorkflowExecutor = _workflow_executor.WorkflowExecutor  # noqa: N806
    _SHARED_EXECUTOR = _workflow_executor._SHARED_EXECUTOR  # noqa: N806
    _clear_sub_execution = _workflow_executor._clear_sub_execution
    _register_sub_execution = _workflow_executor._register_sub_execution
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    execute_workflow_id = node_data.get("executeWorkflowId", "")
    execute_input_mappings = node_data.get("executeInputMappings", [])
    execute_input_template = node_data.get("executeInput", "")
    execute_do_not_wait = bool(node_data.get("executeDoNotWait", False))

    if execute_input_mappings and len(execute_input_mappings) > 0:
        execute_inputs = {}
        for mapping in execute_input_mappings:
            key = mapping.get("key", "")
            value_template = mapping.get("value", "")
            if value_template:
                if value_template.startswith("$"):
                    resolved_value = self.resolve_expression(value_template, inputs, node_id)
                else:
                    resolved_value = self.evaluate_message_template(value_template, inputs, node_id)
                execute_inputs[key] = resolved_value
            else:
                execute_inputs[key] = ""
    elif execute_input_template:
        if execute_input_template.startswith("$"):
            transformed_input = self.resolve_expression(execute_input_template, inputs, node_id)
        else:
            transformed_input = self.evaluate_message_template(
                execute_input_template, inputs, node_id
            )
        if isinstance(transformed_input, str):
            execute_inputs = {"text": transformed_input}
        elif isinstance(transformed_input, dict):
            execute_inputs = transformed_input
        else:
            execute_inputs = {"value": transformed_input}
    else:
        first_input = self._first_visible_input(inputs)
        if isinstance(first_input, dict):
            execute_inputs = dict(first_input)
        else:
            execute_inputs = {"value": first_input}

    if execute_workflow_id and execute_workflow_id in self.workflow_cache:
        target_workflow = self.workflow_cache[execute_workflow_id]
        self._refresh_vars_context_cache()
        merged_global = (
            self._merged_global_context_cache
            if self._merged_global_context_cache is not None
            else {}
        )
        _exec_node_cancel_event = Event()
        if self.cancel_event is not None:
            _exec_node_parent = self.cancel_event

            def _bridge_exec_node_cancel() -> None:
                _exec_node_parent.wait()
                _exec_node_cancel_event.set()

            Thread(target=_bridge_exec_node_cancel, daemon=True).start()
        sub_executor = WorkflowExecutor(
            nodes=target_workflow["nodes"],
            edges=target_workflow["edges"],
            workflow_cache=self.workflow_cache,
            test_mode=False,
            credentials_context=self.credentials_context,
            global_variables_context=merged_global,
            workflow_id=uuid.UUID(execute_workflow_id),
            trace_user_id=self.trace_user_id,
            actor_user_id=self.actor_user_id,
            sub_workflow_invocation_depth=self._sub_workflow_invocation_depth + 1,
            cancel_event=_exec_node_cancel_event,
            invoked_by_agent=self._invoked_by_agent,
        )
        enriched_execute_inputs = {
            "headers": {},
            "query": {},
            "body": execute_inputs,
        }

        if execute_do_not_wait:
            wf_name = target_workflow.get("name", "")
            inputs_snap = dict(execute_inputs)
            bg_callback_done = Event()

            def _on_execute_do_not_wait_done(f: Future) -> None:
                try:
                    WorkflowExecutor._record_bg_sub_workflow_done(
                        f, self, execute_workflow_id, wf_name, inputs_snap
                    )
                finally:
                    bg_callback_done.set()

            bg_future = _SHARED_EXECUTOR.submit(
                sub_executor.execute,
                workflow_id=uuid.UUID(execute_workflow_id),
                initial_inputs=enriched_execute_inputs,
            )
            bg_future.add_done_callback(_on_execute_do_not_wait_done)
            with self._bg_futures_lock:
                self._bg_futures.append(
                    (
                        bg_future,
                        bg_callback_done,
                        execute_workflow_id,
                        wf_name,
                        inputs_snap,
                    )
                )
            output = {"status": "dispatched", "workflow_id": execute_workflow_id}
        else:
            _sub_exec_id = uuid.uuid4()
            _register_sub_execution(
                workflow_id=uuid.UUID(execute_workflow_id),
                execution_id=_sub_exec_id,
                event=_exec_node_cancel_event,
                recoverable=False,
            )
            try:
                sub_result = sub_executor.execute(
                    workflow_id=uuid.UUID(execute_workflow_id),
                    initial_inputs=enriched_execute_inputs,
                )
                if sub_result.allow_downstream_pending:
                    sub_result.join_allow_downstream()
            finally:
                _clear_sub_execution(_sub_exec_id)
            if sub_result.status == "pending":
                raise ValueError("HITL is not supported inside Execute node sub-workflows.")

            sub_exec = SubWorkflowExecution(
                workflow_id=execute_workflow_id,
                inputs=execute_inputs,
                outputs=sub_result.outputs,
                status=sub_result.status,
                execution_time_ms=sub_result.execution_time_ms,
                node_results=sub_result.node_results,
                workflow_name=target_workflow.get("name", ""),
                trigger_source=("AI Agents" if self._invoked_by_agent else "SUB_WORKFLOW"),
            )
            with self.lock:
                self.sub_workflow_executions.append(sub_exec)
                self.sub_workflow_executions.extend(sub_executor.sub_workflow_executions)

            output = {
                "workflow_id": execute_workflow_id,
                "status": sub_result.status,
                "outputs": sub_result.outputs,
                "execution_time_ms": sub_result.execution_time_ms,
            }
    else:
        output = execute_inputs
    return output
