# Logs Tab

The **Logs** tab shows Docker container logs for the Heym stack. Use it for debugging, monitoring, and troubleshooting. For workflow execution logs (node results, outputs), use the Debug panel in the workflow editor—see [Canvas Features](../reference/canvas-features.md#execution-logs).

Docker-backed logs are disabled by default in self-hosted deployments. To enable them, set `DOCKER_LOGS_ENABLED=true`, set `DOCKER_LOGS_ALLOWED_EMAILS` to a comma-separated list of trusted user emails that are allowed to access Docker logs, and make sure `/var/run/docker.sock` is mounted into the backend container. The default Docker Compose service and direct `docker run` example include that mount for Docker-based MCP stdio tools; only keep it when you accept the Docker socket trust boundary.

If registration is open, create the trusted admin account before enabling Docker logs or keep `ALLOW_REGISTER=false`; otherwise an unverified self-registration could claim an allow-listed email.

<video src="/features/showcase/logs.mp4" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/logs.mp4">▶ Watch Logs demo</a></p>

## Container Selection

- **All Containers** – Combined logs from backend, frontend, and PostgreSQL
- **Backend** – `heym-backend` container
- **Frontend** – `heym-frontend` container
- **PostgreSQL** – `heym-postgres` container

## Log Level Filter

- **All** – Show all log levels
- **INFO** – INFO and above
- **WARNING** – Warnings and errors
- **ERROR** – Errors only
- **DEBUG** – Debug and above

## Search

- Filter logs by text search
- Matches are highlighted in the log output

## Features

- **Auto scroll** – Scroll to bottom as new logs arrive
- **Stream** – Stream logs in real time (when supported)
- **Copy** – Copy logs to clipboard
- **Download** – Download logs as a file

## Use Cases

- Debug workflow execution failures
- Inspect API request/response logs
- Monitor database queries
- Check startup and health messages

## Related

- [Incident Playbook (L0)](../reference/incident-playbook.md) - Route runtime symptoms to the right incident procedure
- [Operations Runbook (L1)](../reference/operations-runbook.md) - Diagnose database, service, cluster, and sandbox failures
- [Canvas Features](../reference/canvas-features.md) – Execution logs in the workflow Debug panel
- [Traces Tab](./traces-tab.md) – LLM trace inspection
- [Analytics Tab](./analytics-tab.md) – Execution metrics
- [Workflows Tab](./workflows-tab.md) – Workflow management
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
