import asyncio
import logging
import uuid
from datetime import datetime, timezone

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import upsert_workflow_analytics_snapshot
from app.api.workflows import (
    _persist_global_variables_from_execution,
    collect_referenced_workflows,
    get_credentials_context,
)
from app.db.models import ExecutionHistory, PortalSession, Workflow, WorkflowVersion
from app.db.session import async_session_maker
from app.services.distributed_lock import lock_service
from app.services.global_variables_service import get_global_variables_context
from app.services.timezone_utils import get_configured_timezone
from app.services.workflow_executor import _to_json_compatible, execute_workflow

logger = logging.getLogger("cron_scheduler")


class CronScheduler:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_check: dict[str, datetime] = {}
        self._last_cleanup_date: str | None = None
        self._last_portal_session_cleanup_date: str | None = None
        self._last_workflow_version_cleanup_date: str | None = None
        self._last_refresh_token_cleanup_date: str | None = None
        self._last_file_access_token_cleanup_date: str | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Cron scheduler started (worker_id=%s)", lock_service.worker_id)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Cron scheduler stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                if not lock_service.is_leader:
                    await asyncio.sleep(5)
                    continue

                await self._check_and_execute()
                await self._check_scheduled_deletion_cleanup()
                await self._check_portal_session_cleanup()
                await self._check_workflow_version_cleanup()
                await self._check_refresh_token_cleanup()
                await self._check_file_access_token_cleanup()
            except Exception as e:
                logger.exception("Error in cron scheduler loop: %s", e)
            await asyncio.sleep(30)

    async def _check_and_execute(self) -> None:
        async with async_session_maker() as db:
            workflows = await self._get_workflows_with_cron(db)
            tz = get_configured_timezone()
            now = datetime.now(tz)

            for workflow in workflows:
                cron_nodes = self._find_cron_nodes(workflow.nodes)
                for node in cron_nodes:
                    cron_expr = node.get("data", {}).get("cronExpression", "")
                    if not cron_expr:
                        continue

                    node_id = node.get("id", "")
                    node_key = f"{workflow.id}_{node_id}"
                    try:
                        if self._should_trigger(cron_expr, now, node_key):
                            minute_key = now.strftime("%Y%m%d%H%M")
                            can_execute = await lock_service.check_cron_execution(
                                str(workflow.id),
                                node_id,
                                minute_key,
                            )
                            if can_execute:
                                await self._execute_workflow(db, workflow)
                                self._last_check[node_key] = now
                            else:
                                logger.debug(
                                    "Cron execution for %s already handled by another worker",
                                    node_key,
                                )
                    except Exception as e:
                        logger.error(
                            "Error checking cron for workflow %s node %s: %s",
                            workflow.id,
                            node.get("id"),
                            e,
                        )

    async def _get_workflows_with_cron(self, db: AsyncSession) -> list[Workflow]:
        result = await db.execute(select(Workflow))
        all_workflows = result.scalars().all()
        return [w for w in all_workflows if self._has_cron_node(w.nodes)]

    def _has_cron_node(self, nodes: list[dict]) -> bool:
        return any(
            n.get("type") == "cron" and n.get("data", {}).get("active", True) is not False
            for n in nodes
        )

    def _find_cron_nodes(self, nodes: list[dict]) -> list[dict]:
        return [
            n
            for n in nodes
            if n.get("type") == "cron" and n.get("data", {}).get("active", True) is not False
        ]

    def _should_trigger(self, cron_expr: str, now: datetime, node_key: str) -> bool:
        try:
            cron = croniter(cron_expr, now)
            prev_time = cron.get_prev(datetime)
            last_check = self._last_check.get(node_key)

            if last_check is None:
                self._last_check[node_key] = now
                return False

            if prev_time.replace(tzinfo=now.tzinfo) > last_check:
                return True
            return False
        except Exception as e:
            logger.error("Invalid cron expression '%s': %s", cron_expr, e)
            return False

    async def _execute_workflow(self, db: AsyncSession, workflow: Workflow) -> None:
        logger.info("Executing workflow %s via cron trigger", workflow.id)
        try:
            workflow_cache = await collect_referenced_workflows(db, workflow.nodes)
            credentials_context = await get_credentials_context(db, workflow.owner_id)
            global_variables_context = await get_global_variables_context(db, workflow.owner_id)

            result = execute_workflow(
                workflow_id=workflow.id,
                nodes=workflow.nodes,
                edges=workflow.edges,
                inputs={"triggered_by": "cron"},
                workflow_cache=workflow_cache,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=workflow.owner_id,
            )
            if result.allow_downstream_pending:
                result.join_allow_downstream()

            history_entry = ExecutionHistory(
                workflow_id=workflow.id,
                inputs={"triggered_by": "cron"},
                outputs=_to_json_compatible(result.outputs),
                node_results=_to_json_compatible(result.node_results),
                status=result.status,
                execution_time_ms=result.execution_time_ms,
                trigger_source="cron",
            )
            db.add(history_entry)
            await upsert_workflow_analytics_snapshot(
                db,
                workflow_id=workflow.id,
                owner_id=workflow.owner_id,
                workflow_name_snapshot=workflow.name,
                status=result.status,
                execution_time_ms=result.execution_time_ms,
            )

            for sub_exec in result.sub_workflow_executions:
                sub_history = ExecutionHistory(
                    workflow_id=uuid.UUID(sub_exec.workflow_id),
                    inputs=_to_json_compatible(sub_exec.inputs),
                    outputs=_to_json_compatible(sub_exec.outputs),
                    node_results=_to_json_compatible(sub_exec.node_results),
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

            await _persist_global_variables_from_execution(
                db,
                workflow.owner_id,
                workflow.nodes,
                workflow_cache,
                _to_json_compatible(result.node_results),
                result.sub_workflow_executions,
            )

            await db.commit()
            logger.info(
                "Workflow %s executed successfully via cron, status: %s",
                workflow.id,
                result.status,
            )
        except Exception as e:
            logger.exception("Failed to execute workflow %s via cron: %s", workflow.id, e)

    async def _check_scheduled_deletion_cleanup(self) -> None:
        tz = get_configured_timezone()
        now = datetime.now(tz)
        current_date = now.strftime("%Y%m%d")

        if now.hour == 23 and now.minute >= 59:
            if self._last_cleanup_date != current_date:
                can_cleanup = await lock_service.check_cron_execution(
                    "scheduled_deletion_cleanup",
                    "cleanup",
                    current_date,
                )
                if can_cleanup:
                    await self._cleanup_scheduled_workflows()
                    self._last_cleanup_date = current_date
                else:
                    logger.debug("Scheduled deletion cleanup already handled by another worker")

    async def _cleanup_scheduled_workflows(self) -> None:
        async with async_session_maker() as db:
            result = await db.execute(
                select(Workflow).where(Workflow.scheduled_for_deletion.isnot(None))
            )
            scheduled_workflows = result.scalars().all()

            deleted_count = 0
            for workflow in scheduled_workflows:
                if self._should_delete_workflow(workflow):
                    logger.info(
                        "Deleting scheduled workflow %s (%s) - all start nodes deactivated",
                        workflow.id,
                        workflow.name,
                    )
                    await db.delete(workflow)
                    deleted_count += 1
                else:
                    logger.debug(
                        "Keeping scheduled workflow %s (%s) - not all start nodes deactivated",
                        workflow.id,
                        workflow.name,
                    )

            if deleted_count > 0:
                await db.commit()
                logger.info(
                    "Scheduled deletion cleanup completed: %d workflows deleted", deleted_count
                )

    def _should_delete_workflow(self, workflow: Workflow) -> bool:
        nodes = workflow.nodes or []
        edges = workflow.edges or []

        if not nodes:
            return True

        target_node_ids = {edge.get("target") for edge in edges if edge.get("target")}
        start_nodes = [
            node
            for node in nodes
            if node.get("id") not in target_node_ids
            and node.get("type") not in ("sticky", "errorHandler")
        ]

        if not start_nodes:
            return False

        for node in start_nodes:
            node_data = node.get("data", {})
            if node_data.get("active", True) is not False:
                return False

        return True

    async def _check_portal_session_cleanup(self) -> None:
        tz = get_configured_timezone()
        now = datetime.now(tz)
        current_date = now.strftime("%Y%m%d")

        if now.hour == 2 and now.minute >= 0:
            if self._last_portal_session_cleanup_date != current_date:
                can_cleanup = await lock_service.check_cron_execution(
                    "portal_session_cleanup",
                    "cleanup",
                    current_date,
                )
                if can_cleanup:
                    await self._cleanup_expired_portal_sessions()
                    self._last_portal_session_cleanup_date = current_date
                else:
                    logger.debug("Portal session cleanup already handled by another worker")

    async def _cleanup_expired_portal_sessions(self) -> None:
        async with async_session_maker() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(select(PortalSession).where(PortalSession.expires_at < now))
            expired_sessions = result.scalars().all()

            deleted_count = 0
            for session in expired_sessions:
                await db.delete(session)
                deleted_count += 1

            if deleted_count > 0:
                await db.commit()
                logger.info(
                    "Portal session cleanup completed: %d expired sessions deleted", deleted_count
                )

    async def _check_workflow_version_cleanup(self) -> None:
        tz = get_configured_timezone()
        now = datetime.now(tz)
        current_date = now.strftime("%Y%m%d")

        if now.hour == 2 and now.minute >= 0 and now.minute < 30:
            if self._last_workflow_version_cleanup_date != current_date:
                can_cleanup = await lock_service.check_cron_execution(
                    "workflow_version_cleanup",
                    "cleanup",
                    current_date,
                )
                if can_cleanup:
                    await self._cleanup_old_workflow_versions()
                    self._last_workflow_version_cleanup_date = current_date
                else:
                    logger.debug("Workflow version cleanup already handled by another worker")

    async def _cleanup_old_workflow_versions(self) -> None:
        async with async_session_maker() as db:
            from datetime import timedelta

            cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
            result = await db.execute(
                select(WorkflowVersion).where(WorkflowVersion.created_at < cutoff_date)
            )
            old_versions = result.scalars().all()

            deleted_count = 0
            for version in old_versions:
                await db.delete(version)
                deleted_count += 1

            if deleted_count > 0:
                await db.commit()
                logger.info(
                    "Workflow version cleanup completed: %d old versions deleted (older than 7 days)",
                    deleted_count,
                )

    async def _check_refresh_token_cleanup(self) -> None:
        tz = get_configured_timezone()
        now = datetime.now(tz)
        current_date = now.strftime("%Y%m%d")

        if now.hour == 3 and now.minute >= 0 and now.minute < 30:
            if self._last_refresh_token_cleanup_date != current_date:
                can_cleanup = await lock_service.check_cron_execution(
                    "refresh_token_cleanup",
                    "cleanup",
                    current_date,
                )
                if can_cleanup:
                    await self._cleanup_expired_refresh_tokens()
                    self._last_refresh_token_cleanup_date = current_date
                else:
                    logger.debug("Refresh token cleanup already handled by another worker")

    async def _cleanup_expired_refresh_tokens(self) -> None:
        from app.services.auth import cleanup_expired_refresh_tokens

        async with async_session_maker() as db:
            deleted_count = await cleanup_expired_refresh_tokens(db)
            if deleted_count > 0:
                await db.commit()
                logger.info(
                    "Refresh token cleanup completed: %d expired tokens deleted", deleted_count
                )

    async def _check_file_access_token_cleanup(self) -> None:
        tz = get_configured_timezone()
        now = datetime.now(tz)
        current_date = now.strftime("%Y%m%d")

        if now.hour == 3 and now.minute >= 30 and now.minute < 60:
            if self._last_file_access_token_cleanup_date != current_date:
                can_cleanup = await lock_service.check_cron_execution(
                    "file_access_token_cleanup",
                    "cleanup",
                    current_date,
                )
                if can_cleanup:
                    await self._cleanup_expired_file_access_tokens()
                    self._last_file_access_token_cleanup_date = current_date
                else:
                    logger.debug("File access token cleanup already handled by another worker")

    async def _cleanup_expired_file_access_tokens(self) -> None:
        from app.db.models import FileAccessToken

        async with async_session_maker() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(FileAccessToken).where(
                    FileAccessToken.expires_at.isnot(None),
                    FileAccessToken.expires_at < now,
                )
            )
            expired_tokens = result.scalars().all()
            deleted_count = 0
            for token in expired_tokens:
                await db.delete(token)
                deleted_count += 1
            if deleted_count > 0:
                await db.commit()
                logger.info(
                    "File access token cleanup completed: %d expired tokens deleted",
                    deleted_count,
                )


cron_scheduler = CronScheduler()
