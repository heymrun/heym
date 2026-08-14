# Security

Security practices and configuration for the Heym platform.

## Password Policy

All passwords — at registration and when changing your password — must meet these requirements:

| Rule | Requirement |
|------|-------------|
| Minimum length | 8 characters |
| Uppercase | At least one uppercase letter (A–Z) |
| Lowercase | At least one lowercase letter (a–z) |
| Digit | At least one number (0–9) |

These rules are enforced on both the frontend and the backend (Pydantic validator). A request with a non-compliant password is rejected with a `422 Unprocessable Entity` response before any database write occurs.

**Example of a valid password:** `MyWorkflow7!`

## Session Management

- Access tokens are stored in **HttpOnly** cookies, not `localStorage`. This prevents JavaScript (including XSS payloads) from reading the token.
- The refresh token is scoped to the `/api/auth/refresh` path and cannot be sent to other endpoints.
- Each `/api/auth/refresh` call **rotates** the refresh token: the old token is immediately revoked and a new one is issued. Replaying a used refresh token returns `401`.

## Rate Limiting

The following endpoints are rate-limited per IP:

| Endpoint | Limit | Ban duration |
|----------|-------|--------------|
| `POST /api/auth/login` | 10 req / 60 s | 15 min |
| `POST /api/auth/register` | 5 req / 60 s | 10 min |
| `POST /register` (OAuth clients) | 5 req / 60 s | 10 min |
| Portal login | 3 attempts | 24 h |

When `REDIS_URL` is configured, rate limits are shared across all backend workers. Without it, limits apply per worker process.

## Credential Encryption

All API keys, webhook URLs, and bearer tokens stored in the [Credentials](../tabs/credentials-tab.md) panel are encrypted at rest using AES-256 (Fernet) before being written to the database. The key is derived from the `ENCRYPTION_KEY` environment variable. The `run.sh` and `deploy.sh` scripts generate a strong value automatically when it is empty; the application refuses to start if `ENCRYPTION_KEY` is empty or left at a known placeholder.

## MCP API Key

The MCP API key is used to authenticate external MCP clients connecting to the `/api/mcp/sse` endpoint. When the SSE connection is established, a short-lived (1-hour) session token is issued and embedded in the message endpoint URL instead of the real API key, preventing the key from appearing in server access logs. See [MCP Tab](../tabs/mcp-tab.md) for setup.

## OAuth / PKCE

The OAuth 2.0 authorization server (used for MCP clients) supports only the `authorization_code` grant with PKCE (`S256`). The consent form uses HMAC-SHA256 CSRF tokens valid for 10 minutes. All values displayed in the consent page are HTML-escaped.

## Execution Tokens

[Execution tokens](./execution-tokens.md) are scoped JWTs for calling a workflow's execute endpoint from external systems. Unlike user session tokens, they are:

- **Single-workflow scoped** — a token is rejected for any other workflow.
- **Independently revocable** — revoking a token has no effect on the issuing user's session.
- **Short or long-lived** — choose a TTL from 60 seconds to 10 years.

Tokens are signed with the same application secret (`SECRET_KEY`) and checked on every request: signature, expiry, `wid` claim match, and revocation status. See [Execution Tokens](./execution-tokens.md) for setup and API reference.

## Content Safety

Use [Guardrails](./guardrails.md) on LLM and Agent nodes to block unsafe or policy-violating user messages before they reach the model. Guardrails support nine content categories (violence, hate speech, sexual content, etc.) with configurable sensitivity levels.

## Python Tool Sandbox

User-defined Python tools on the [Agent node](../nodes/agent-node.md) execute untrusted code. By default Heym runs each tool inside a hardened, throwaway Docker container with:

- no network access,
- a read-only root filesystem with a small `tmpfs` working directory,
- a non-root user with all Linux capabilities dropped and `no-new-privileges`,
- strict CPU, memory, and PID limits, and
- **no Docker socket** mounted, so a tool cannot reach the host Docker daemon.

The execution backend is controlled by the `HEYM_PYTHON_TOOL_SANDBOX` environment variable:

| Value | Behavior |
|-------|----------|
| `auto` (default) | Run in the hardened Docker container. If Docker is unavailable, execution **fails closed** — it does not silently run untrusted code without OS isolation. |
| `docker` | Same as `auto`, but never falls back. |
| `subprocess` | Run in a local in-process subprocess guarded by an import allowlist. This is **not a security boundary** and is intended only for trusted code or local development. `run.sh` selects it for native dev. |

Set `HEYM_PYTHON_TOOL_IMAGE` to pin the sandbox image; when empty, Heym auto-detects the running backend image. The in-process restrictions (an import allowlist plus attribute and introspection filtering) are applied as defense in depth, but the container is the real isolation boundary — keep the default `auto` (or `docker`) mode for multi-user and production deployments.

## Skill Sandbox

Python skills attached to an [Agent node](../nodes/agent-node.md) also execute untrusted code — a skill can arrive verbatim inside a shared workflow or an `everyone`-visibility template — so skills run through the **same** `HEYM_PYTHON_TOOL_SANDBOX` switch as Python tools and fail closed the same way. The skill container is hardened identically (non-root, all capabilities dropped, `no-new-privileges`, read-only root filesystem, CPU/memory/PID limits, and **no Docker socket**), with two deliberate differences because skills legitimately need them:

- **Network egress is allowed** (skills call APIs and install their own dependencies via `uv`), and
- **a writable workspace is mounted** so skills can generate output files and read Heym Drive files.

The workspace is shared with the throwaway sibling container through the same named Docker volume the Codex runner uses (`heym-codex-workspaces`, mounted at `/app/data/codex-workspaces`). Only this run's own subdirectory is mounted into the sibling — via a per-run `volume-subpath` — so one skill never sees another run's or Codex's workspace data. The Docker Compose stack always mounts this volume; the single-container `docker run` must include `-v heym-codex-workspaces:/app/data/codex-workspaces` for Python skills as well as Codex. If the volume is missing in `auto`/`docker` mode, skill execution **fails closed** rather than running in the backend. Because per-run subpath mounts require **Docker Engine 25.0 or newer**, older engines should either upgrade or run trusted skills with `HEYM_PYTHON_TOOL_SANDBOX=subprocess`.

Only non-secret, portable environment variables (proxy and CA-bundle settings, locale) are forwarded into the container; database URLs, `SECRET_KEY`/`ENCRYPTION_KEY`, provider API keys, and OAuth secrets are withheld by an allowlist. Skill file paths are validated to stay inside the workspace, and symlinks planted in the output directory (including the `_hitl_request.json` sentinel) are never followed. Override the defaults with `HEYM_SKILL_IMAGE`, `HEYM_SKILL_NETWORK`, `HEYM_SKILL_MEMORY`, `HEYM_SKILL_CPUS`, `HEYM_SKILL_PIDS`, and `HEYM_SKILL_USER` if needed.

As with tools, `subprocess` mode runs the skill in the backend process and is **not a security boundary** — use it only for trusted single-user or local development (`run.sh` selects it for native dev).

## Code Node Sandbox

The [Code node](../nodes/code-node.md) runs arbitrary user Python together with arbitrary third-party dependencies, so it is the strictest of the three sandboxes and the only one with **no escape hatch**: it reads no sandbox-mode variable, has no `subprocess` mode, and fails closed when no Docker daemon is reachable. It never falls back to running user code in the backend process.

Execution is one or two throwaway containers, both hardened like the tool and skill sandboxes (non-root, all capabilities dropped, `no-new-privileges`, read-only root filesystem, CPU/memory/PID limits, and **no Docker socket**):

- With an empty `requirements.txt`, a **single container with `--network none`** runs the code. The runner arrives in the container's stdin payload, so nothing is mounted at all.
- With dependencies, a first container installs them with network access into a per-run `.deps` directory, and a second container mounts that subtree **read-only** and runs the code. The execution container has no network unless the node's `codeAllowNetwork` option is turned on.

Dependencies are installed with `uv`, retried with `pip`, and never cached between runs. When the backend runs in a container, the per-run directory lives on the same `heym-codex-workspaces` volume the skill sandbox uses, mounted through a per-run `volume-subpath` so one run never sees another's files; that form needs **Docker Engine 25.0 or newer**. A native backend (`./run.sh`) has no such volume and does not need one — its per-run directory is a local temporary path bind-mounted straight into the sibling. Either way the directory is deleted after every execution regardless of outcome.

Only non-secret, portable environment variables are forwarded into the containers — proxy settings, CA bundles, and locale, which dependency installation needs to reach PyPI behind a corporate proxy. Database URLs, `SECRET_KEY`/`ENCRYPTION_KEY`, provider API keys, and OAuth secrets are withheld by an allowlist, so a new backend secret is dropped by default rather than leaked until someone updates a denylist. The backend's `HOME` never overrides the sandbox's own writable path.

The **Format** button uses the same sandbox. Ruff parses and rewrites the source rather than executing it, but running it on the backend host would hand an untrusted file a process that inherits the backend's whole environment, so it gets its own throwaway `--network none` container with the same limits and the same allowlisted environment. It fails closed without Docker rather than formatting on the host.

Sandbox limits are constants rather than environment variables — 512 MB of memory, one CPU, 256 processes, a 120-second install timeout, and a 60-second execution timeout. The image is resolved from the existing `HEYM_PYTHON_TOOL_IMAGE` / `HEYM_CODEX_DOCKER_IMAGE` chain; the node introduces no configuration of its own.

## Related

- [Running & Deployment](../getting-started/running-and-deployment.md) – Configure `SECRET_KEY`, `ENCRYPTION_KEY`, `ALLOW_REGISTER`, and `HEYM_PYTHON_TOOL_SANDBOX` at startup
- [Code Node](../nodes/code-node.md) – Sandboxed Python execution with its own dependencies
- [Agent Node](../nodes/agent-node.md) – Custom Python tools that run in the sandbox
- [Execution Tokens](./execution-tokens.md) – Scoped JWTs for calling workflows from external systems
- [Guardrails](./guardrails.md) – Block unsafe content in LLM and Agent nodes
- [Settings](./user-settings.md) – Change your password
- [Credentials Tab](../tabs/credentials-tab.md) – Manage API keys
- [MCP Tab](../tabs/mcp-tab.md) – MCP API key and OAuth clients
- [Portal](./portal.md) – Public chat portal access control
