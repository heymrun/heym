import logging
import os
import time
from contextlib import asynccontextmanager, suppress

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api import (
    agent_memory,
    ai_assistant,
    analytics,
    auth,
    bigquery_oauth,
    chats,
    config,
    credentials,
    dashboards,
    data_tables,
    discord,
    evals,
    expressions,
    file_intake,
    files,
    folders,
    global_variables,
    google_sheets_oauth,
    hitl,
    linear_oauth,
    llm_pricing,
    logs,
    mcp,
    mcp_servers,
    notion_oauth,
    oauth,
    playwright,
    plugins,
    portal,
    schedules,
    skill_builder,
    slack,
    teams,
    telegram,
    templates,
    traces,
    vector_stores,
    voice,
    workflows,
)
from app.api.deps import get_client_ip
from app.config import settings
from app.db.session import async_session_maker
from app.http_identity import HEYM_SERVER_AGENT
from app.middleware.request_body_limit import RequestBodySizeLimitMiddleware
from app.models.schemas import AppVersionResponse
from app.observability.tracing import setup_tracing, shutdown_tracing
from app.services.clickhouse_pool import close_all_clients as close_clickhouse_clients
from app.services.clickhouse_pool import warm_up_pools as warm_up_clickhouse_pools
from app.services.cron_scheduler import cron_scheduler
from app.services.distributed_lock import lock_service
from app.services.execution_cancellation import (
    active_execution_registry,
    mark_own_executions_orphaned,
)
from app.services.execution_recovery import execution_recovery_service
from app.services.grist_pool import close_all_clients as close_grist_clients
from app.services.grist_pool import warm_up_pools as warm_up_grist_pools
from app.services.hitl_service import build_public_base_url, build_review_url
from app.services.imap_trigger_service import imap_trigger_manager
from app.services.notion_service import NotionService
from app.services.qdrant_pool import close_all_clients as close_qdrant_clients
from app.services.qdrant_pool import warm_up_pools as warm_up_qdrant_pools
from app.services.rabbitmq_consumer import rabbitmq_consumer_manager
from app.services.rabbitmq_pool import RabbitMQPool
from app.services.redis_pool import close_all_pools as close_redis_pools
from app.services.redis_pool import warm_up_pools as warm_up_redis_pools
from app.services.version_check import get_version_status
from app.services.websocket_trigger_service import websocket_trigger_manager
from app.services.workflow_executor import close_http_client

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("winston")


def _ensure_playwright_browsers() -> None:
    """Install Playwright Chromium if not present (local dev). Skipped when PLAYWRIGHT_INSTALL_AT_STARTUP=false (Docker)."""
    if os.environ.get("PLAYWRIGHT_INSTALL_AT_STARTUP", "true").lower() == "false":
        return
    try:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning("Playwright install failed: %s", result.stderr or result.stdout)
        else:
            logger.info("Playwright Chromium ready")
    except Exception as e:
        logger.warning("Playwright install skipped: %s", e)


async def _reinstall_plugin_dependencies() -> None:
    """Reinstall declared pip dependencies for installed plugins on startup.

    Container filesystems are ephemeral, so deps installed when a plugin was added
    are lost on recreate; this restores them. No-op when plugins are disabled.
    Failures never block startup.
    """
    if not settings.plugins_enabled:
        return
    try:
        import asyncio

        from sqlalchemy import select

        from app.db.models import Plugin
        from app.models.plugin_schemas import PluginManifest
        from app.services import plugin_store

        async with async_session_maker() as _plugin_db:
            rows = (
                (await _plugin_db.execute(select(Plugin).where(Plugin.enabled.is_(True))))
                .scalars()
                .all()
            )
        deps: set[str] = set()
        for plugin in rows:
            try:
                deps.update(PluginManifest.model_validate(plugin.manifest).dependencies)
            except Exception:
                continue
        if deps:
            logger.info("Reinstalling %d plugin dependency spec(s) on startup", len(deps))
            await asyncio.to_thread(plugin_store.ensure_dependencies_installed, sorted(deps))
    except Exception as exc:
        logger.warning("Plugin dependency reinstall skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Heym AI Workflow Platform v%s", settings.resolved_version)
    await lock_service.start()

    async with async_session_maker() as _startup_db:
        await _startup_db.execute(
            sa.text("UPDATE dashboard_conversations SET is_running = false WHERE is_running = true")
        )
        await _startup_db.commit()

    await _reinstall_plugin_dependencies()

    _ensure_playwright_browsers()

    redis_count = warm_up_redis_pools()
    if redis_count > 0:
        logger.info("Redis pools warmed up: %d", redis_count)

    grist_count = warm_up_grist_pools()
    if grist_count > 0:
        logger.info("Grist pools warmed up: %d", grist_count)

    qdrant_count = warm_up_qdrant_pools()
    if qdrant_count > 0:
        logger.info("Qdrant pools warmed up: %d", qdrant_count)

    clickhouse_count = warm_up_clickhouse_pools()
    if clickhouse_count > 0:
        logger.info("ClickHouse pools warmed up: %d", clickhouse_count)

    await active_execution_registry.start()
    await execution_recovery_service.start()
    await cron_scheduler.start()
    await imap_trigger_manager.start()
    await rabbitmq_consumer_manager.start()
    await websocket_trigger_manager.start()
    yield
    shutdown_tracing()
    await websocket_trigger_manager.stop()
    await rabbitmq_consumer_manager.stop()
    await imap_trigger_manager.stop()
    await RabbitMQPool.close_all()
    await cron_scheduler.stop()
    await execution_recovery_service.stop()
    await active_execution_registry.stop()
    with suppress(Exception):
        await mark_own_executions_orphaned()
    await lock_service.stop()
    close_redis_pools()
    close_grist_clients()
    close_qdrant_clients()
    close_clickhouse_clients()
    NotionService.close_shared_client()
    close_http_client()


class WinstonLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        client_ip = get_client_ip(request)
        logger.info("request %s %s %s", request.method, request.url.path, client_ip)
        try:
            response = await call_next(request)
        except Exception as exc:
            duration = (time.time() - start_time) * 1000
            logger.exception(
                "error %s %s %sms %s %s",
                request.method,
                request.url.path,
                f"{duration:.2f}",
                client_ip,
                str(exc),
            )
            raise
        duration = (time.time() - start_time) * 1000
        logger.info(
            "response %s %s %s %sms %s",
            request.method,
            request.url.path,
            response.status_code,
            f"{duration:.2f}",
            client_ip,
        )
        return response


class HeymIdentityMiddleware(BaseHTTPMiddleware):
    """Expose product identity on every HTTP response (API, portal, MCP, health)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Heym-Agent"] = HEYM_SERVER_AGENT
        response.headers["Server"] = HEYM_SERVER_AGENT
        return response


app = FastAPI(
    title="Heym API",
    description="AI Workflow Automation Platform",
    version=settings.resolved_version,
    lifespan=lifespan,
)

# Initialize OpenTelemetry tracing (no-op unless HEYM_OTEL_ENABLED=true). Must run
# against the app instance so FastAPI inbound-context instrumentation can attach.
setup_tracing(app)

# Register before CORS so oversized-request 413 responses still receive CORS headers.
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    max_body_size=settings.request_body_max_size_mb * 1024 * 1024,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(WinstonLoggingMiddleware)
app.add_middleware(HeymIdentityMiddleware)

app.include_router(oauth.router, tags=["OAuth"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["Workflows"])
app.include_router(agent_memory.router, prefix="/api/workflows", tags=["Agent Memory"])
app.include_router(playwright.router, prefix="/api/playwright", tags=["Playwright"])
app.include_router(folders.router, prefix="/api", tags=["Folders"])
app.include_router(credentials.router, prefix="/api/credentials", tags=["Credentials"])
app.include_router(
    google_sheets_oauth.router,
    prefix="/api/credentials/google-sheets/oauth",
    tags=["Google Sheets OAuth"],
)
app.include_router(
    bigquery_oauth.router,
    prefix="/api/credentials/bigquery/oauth",
    tags=["BigQuery OAuth"],
)
app.include_router(
    notion_oauth.router,
    prefix="/api/credentials/notion/oauth",
    tags=["Notion OAuth"],
)
app.include_router(
    linear_oauth.router,
    prefix="/api/credentials/linear/oauth",
    tags=["Linear OAuth"],
)
app.include_router(
    global_variables.router, prefix="/api/global-variables", tags=["Global Variables"]
)
app.include_router(vector_stores.router, prefix="/api/vector-stores", tags=["Vector Stores"])
app.include_router(ai_assistant.router, prefix="/api/ai", tags=["AI Assistant"])
app.include_router(skill_builder.router, prefix="/api/ai", tags=["Skill Builder"])
app.include_router(config.router, prefix="/api/config", tags=["Config"])
app.include_router(mcp.router, prefix="/api/mcp", tags=["MCP"])
app.include_router(mcp_servers.router, prefix="/api/mcp/servers", tags=["MCP Servers"])
app.include_router(traces.router, prefix="/api/traces", tags=["Traces"])
app.include_router(llm_pricing.router, prefix="/api/llm-pricing", tags=["LLM Pricing"])
app.include_router(portal.router, prefix="/api/portal", tags=["Portal"])
app.include_router(hitl.router, prefix="/api/hitl", tags=["HITL"])
app.include_router(files.router, prefix="/api/files", tags=["Files"])
app.include_router(file_intake.router, prefix="/api", tags=["File Intake"])
app.include_router(portal.router, prefix="/api/workflows", tags=["Portal Settings"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(dashboards.router, prefix="/api/dashboards", tags=["Dashboards"])
app.include_router(logs.router, prefix="/api/logs", tags=["Logs"])
app.include_router(plugins.router, prefix="/api/plugins", tags=["Plugins"])
app.include_router(evals.router, prefix="/api/evals", tags=["Evals"])
app.include_router(chats.router, prefix="/api/chats", tags=["Chats"])
app.include_router(voice.router, prefix="/api/voice", tags=["Voice"])
app.include_router(expressions.router, prefix="/api/expressions", tags=["Expressions"])
app.include_router(templates.router, prefix="/api/templates", tags=["Templates"])
app.include_router(teams.router, prefix="/api/teams", tags=["Teams"])
app.include_router(data_tables.router, prefix="/api/data-tables", tags=["Data Tables"])
app.include_router(slack.router, prefix="/api/slack", tags=["Slack"])
app.include_router(discord.router, prefix="/api/discord", tags=["Discord"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["Telegram"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["Schedules"])


@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "heym-api", "version": settings.resolved_version}


@app.get("/api/version", response_model=AppVersionResponse)
async def version_info(response: Response) -> AppVersionResponse:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    version_status = await get_version_status(settings.resolved_version)
    return AppVersionResponse(
        version=version_status.current_version,
        latest_version=version_status.latest_version,
        update_available=version_status.update_available,
        release_url=version_status.release_url,
        compare_url=version_status.compare_url,
        compare_label=version_status.compare_label,
        source=version_status.source,
        checked_at=version_status.checked_at,
        error=version_status.error,
    )


@app.get("/review/{token}", include_in_schema=False)
async def redirect_hitl_review(token: str, request: Request) -> RedirectResponse:
    public_base_url = build_public_base_url(request)
    request_base_url = str(request.base_url).rstrip("/")
    target_base_url = public_base_url
    if target_base_url == request_base_url and settings.frontend_url:
        configured_frontend_url = settings.frontend_url.rstrip("/")
        if configured_frontend_url != request_base_url:
            target_base_url = configured_frontend_url
    if target_base_url == request_base_url:
        raise HTTPException(status_code=404, detail="Review page is served by the frontend.")
    return RedirectResponse(url=build_review_url(target_base_url, token), status_code=307)
