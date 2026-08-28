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
| `ALLOW_REGISTER` | Allow new user self-registration. Set `false` to lock down production, but only after your admin account exists: registration is refused for everyone when this is off and there is no first-user bootstrap, so an empty database plus `false` leaves no way to create an account. | `true` |
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
| `HEYM_HTTP_ALLOW_PRIVATE_URLS` | Disable the SSRF egress guard on the **HTTP, WebSocket Send, and WebSocket Trigger nodes**. When `false` (default), target hosts must resolve only to public addresses; loopback, private, link-local, multicast, and cloud-metadata (`169.254.169.254`) targets are refused, and resolved IPs are pinned at dial time to defeat DNS rebinding. Guarded connections dial directly instead of honoring environment proxies so the pinned target stays authoritative. Guarded WebSocket connections also refuse redirects. The HTTP node still requires `http`/`https`, and WebSocket nodes still require `ws`/`wss`, when the opt-out is enabled. Set `true` only on trusted self-hosted instances that intentionally call internal HTTP or WebSocket services; this also restores the WebSocket client's normal proxy behavior. **Keep `false` on hosted/multi-tenant deployments.** | `false` |

## Files & storage

| Variable | Description | Default |
|----------|-------------|---------|
| `FILE_STORAGE_DIR` | Directory for Drive uploads and generated files. Relative values resolve against the backend's working directory, which is `/app` under Compose but `/app/backend` in the single-image release. Set it to an absolute `/app/data/files` whenever you bind-mount `/app/data/files` into `ghcr.io/heymrun/heym`, or the mount receives nothing. | `./data/files` |
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

## Playwright custom code sandbox

The Playwright node's **Run Code** mode (`playwrightCode`) is off by default. When enabled it runs in a hardened throwaway sibling container (Compose / GHCR) or, for native `./run.sh`, falls back to `subprocess`. Step-based Playwright nodes are unaffected.

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_PLAYWRIGHT_CUSTOM_CODE_ENABLED` | Allow executing custom `playwrightCode` / Run Code mode. | `false` |
| `HEYM_PLAYWRIGHT_SANDBOX` | `auto`/`docker` (sibling container, fail-closed) or `subprocess` (in-process; trusted/local only). `./run.sh` sets `subprocess` when no image is configured. | `auto` |
| `HEYM_PLAYWRIGHT_SANDBOX_IMAGE` | Sibling runner image. Compose defaults to `HEYM_BACKEND_IMAGE`; GHCR release image defaults to `ghcr.io/heymrun/heym:<version>`. Empty falls back to `HEYM_CODEX_DOCKER_IMAGE`, then container inspect. | — |
| `HEYM_PLAYWRIGHT_SANDBOX_PYTHON` | Interpreter inside the sibling image. Empty auto-detects `/app/backend/.venv/bin/python` (GHCR) or `/app/.venv/bin/python` (Compose). | auto |

## Agent Python tool sandbox

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_PYTHON_TOOL_SANDBOX` | How user-defined Agent Python **tools** and **skills** run: `auto` (Docker sandbox, fail-closed), `docker` (never falls back), or `subprocess` (no security boundary; trusted/local only). Governs both paths. MCP `stdio` isolation is **not** affected by this and has its own `HEYM_MCP_STDIO_SANDBOX`. | `auto` |
| `HEYM_PYTHON_TOOL_IMAGE` | Image used for the Python tool Docker sandbox (also the skill sandbox fallback when `HEYM_SKILL_IMAGE` is empty). Empty auto-detects the running backend image. | — |

## Agent skill sandbox

Untrusted Agent Python **skills** run in a hardened, throwaway sibling container (non-root, `cap-drop ALL`, `no-new-privileges`, read-only root fs, resource limits, **no Docker socket**) selected by `HEYM_PYTHON_TOOL_SANDBOX` above. Unlike Python tools, skills keep network egress and a per-run writable workspace, shared with the sibling through the same volume the Codex runner uses. Requires Docker Engine 25.0+ (per-run `volume-subpath` mounts); otherwise `auto` fails closed.

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_SKILL_IMAGE` | Image used for the skill Docker sandbox. Empty falls back to `HEYM_PYTHON_TOOL_IMAGE`, then auto-detects the running backend image. | — |
| `HEYM_SKILL_NETWORK` | Docker network mode for skill containers. Egress is intentionally allowed (skills call APIs / install deps via `uv`). | `bridge` |
| `HEYM_SKILL_MEMORY` | Memory limit (and swap cap) for skill containers. | `512m` |
| `HEYM_SKILL_CPUS` | CPU limit for skill containers. | `1` |
| `HEYM_SKILL_PIDS` | PID limit for skill containers. | `256` |
| `HEYM_SKILL_USER` | Non-root `uid:gid` the skill runs as inside the container. | `65534:65534` |
| `HEYM_SKILL_WORKSPACE_MOUNT` | Mount point of the shared workspace volume inside the backend. Falls back to `HEYM_CODEX_WORKSPACE_DIR`. | `/app/data/codex-workspaces` |
| `HEYM_SKILL_WORKSPACE_DIR` | Directory (under the mount) where per-run skill workspaces are created. | `<mount>/_skill-workspaces` |
| `HEYM_SKILL_DOCKER_WORKSPACE_VOLUME` | Docker volume shared with each skill runner. Falls back to `HEYM_CODEX_DOCKER_WORKSPACE_VOLUME` (`heym-codex-workspaces` in Compose), else the backend's own mount is inspected. | — |
| `HEYM_SKILL_HOST_WORKSPACE_DIR` | Absolute host path for the workspace mount when using a bind mount instead of a Docker volume. | — |

## Code node sandbox

**The Code node adds no variables of its own, and deliberately has no `subprocess` escape hatch.** It runs arbitrary user Python with arbitrary dependencies, so it always requires a reachable Docker daemon and fails closed without one — `HEYM_PYTHON_TOOL_SANDBOX` does not apply to it. Its limits (512m memory, 1 CPU, 256 PIDs, 120s install timeout, 60s execution timeout) are constants in `app/services/code_python_executor.py`, not configuration.

It reuses existing variables only: `HEYM_PYTHON_TOOL_IMAGE` then `HEYM_CODEX_DOCKER_IMAGE` for image resolution (falling back to inspecting the backend's own image), and `HEYM_CODEX_WORKSPACE_DIR` / `HEYM_CODEX_DOCKER_WORKSPACE_VOLUME` for the per-run dependency workspace when the backend is containerised. A native `run.sh` backend needs neither variable: it bind-mounts a local temporary directory instead. Code nodes with an empty `requirements.txt` mount nothing at all, since the install phase is skipped.

## MCP stdio sandbox

The MCP `stdio` transport starts a server process from a command supplied in the node configuration (Agent MCP connections, the MCP Call node, and the editor's "Fetch tools" preview). That process runs in a hardened, throwaway sibling container rather than on the backend host: non-root, `cap-drop ALL`, `no-new-privileges`, read-only root fs, resource limits, and **no Docker socket**. Network egress is allowed, because `npx` / `uvx` must fetch their package and MCP servers exist to call APIs.

`HEYM_MCP_STDIO_SANDBOX` is deliberately separate from `HEYM_PYTHON_TOOL_SANDBOX`: an operator who selects `subprocess` there for Python tool compatibility (as `run.sh` does automatically for native dev) must not silently lose MCP stdio isolation as a side effect. Unknown values fall back to `auto`, never to host execution.

A `docker run [flags] IMAGE [args]` command keeps working: Heym starts `IMAGE` itself with the hardening applied, carrying over `-e`, `-w` and `--entrypoint`. Flags that would dissolve the boundary (`--privileged`, `--cap-add`, `--device`, `--security-opt`, `--network host`, `--pid/--ipc/--uts host`, `--env-file`, `--volumes-from`) are refused with an explanatory error.

**Caller-supplied mounts (`-v`, `--volume`, `--mount`, `--volumes-from`) are refused outright.** Validating a mount source is not a winnable game: `//var/run/docker.sock` survives `os.path.normpath` because POSIX preserves exactly two leading slashes, and relative paths, symlinks and parent directories each defeat a denylist differently.

**No application storage is mounted by default either.** The sandbox sees no Heym files unless you name a volume or directory explicitly, and that mount is read-only unless you also opt into writes. The skill/Codex/OpenCode workspace volumes are never auto-mounted: they hold every tenant's workspaces, so exposing one to a single caller's MCP process would be a cross-tenant read. If a file-oriented MCP server (for example `@modelcontextprotocol/server-filesystem`) needs data, point `HEYM_MCP_STDIO_FILES_VOLUME` at a volume you scope yourself, optionally narrowing it with `HEYM_MCP_STDIO_FILES_SUBPATH`.

Inside the container the root filesystem is read-only and `/tmp` is a throwaway tmpfs, so the sandbox sets `HOME` and the npm/uv cache directories to paths under `/tmp` and mounts that tmpfs with `exec`. Without those, `npx` and `uvx` servers cannot run at all: the sandbox user's passwd home is `/nonexistent`, and Docker applies `noexec` to every `--tmpfs` that does not name `exec` explicitly. Values you set on the connection are applied after these defaults, so you can override them.

The working directory is that same tmpfs, not the runner image's `WORKDIR`: `/app` in the backend image is the Heym backend project itself, so a `uv run …` server would try to sync it and fail on the read-only root filesystem. A `docker run IMAGE` command keeps its own image's `WORKDIR` unless it passes `-w`.

These variables are wired through `docker-compose.yml`, so setting them in `.env` works for `./deploy.sh`.

Only the env vars set on the connection reach the server. The backend's own environment (`SECRET_KEY`, `ENCRYPTION_KEY`, `DATABASE_URL`, provider API keys) is never forwarded; the MCP SDK supplies a safe default `PATH`/`HOME`/`SHELL`/`TERM`/`USER`/`LOGNAME` set on top.

> **Operator-only escape hatches.** `HEYM_MCP_STDIO_SANDBOX=subprocess` and `HEYM_MCP_STDIO_FILES_HOST_DIR` are never settable by a workflow author, only by whoever runs the deployment. Both can remove the isolation this section describes, so treat them as trusted single-user / single-tenant options and leave them unset on anything multi-user.

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_MCP_STDIO_SANDBOX` | Isolation for MCP `stdio` servers: `auto` (Docker required, fail-closed), `docker` (never falls back), or `subprocess`. Independent of `HEYM_PYTHON_TOOL_SANDBOX`. ⚠️ `subprocess` removes the boundary entirely and runs the caller's command on the backend host, which is the GHSA-378x-q589-34mv condition: **trusted single-user instances only, never on a shared or hosted deployment.** | `auto` |
| `HEYM_MCP_STDIO_IMAGE` | Image used to run non-`docker` stdio commands (`npx`, `uvx`, `node`, `python`, …). Compose defaults it to `HEYM_BACKEND_IMAGE`, the GHCR image to its own release tag; set it only for native `run.sh` (`heym-backend:local`) or a custom runner. Falls back to `HEYM_PYTHON_TOOL_IMAGE`, then `HEYM_CODEX_DOCKER_IMAGE`, then container inspect, then fails closed. The `docker run <image>` form names its own image. | — |
| `HEYM_MCP_STDIO_FILES_PATH` | Mount point inside the sandbox for the optional file mount below. | `/mnt/heym-files` |
| `HEYM_MCP_STDIO_FILES_VOLUME` | Docker volume to expose to MCP servers. **Nothing is mounted unless you set this** (or the host-dir variant); there is no fallback to application volumes. | — |
| `HEYM_MCP_STDIO_FILES_SUBPATH` | Mount only this subpath of the volume, so a shared volume can be scoped per tenant or per purpose. | — |
| `HEYM_MCP_STDIO_FILES_HOST_DIR` | Absolute host path to expose instead of a volume. No fallback to `FILE_STORAGE_DIR`. ⚠️ This bind-mounts a backend host path into the sandbox, so a wide path (or one holding several tenants' data) weakens the boundary: scope it deliberately, and prefer a volume with `HEYM_MCP_STDIO_FILES_SUBPATH` on shared deployments. | — |
| `HEYM_MCP_STDIO_FILES_WRITABLE` | Mount the file mount read-write. Read-only otherwise. | `false` |
| `HEYM_MCP_STDIO_TMPFS_SIZE` | Size of the writable `/tmp` tmpfs, which holds the npm/uv caches and anything the server installs at startup. Raise it for large packages. | `512m` |
| `HEYM_MCP_STDIO_MEMORY` | Memory limit for MCP stdio containers. | `512m` |
| `HEYM_MCP_STDIO_CPUS` | CPU limit for MCP stdio containers. | `2` |
| `HEYM_MCP_STDIO_PIDS` | PID limit for MCP stdio containers. | `256` |
| `HEYM_MCP_STDIO_USER` | Non-root user for the MCP server, as a canonical `uid:gid` of two positive numbers. Anything else falls back to the default: a bare `uid` (Docker would put it in group root), a zero uid or gid in any spelling (`0`, `00`, `+0`, `:0`, `1000:0`), a user name, or a value with whitespace or extra fields. The value is re-rendered from the parsed numbers, so what is validated is what Docker receives. | `65534:65534` |

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
| `HEYM_PLUGINS_DIR` | Directory where installed plugins are stored. Same relative-path caveat as `FILE_STORAGE_DIR`: use an absolute `/app/data/plugins` when bind-mounting it into the single-image release. | `data/plugins` |

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
| `HEYM_CODEX_DOCKER_MEMORY` | Memory limit passed to Codex runner containers. | `4g` |
| `HEYM_CODEX_DOCKER_PIDS` | PID limit passed to Codex runner containers. | `1024` |
| `HEYM_CODEX_GIT_AUTHOR_NAME` | Author name for commits Codex creates. | `Heym Codex` |
| `HEYM_CODEX_GIT_AUTHOR_EMAIL` | Author email for Codex commits. The GitHub avatar shown next to it is derived from this email (matching GitHub account, else Gravatar). | `support@heym.run` |
| `HEYM_CODEX_OAUTH_CLIENT_ID` | OpenAI OAuth client id for "Sign in with ChatGPT". Defaults to the public Codex CLI client. | `app_EMoamEEZ73f0CkXaXp7hrann` |
| `HEYM_CODEX_OAUTH_ISSUER` | OpenAI OAuth issuer base URL. | `https://auth.openai.com` |
| `HEYM_CODEX_OAUTH_REDIRECT_URI` | OAuth redirect URI (fixed by OpenAI's Codex client; used for the paste-back flow). | `http://localhost:1455/auth/callback` |

> `HEYM_CODEX_CLI_VERSION` is a **Docker build arg** (not a runtime env var) that pins the `@openai/codex` npm version installed into the image. Default `latest`.

## OpenCode Go node

The [OpenCode Go node](frontend/src/docs/content/nodes/opencode-go-node.md) runs the OpenCode CLI (Go) in an isolated workspace against a GitHub repository. It needs the `opencode` CLI and `git` on PATH. Local `./run.sh` uses the native `opencode` CLI (host subprocess). Docker deployments use the bundled `heym-opencode-docker` wrapper, which starts a hardened sibling container from the same Heym image (all capabilities dropped, `no-new-privileges`, read-only root, resource limits) sharing the workspace named volume. All git/GitHub operations run host-side, so the GitHub token is never placed inside the OpenCode process/container.

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_OPENCODE_CLI_COMMAND` | Path/name of the OpenCode CLI binary (or the `heym-opencode-docker` wrapper in Docker deployments). | `opencode` |
| `HEYM_OPENCODE_WORKSPACE_DIR` | Directory for cloned repo workspaces (its `<workspace>.oc-home` sibling holds the OpenCode config/auth for the run). | `./data/opencode-workspaces` |
| `HEYM_OPENCODE_GIT_AUTHOR_NAME` | Author name for commits OpenCode creates. | `Heym OpenCode` |
| `HEYM_OPENCODE_GIT_AUTHOR_EMAIL` | Author email for OpenCode commits. The GitHub avatar shown next to it is derived from this email (matching GitHub account, else Gravatar). | `support@heym.run` |
| `HEYM_OPENCODE_DOCKER_IMAGE` | Image used by `heym-opencode-docker`. Compose defaults to the locally built backend image (`heym-backend:local`). The release image defaults to the same single GHCR image (`ghcr.io/heymrun/heym:<version>`). | auto |
| `HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME` | Docker volume mounted into each OpenCode runner at `HEYM_OPENCODE_WORKSPACE_DIR`. Docker Compose uses `heym-opencode-workspaces`. | — |
| `HEYM_OPENCODE_HOST_WORKSPACE_DIR` | Absolute host path for `HEYM_OPENCODE_WORKSPACE_DIR` when using bind mounts instead of a Docker volume. | — |
| `HEYM_OPENCODE_DOCKER_NETWORK` | Docker network mode for OpenCode runner containers (egress is required to reach the model gateway). | `bridge` |
| `HEYM_OPENCODE_DOCKER_CPUS` | CPU limit passed to OpenCode runner containers. | `2` |
| `HEYM_OPENCODE_DOCKER_MEMORY` | Memory limit passed to OpenCode runner containers. | `4g` |
| `HEYM_OPENCODE_DOCKER_PIDS` | PID limit passed to OpenCode runner containers. | `1024` |
| `HEYM_OPENCODE_DOCKER_ENTRYPOINT` | Entrypoint binary run inside the OpenCode runner container. | `opencode` |
| `HEYM_OPENCODE_DOCKER_EXTRA_ARGS` | Extra `docker run` arguments appended to the OpenCode runner invocation (shell-split). | — |

> `HEYM_OPENCODE_CLI_VERSION` is a **Docker build arg** (not a runtime env var) that pins the `opencode` CLI GitHub release installed into the image. Default `latest`.

## OpenTelemetry tracing

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_OTEL_ENABLED` | Emit a root span per workflow run and a child span per node over OTLP/HTTP. | `false` |
| `HEYM_OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP base endpoint, e.g. `http://collector:4318` (spans posted to `/v1/traces`). | — |
| `HEYM_OTEL_EXPORTER_OTLP_HEADERS` | Comma-separated `key=value` exporter headers for auth. | — |
| `HEYM_OTEL_SERVICE_NAME` | `service.name` resource attribute. | `heym` |
| `HEYM_OTEL_TRACES_SAMPLER_RATIO` | Parent-based head sampling ratio (`0.0`–`1.0`). | `1.0` |
| `HEYM_OTEL_CAPTURE_NODE_IO` | Attach truncated node input/output to node spans (may contain user data). | `false` |

## Load distribution (multi-instance)

Point a second Heym instance at the same database and it joins as a worker.
Background runs are shared between the instances by a percentage set under
**Settings → Instances**. Postgres is the only channel between them: a worker
needs no open port and no route back to the main instance.

Two rules the cluster cannot enforce for you:

- **`SECRET_KEY` and `ENCRYPTION_KEY` must be identical on every instance.** A
  worker with a different `ENCRYPTION_KEY` cannot decrypt credentials. Heym
  compares digests of both keys on each heartbeat and marks a mismatched
  instance incompatible so it receives no work, rather than letting it fail
  every credential-using run.
- **Point ingress at the main instance only.** Round-robining user traffic
  across instances would send a file upload to one machine and its download to
  another.

Worker instances also have a different outbound IP than main. Any API that
allowlists source addresses sees the new one. `sendEmail` runs on main for
exactly this reason; for the HTTP node, give the cluster one NAT egress address
or allowlist every instance.

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_CLUSTER_ENABLED` | Turn load distribution on. Off means every run executes in-process exactly as before. | `false` |
| `HEYM_INSTANCE_ROLE` | `main` or `worker`. Main owns file storage, plugins and ingress. | `main` |
| `HEYM_INSTANCE_NAME` | Display label for this instance; the admin UI can rename it later. | — |
| `HEYM_INSTANCE_ID` | Stable id shared by all of this instance's processes. Derived from the name when empty. | — |

## Miscellaneous

| Variable | Description | Default |
|----------|-------------|---------|
| `HEYM_LLM_PRICING_SYNC_ENABLED` | Periodically sync model pricing data. | `true` |
| `APP_VERSION` | Override the reported app version. Empty reads the `VERSION` file. | — |
| `HEYM_BACKEND_IMAGE` | Compose only (`./deploy.sh`): tag the backend is built and run as. Every sibling sandbox image (MCP stdio, Playwright, Codex, OpenCode) defaults to it. | `heym-backend:local` |

## Frontend build-time

These are read at build time by Vite and baked into the frontend bundle.

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_URL` | Base URL the frontend calls for the API. | same-origin |
| `VITE_APP_VERSION` | Version string shown in the UI. | from build |
| `VITE_HEYM_WEB_URL` | Marketing/site URL used for external links. | — |
