import logging
import os
import time
from contextlib import asynccontextmanager

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
    config,
    credentials,
    data_tables,
    evals,
    expressions,
    files,
    folders,
    global_variables,
    google_sheets_oauth,
    hitl,
    logs,
    mcp,
    oauth,
    playwright,
    portal,
    schedules,
    skill_builder,
    slack,
    teams,
    telegram,
    templates,
    traces,
    vector_stores,
    workflows,
)
from app.api.deps import get_client_ip
from app.config import settings
from app.http_identity import HEYM_SERVER_AGENT
from app.services.cron_scheduler import cron_scheduler
from app.services.distributed_lock import lock_service
from app.services.grist_pool import close_all_clients as close_grist_clients
from app.services.grist_pool import warm_up_pools as warm_up_grist_pools
from app.services.hitl_service import build_public_base_url, build_review_url
from app.services.imap_trigger_service import imap_trigger_manager
from app.services.qdrant_pool import close_all_clients as close_qdrant_clients
from app.services.qdrant_pool import warm_up_pools as warm_up_qdrant_pools
from app.services.rabbitmq_consumer import rabbitmq_consumer_manager
from app.services.rabbitmq_pool import RabbitMQPool
from app.services.redis_pool import close_all_pools as close_redis_pools
from app.services.redis_pool import warm_up_pools as warm_up_redis_pools
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Heym AI Workflow Platform v%s", settings.resolved_version)
    await lock_service.start()

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

    await cron_scheduler.start()
    await imap_trigger_manager.start()
    await rabbitmq_consumer_manager.start()
    await websocket_trigger_manager.start()
    yield
    await websocket_trigger_manager.stop()
    await rabbitmq_consumer_manager.stop()
    await imap_trigger_manager.stop()
    await RabbitMQPool.close_all()
    await cron_scheduler.stop()
    await lock_service.stop()
    close_redis_pools()
    close_grist_clients()
    close_qdrant_clients()
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
    global_variables.router, prefix="/api/global-variables", tags=["Global Variables"]
)
app.include_router(vector_stores.router, prefix="/api/vector-stores", tags=["Vector Stores"])
app.include_router(ai_assistant.router, prefix="/api/ai", tags=["AI Assistant"])
app.include_router(skill_builder.router, prefix="/api/ai", tags=["Skill Builder"])
app.include_router(config.router, prefix="/api/config", tags=["Config"])
app.include_router(mcp.router, prefix="/api/mcp", tags=["MCP"])
app.include_router(traces.router, prefix="/api/traces", tags=["Traces"])
app.include_router(portal.router, prefix="/api/portal", tags=["Portal"])
app.include_router(hitl.router, prefix="/api/hitl", tags=["HITL"])
app.include_router(files.router, prefix="/api/files", tags=["Files"])
app.include_router(portal.router, prefix="/api/workflows", tags=["Portal Settings"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(logs.router, prefix="/api/logs", tags=["Logs"])
app.include_router(evals.router, prefix="/api/evals", tags=["Evals"])
app.include_router(expressions.router, prefix="/api/expressions", tags=["Expressions"])
app.include_router(templates.router, prefix="/api/templates", tags=["Templates"])
app.include_router(teams.router, prefix="/api/teams", tags=["Teams"])
app.include_router(data_tables.router, prefix="/api/data-tables", tags=["Data Tables"])
app.include_router(slack.router, prefix="/api/slack", tags=["Slack"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["Telegram"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["Schedules"])


@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "heym-api", "version": settings.resolved_version}


@app.get("/api/version")
async def version_info() -> dict:
    return {"version": settings.resolved_version}


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
