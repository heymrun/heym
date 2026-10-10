"""The run list behind History and Heym Work's Activity.

Workflow runs of workflows the user can access, plus the user's own chat and assistant
runs, filtered the way the History dialog filters them. The statement selects explicit
columns and the module imports no settings, so Heym Work runs the same query under its
read-only database role.
"""

import uuid

from sqlalchemy import String, case, cast, literal, null, or_, select, union_all
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement, Select, Subquery

from app.db.models import ExecutionHistory, RunHistory, Workflow
from app.services.workflow_access import workflow_access_clause

# A recovery that could not re-run a run after a restart stores "failed". To a reader that
# is the same outcome as "error", so the Error filter returns both.
_HISTORY_STATUS_GROUPS: dict[str, tuple[str, ...]] = {"error": ("error", "failed")}


def history_status_clause(
    column: InstrumentedAttribute, execution_status: object
) -> ColumnElement | None:
    """Build the WHERE clause for a history status filter, or None for "no filter".

    Anything that is not a non-blank string means "no filter": tests call the endpoint
    functions directly, where FastAPI has not resolved ``Query(default=None)``.
    """
    if not isinstance(execution_status, str):
        return None
    cleaned = execution_status.strip()
    if not cleaned:
        return None
    statuses = _HISTORY_STATUS_GROUPS.get(cleaned, (cleaned,))
    if len(statuses) == 1:
        return column == statuses[0]
    return column.in_(statuses)


def filters_to_workflow_runs(instance_id: str | None) -> bool:
    """Whether an instance filter is set, which excludes non-workflow runs."""
    return isinstance(instance_id, str) and bool(instance_id.strip())


def apply_instance_filter(query: Select, instance_id: str | None) -> Select:
    """Narrow a history query to one executing instance.

    Filters on the id rather than the stored name: the name is a snapshot taken
    when the run finished, so two rows can carry different names for the same
    instance after a rename, and different instances can share a name.
    """
    # Tests call this endpoint function directly, where FastAPI has not resolved
    # Query(default=None) into a value, so anything that is not a string is
    # treated as "no filter".
    if not isinstance(instance_id, str):
        return query
    cleaned = instance_id.strip()
    if not cleaned:
        return query
    return query.where(ExecutionHistory.executed_by_instance_id == cleaned)


def run_history_rows(
    user_id: uuid.UUID,
    *,
    search: str | None = None,
    execution_status: str | None = None,
    trigger_source: str | None = None,
    workflow_id: str | None = None,
    instance_id: str | None = None,
    is_admin: bool | None = None,
) -> Subquery:
    """The filtered run list as a subquery; the caller counts, orders and pages it.

    ``is_admin`` works as in ``workflow_access_clause``.
    """
    exec_subq = (
        select(
            ExecutionHistory.id,
            ExecutionHistory.workflow_id,
            Workflow.name.label("workflow_name"),
            literal("workflow").label("run_type"),
            ExecutionHistory.started_at,
            ExecutionHistory.status,
            ExecutionHistory.execution_time_ms,
            ExecutionHistory.trigger_source,
            ExecutionHistory.recovered,
            ExecutionHistory.executed_by_instance_id,
            ExecutionHistory.executed_by_instance_name,
        )
        .join(Workflow, ExecutionHistory.workflow_id == Workflow.id)
        .where(workflow_access_clause(user_id, is_admin=is_admin))
    )
    if workflow_id:
        exec_subq = exec_subq.where(ExecutionHistory.workflow_id == workflow_id)
    if trigger_source:
        exec_subq = exec_subq.where(ExecutionHistory.trigger_source == trigger_source)
    exec_subq = apply_instance_filter(exec_subq, instance_id)
    exec_status_clause = history_status_clause(ExecutionHistory.status, execution_status)
    if exec_status_clause is not None:
        exec_subq = exec_subq.where(exec_status_clause)
    if search:
        pattern = f"%{search}%"
        exec_subq = exec_subq.where(
            or_(
                Workflow.name.ilike(pattern),
                ExecutionHistory.status.ilike(pattern),
                ExecutionHistory.trigger_source.ilike(pattern),
                cast(ExecutionHistory.inputs, String).ilike(pattern),
                cast(ExecutionHistory.outputs, String).ilike(pattern),
                cast(ExecutionHistory.node_results, String).ilike(pattern),
            )
        )

    if workflow_id or filters_to_workflow_runs(instance_id):
        return exec_subq.subquery()

    run_display_name = case(
        (RunHistory.run_type == "dashboard_chat", "Dashboard Chat"),
        (RunHistory.run_type == "workflow_assistant", "Workflow Assistant"),
        else_=RunHistory.run_type,
    )
    run_subq = select(
        RunHistory.id,
        RunHistory.workflow_id,
        run_display_name.label("workflow_name"),
        RunHistory.run_type.label("run_type"),
        RunHistory.started_at,
        RunHistory.status,
        RunHistory.execution_time_ms,
        RunHistory.trigger_source,
        literal(False).label("recovered"),
        # Chat/assistant runs are not workflow executions and have no
        # instance of their own; the union needs matching columns.
        cast(null(), String).label("executed_by_instance_id"),
        cast(null(), String).label("executed_by_instance_name"),
    ).where(RunHistory.user_id == user_id)
    if trigger_source:
        run_subq = run_subq.where(RunHistory.trigger_source == trigger_source)
    run_status_clause = history_status_clause(RunHistory.status, execution_status)
    if run_status_clause is not None:
        run_subq = run_subq.where(run_status_clause)
    if search:
        pattern = f"%{search}%"
        run_subq = run_subq.where(
            or_(
                RunHistory.status.ilike(pattern),
                RunHistory.trigger_source.ilike(pattern),
                RunHistory.run_type.ilike(pattern),
                cast(RunHistory.inputs, String).ilike(pattern),
                cast(RunHistory.outputs, String).ilike(pattern),
            )
        )
    return union_all(exec_subq, run_subq).subquery()
