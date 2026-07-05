# Environment Variables

This is the full reference for configuring a self-hosted Heym instance. Every
variable is optional unless marked **required**. Values can be set in a `.env`
file (copy `.env.example`) or passed directly to the process / container.

`./run.sh` and `./deploy.sh` auto-generate `SECRET_KEY` and `ENCRYPTION_KEY`
when they are empty, so a plain `./run.sh` works with no manual setup.

Defaults below are the values used when the variable is unset. Note that
`.env.example` ships a few tighter starter values (for example shorter JWT
lifetimes) that override these code defaults when you copy it.

## Required

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | JWT signing key. Must be cryptographically random and at least 32 characters. Startup fails if missing or a known placeholder. | — (required) |
| `ENCRYPTION_KEY` | Key used to encrypt stored credentials at rest. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. Startup fails if missing or the known placeholder. | — (required) |

## Database

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Full async SQLAlchemy connection string. Overrides the `POSTGRES_*` values when set. | auto-built from `POSTGRES_*` |
| `POSTGRES_HOST` | Database host (used when `DATABASE_URL` is empty). | `localhost` |
| `POSTGRES_PORT` | Database port. | `6543` |
| `POSTGRES_USER` | Database user. | `postgres` |
| `POSTGRES_PASSWORD` | Database password. | `postgres` |
| `POSTGRES_DB` | Database name. | `heym` |
| `AUTO_REWRITE_LOCAL_DATABASE_HOST` | Single-image runtime helper: rewrite a `localhost` DB host to the in-container address. | `true` |

## Authentication & sessions

| Variable | Description | Default |
|----------|-------------|---------|
| `JWT_ALGORITHM` | JWT signing algorithm. | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime in minutes. | `1440` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh-token lifetime in days. | `30` |
| `ALLOW_REGISTER` | Allow new user self-registration. Set `false` to lock down production. | `true` |
| `TRUST_PROXY_HEADERS` | Trust `X-Forwarded-*` headers (enable only behind a trusted proxy). | `false` |

## OAuth (MCP / API clients)

| Variable | Description | Default |
|----------|-------------|---------|
| `OAUTH_ACCESS_TOKEN_EXPIRE_SECONDS` | OAuth access-token lifetime. | `3600` |
| `OAUTH_REFRESH_TOKEN_EXPIRE_DAYS` | OAuth refresh-token lifetime. | `30` |
| `OAUTH_AUTH_CODE_EXPIRE_MINUTES` | OAuth authorization-code lifetime. | `10` |
| `OAUTH_ISSUER` | Public OAuth issuer URL (e.g. `https://api.example.com`). Empty uses the request base URL. | — |

## Networking & CORS

| Variable | Description | Default |
|----------|-------------|---------|
| `CORS_ORIGINS` | Comma-separated allowed origins. | `http://localhost:4017` |
| `FRONTEND_URL` | Public frontend URL used in generated links. | `http://localhost:4017` |
| `BACKEND_PORT` | Backend server port. | `10105` |
| `FRONTEND_PORT` | Frontend server port. | `4017` |
| `BACKEND_BIND_HOST` | Address the backend binds to (single-image runtime). | `127.0.0.1` |
| `BACKEND_PROXY_HOST` | Host the frontend proxies API calls to (single-image runtime). | `127.0.0.1` |
| `TIMEZONE` | IANA timezone for scheduling/display. Empty falls back to `TZ`, then `UTC`. | — |

## Files & storage

| Variable | Description | Default |
|----------|-------------|---------|
| `FILE_STORAGE_DIR` | Directory for Drive uploads and generated files. | `./data/files` |
| `FILE_MAX_SIZE_MB` | Maximum single-file size in MB. | `99` |
| `REQUEST_BODY_MAX_SIZE_MB` | Maximum HTTP request body size; kept one MB above `FILE_MAX_SIZE_MB` for multipart overhead. | `100` |
| `DOCS_DIR` | Override path to docs content. Empty uses `frontend/src/docs/content`. | — |

## MCP (Model Context Protocol)

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_PROTOCOL_MAX_CONCURRENCY` | Max concurrent MCP protocol operations. | `20` |
| `MCP_SSE_MAX_SESSIONS` | Max concurrent MCP SSE sessions. | `100` |
| `HEYM_MCP_ALLOW_PRIVATE_URLS` | Disable the SSRF egress guard for `sse`/`streamable_http` MCP servers. When `false` (default) MCP HTTP URLs must resolve to a public address; loopback, private, link-local, multicast, and cloud-metadata targets are refused, and the resolved IP is pinned at dial time to defeat DNS rebinding. Set `true` only on trusted self-hosted instances that intentionally connect to internal MCP servers. **Keep `false` on hosted/multi-tenant deployments.** | `false` |

> While the guard is on, MCP HTTP/SSE tool fetches connect directly (they do not honor `HTTP_PROXY`/`HTTPS_PROXY`) so the pinned target IP is authoritative, matching the Drive download guard.

## Agent Python tool sandbox

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_PYTHON_TOOL_SANDBOX` | How user-defined Agent Python tools run: `auto` (Docker sandbox, fail-closed), `docker` (never falls back), or `subprocess` (no security boundary; trusted/local only). | `auto` |
| `HEYM_PYTHON_TOOL_IMAGE` | Image used for the Docker sandbox. Empty auto-detects the running backend image. | — |

## Docker log access

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKER_LOGS_ENABLED` | Expose container log access in the UI. Grants broad host visibility. | `false` |
| `DOCKER_LOGS_ALLOWED_EMAILS` | Comma-separated emails allowed to read Docker logs. Create the admin account before enabling. | — |

## Plugins (custom nodes)

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_PLUGINS_ENABLED` | Enable installing custom nodes from zip packages. Install/uninstall runs server-side code, so it is operator-restricted. | `false` |
| `HEYM_PLUGIN_ADMIN_EMAILS` | Comma-separated operator emails allowed to install/uninstall plugins. | — |
| `HEYM_PLUGINS_DIR` | Directory where installed plugins are stored. | `data/plugins` |

## Codex node

The [Codex node](frontend/src/docs/content/nodes/codex-node.md) runs the OpenAI Codex CLI in an isolated workspace. It needs the `codex` CLI and `git` on PATH. Local `./run.sh` uses the native `codex` CLI. Docker deployments use the bundled `heym-codex-docker` wrapper, which starts a sibling container from the same Heym image so Codex's bubblewrap sandbox can create Linux namespaces outside the backend container.

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_CODEX_CLI_COMMAND` | Path/name of the Codex CLI binary. | `codex` |
| `HEYM_CODEX_WORKSPACE_DIR` | Directory for cloned repo workspaces (its `<workspace>.codex-home` sibling holds the auth bundle, outside the repo). | `./data/codex-workspaces` |
| `HEYM_CODEX_NETWORK_ACCESS` | Allow outbound network access for commands inside Codex's `workspace-write` sandbox. Docker deploys set this to `true` so Codex can download files/dependencies while still writing only inside the workspace. | `false` |
| `HEYM_CODEX_DOCKER_IMAGE` | Image used by `heym-codex-docker`. Compose defaults to the locally built backend image (`heym-backend:local`). The release image defaults to the same single GHCR image (`ghcr.io/heymrun/heym:<version>`). | auto |
| `HEYM_CODEX_DOCKER_WORKSPACE_VOLUME` | Docker volume mounted into each Codex runner at `HEYM_CODEX_WORKSPACE_DIR`. Docker Compose uses `heym-codex-workspaces`. | — |
| `HEYM_CODEX_HOST_WORKSPACE_DIR` | Absolute host path for `HEYM_CODEX_WORKSPACE_DIR` when using bind mounts instead of a Docker volume. | — |
| `HEYM_CODEX_DOCKER_NETWORK` | Docker network mode for Codex runner containers. | `bridge` |
| `HEYM_CODEX_DOCKER_CPUS` | CPU limit passed to Codex runner containers. | `2` |
| `HEYM_CODEX_DOCKER_MEMORY` | Memory limit passed to Codex runner containers. | `2g` |
| `HEYM_CODEX_DOCKER_PIDS` | PID limit passed to Codex runner containers. | `1024` |
| `HEYM_CODEX_GIT_AUTHOR_NAME` | Author name for commits Codex creates. | `Heym Codex` |
| `HEYM_CODEX_GIT_AUTHOR_EMAIL` | Author email for Codex commits. The GitHub avatar shown next to it is derived from this email (matching GitHub account, else Gravatar). | `support@heym.run` |
| `HEYM_CODEX_OAUTH_CLIENT_ID` | OpenAI OAuth client id for "Sign in with ChatGPT". Defaults to the public Codex CLI client. | `app_EMoamEEZ73f0CkXaXp7hrann` |
| `HEYM_CODEX_OAUTH_ISSUER` | OpenAI OAuth issuer base URL. | `https://auth.openai.com` |
| `HEYM_CODEX_OAUTH_REDIRECT_URI` | OAuth redirect URI (fixed by OpenAI's Codex client; used for the paste-back flow). | `http://localhost:1455/auth/callback` |

> `HEYM_CODEX_CLI_VERSION` is a **Docker build arg** (not a runtime env var) that pins the `@openai/codex` npm version installed into the image. Default `latest`.

## OpenTelemetry tracing

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_OTEL_ENABLED` | Emit a root span per workflow run and a child span per node over OTLP/HTTP. | `false` |
| `HEYM_OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP base endpoint, e.g. `http://collector:4318` (spans posted to `/v1/traces`). | — |
| `HEYM_OTEL_EXPORTER_OTLP_HEADERS` | Comma-separated `key=value` exporter headers for auth. | — |
| `HEYM_OTEL_SERVICE_NAME` | `service.name` resource attribute. | `heym` |
| `HEYM_OTEL_TRACES_SAMPLER_RATIO` | Parent-based head sampling ratio (`0.0`–`1.0`). | `1.0` |
| `HEYM_OTEL_CAPTURE_NODE_IO` | Attach truncated node input/output to node spans (may contain user data). | `false` |

## Miscellaneous

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_LLM_PRICING_SYNC_ENABLED` | Periodically sync model pricing data. | `true` |
| `APP_VERSION` | Override the reported app version. Empty reads the `VERSION` file. | — |

## Frontend build-time

These are read at build time by Vite and baked into the frontend bundle.

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_URL` | Base URL the frontend calls for the API. | same-origin |
| `VITE_APP_VERSION` | Version string shown in the UI. | from build |
| `VITE_HEYM_WEB_URL` | Marketing/site URL used for external links. | — |
