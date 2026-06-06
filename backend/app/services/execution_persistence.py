"""Persist workflow execution history, analytics snapshots, and global variables."""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.db.models import ExecutionHistory
from app.services.global_variables_service import persist_global_variables_from_execution
from app.services.workflow_executor import (
    ExecutionResult,
    SubWorkflowExecution,
    _to_json_compatible,
)

logger = logging.getLogger(__name__)


def _coerce_execution_fields(
    outputs: object,
    node_results: object,
    *,
    json_compatible: bool,
) -> tuple[object, list]:
    if json_compatible:
        return _to_json_compatible(outputs), _to_json_compatible(node_results)
    if isinstance(node_results, list):
        return outputs, node_results
    return outputs, list(node_results)


def _sub_execution_fields(sub_exec: SubWorkflowExecution | dict[str, Any]) -> dict[str, Any]:
    if isinstance(sub_exec, SubWorkflowExecution):
        return {
            "workflow_id": sub_exec.workflow_id,
            "inputs": sub_exec.inputs,
            "outputs": sub_exec.outputs,
            "node_results": sub_exec.node_results,
            "status": sub_exec.status,
            "execution_time_ms": sub_exec.execution_time_ms,
            "workflow_name": sub_exec.workflow_name,
            "trigger_source": sub_exec.trigger_source,
        }
    return {
        "workflow_id": sub_exec["workflow_id"],
        "inputs": sub_exec.get("inputs", {}),
        "outputs": sub_exec.get("outputs", {}),
        "node_results": sub_exec.get("node_results", []),
        "status": sub_exec["status"],
        "execution_time_ms": sub_exec["execution_time_ms"],
        "workflow_name": sub_exec.get("workflow_name", ""),
        "trigger_source": sub_exec.get("trigger_source", "SUB_WORKFLOW"),
    }


async def persist_workflow_execution_analytics(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    workflow_name: str,
    status: str,
    execution_time_ms: float,
) -> None:
    """Record a single analytics snapshot for a workflow execution."""
    logger.debug(
        "Persisting execution analytics for workflow %s (status=%s, time_ms=%.2f)",
        workflow_id,
        status,
        execution_time_ms,
    )
    await upsert_workflow_analytics_snapshot(
        db,
        workflow_id=workflow_id,
        owner_id=owner_id,
        workflow_name_snapshot=workflow_name,
        status=status,
        execution_time_ms=execution_time_ms,
    )


async def persist_sub_workflow_execution_histories(
    db: AsyncSession,
    sub_workflow_executions: list[SubWorkflowExecution | dict[str, Any]],
    *,
    json_compatible: bool = False,
) -> None:
    """Persist execution history and analytics for sub-workflow runs."""
    if not sub_workflow_executions:
        return

    logger.info(
        "Persisting sub-workflow execution history for %d workflow(s)",
        len(sub_workflow_executions),
    )
    for sub_exec in sub_workflow_executions:
        fields = _sub_execution_fields(sub_exec)
        inputs = fields["inputs"]
        outputs = fields["outputs"]
        node_results = fields["node_results"]
        if json_compatible:
            inputs = _to_json_compatible(inputs)
            outputs = _to_json_compatible(outputs)
            node_results = _to_json_compatible(node_results)

        sub_history = ExecutionHistory(
            workflow_id=uuid.UUID(str(fields["workflow_id"])),
            inputs=inputs,
            outputs=outputs,
            node_results=node_results,
            status=fields["status"],
            execution_time_ms=float(fields["execution_time_ms"]),
            trigger_source=fields["trigger_source"],
        )
        db.add(sub_history)
        await persist_workflow_execution_analytics(
            db,
            workflow_id=uuid.UUID(str(fields["workflow_id"])),
            owner_id=None,
            workflow_name=fields["workflow_name"] or "Sub-workflow",
            status=fields["status"],
            execution_time_ms=float(fields["execution_time_ms"]),
        )


async def persist_workflow_execution_record(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    workflow_name: str,
    owner_id: uuid.UUID,
    inputs: dict,
    outputs: object,
    node_results: object,
    status: str,
    execution_time_ms: float,
    trigger_source: str,
    workflow_nodes: list[dict],
    workflow_cache: dict[str, dict],
    sub_workflow_executions: list[SubWorkflowExecution | dict[str, Any]],
    credentials_owner_id: uuid.UUID | None = None,
    json_compatible: bool = False,
    persist_global_variables: bool = True,
    persist_sub_workflows: bool = True,
) -> ExecutionHistory:
    """Create main execution history plus optional sub-workflow and global-variable persistence."""
    logger.info(
        "Persisting execution record for workflow %s (trigger=%s, status=%s, "
        "sub_workflows=%d, persist_globals=%s)",
        workflow_id,
        trigger_source,
        status,
        len(sub_workflow_executions),
        persist_global_variables,
    )
    normalized_outputs, normalized_node_results = _coerce_execution_fields(
        outputs,
        node_results,
        json_compatible=json_compatible,
    )
    normalized_inputs = _to_json_compatible(inputs) if json_compatible else inputs
    credentials_owner = credentials_owner_id or owner_id

    history_entry = ExecutionHistory(
        workflow_id=workflow_id,
        inputs=normalized_inputs,
        outputs=normalized_outputs,
        node_results=normalized_node_results,
        status=status,
        execution_time_ms=execution_time_ms,
        trigger_source=trigger_source,
    )
    db.add(history_entry)
    await persist_workflow_execution_analytics(
        db,
        workflow_id=workflow_id,
        owner_id=owner_id,
        workflow_name=workflow_name,
        status=status,
        execution_time_ms=execution_time_ms,
    )

    if persist_sub_workflows and sub_workflow_executions:
        await persist_sub_workflow_execution_histories(
            db,
            sub_workflow_executions,
            json_compatible=json_compatible,
        )

    if persist_global_variables:
        await persist_global_variables_from_execution(
            db,
            credentials_owner,
            workflow_nodes,
            workflow_cache,
            normalized_node_results,
            sub_workflow_executions,
        )

    return history_entry


async def persist_execution_result(
    db: AsyncSession,
    *,
    workflow_id: uuid.UUID,
    workflow_name: str,
    owner_id: uuid.UUID,
    inputs: dict,
    result: ExecutionResult,
    trigger_source: str,
    workflow_nodes: list[dict],
    workflow_cache: dict[str, dict],
    credentials_owner_id: uuid.UUID | None = None,
    json_compatible: bool = False,
    persist_global_variables: bool = True,
    persist_sub_workflows: bool = True,
) -> ExecutionHistory:
    """Persist artifacts for a completed ``ExecutionResult``."""
    logger.debug(
        "Persisting execution result for workflow %s (trigger=%s, status=%s)",
        workflow_id,
        trigger_source,
        result.status,
    )
    return await persist_workflow_execution_record(
        db,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        owner_id=owner_id,
        inputs=inputs,
        outputs=result.outputs,
        node_results=result.node_results,
        status=result.status,
        execution_time_ms=result.execution_time_ms,
        trigger_source=trigger_source,
        workflow_nodes=workflow_nodes,
        workflow_cache=workflow_cache,
        sub_workflow_executions=result.sub_workflow_executions,
        credentials_owner_id=credentials_owner_id,
        json_compatible=json_compatible,
        persist_global_variables=persist_global_variables,
        persist_sub_workflows=persist_sub_workflows,
    )


async def update_execution_history_and_persist_artifacts(
    db: AsyncSession,
    history_entry: ExecutionHistory,
    *,
    workflow_id: uuid.UUID,
    workflow_name: str,
    owner_id: uuid.UUID,
    outputs: object,
    node_results: object,
    status: str,
    execution_time_ms: float,
    workflow_nodes: list[dict],
    workflow_cache: dict[str, dict],
    sub_workflow_executions: list[SubWorkflowExecution | dict[str, Any]],
    credentials_owner_id: uuid.UUID | None = None,
    json_compatible: bool = False,
    refresh_main_analytics: bool = True,
) -> None:
    """Update an existing history row and persist sub-workflows, globals, and analytics."""
    logger.info(
        "Updating execution history %s for workflow %s (status=%s, sub_workflows=%d)",
        history_entry.id,
        workflow_id,
        status,
        len(sub_workflow_executions),
    )
    normalized_outputs, normalized_node_results = _coerce_execution_fields(
        outputs,
        node_results,
        json_compatible=json_compatible,
    )
    credentials_owner = credentials_owner_id or owner_id

    history_entry.outputs = normalized_outputs
    history_entry.node_results = normalized_node_results
    history_entry.status = status
    history_entry.execution_time_ms = execution_time_ms
    flag_modified(history_entry, "outputs")
    flag_modified(history_entry, "node_results")

    if sub_workflow_executions:
        await persist_sub_workflow_execution_histories(
            db,
            sub_workflow_executions,
            json_compatible=json_compatible,
        )

    await persist_global_variables_from_execution(
        db,
        credentials_owner,
        workflow_nodes,
        workflow_cache,
        normalized_node_results,
        sub_workflow_executions,
    )

    if refresh_main_analytics:
        await persist_workflow_execution_analytics(
            db,
            workflow_id=workflow_id,
            owner_id=owner_id,
            workflow_name=workflow_name,
            status=status,
            execution_time_ms=execution_time_ms,
        )
