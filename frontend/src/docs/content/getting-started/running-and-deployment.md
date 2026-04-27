# Running & Deployment

Heym provides two scripts for different environments: `run.sh` for local development and `deploy.sh` for production deployments using Docker Compose.

## Prerequisites

Both scripts require the following tools to be installed:

| Tool | Purpose |
|------|---------|
| [Docker](https://docs.docker.com/get-docker/) | Database container (dev) and full stack (prod) |
| [uv](https://github.com/astral-sh/uv) | Python package manager for the backend |
| [bun](https://bun.sh) | JavaScript runtime for the frontend |

## Environment Setup

Both scripts read from a `.env` file in the project root. If it does not exist, `run.sh` automatically creates one from `.env.example`. For `deploy.sh`, you must create it manually:

```bash
cp .env.example .env
```

Key environment variables:

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | **Required.** JWT signing secret |
| `ENCRYPTION_KEY` | **Required.** Credential encryption key |
| `DATABASE_URL` | Optional database connection string override. If empty, Heym builds it from `POSTGRES_*` settings. |
| `BACKEND_PORT` | Backend API port — defaults to `10105` |
| `FRONTEND_PORT` | Frontend port — defaults to `4017` |
| `FRONTEND_URL` | **Required in production.** Public URL of the app (scheme + host, e.g. `https://heym.example.com`). Used for Google Sheets OAuth redirect URI and similar; must match the URL users use in the browser. |
| `ALLOW_REGISTER` | Open user registration (`false` in prod, `true` in dev) |

Database connection defaults (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) are documented in `.env.example`.

---

## Development: `run.sh`

`run.sh` starts all three services locally — the database (as a Docker container), the FastAPI backend, and the Vite dev server — with a single command.

```bash
./run.sh
```

**What it does, step by step:**

1. Checks that `docker`, `bun`, and `uv` are available
2. Creates `.env` from `.env.example` if missing
3. Starts (or creates) a database Docker container on port `6543`
4. Installs Python dependencies via `uv sync`
5. Runs Alembic database migrations (`alembic upgrade head`)
6. Frees the backend and frontend ports if occupied
7. Starts the FastAPI backend with `--reload` (hot-reload on code changes)
8. Installs frontend dependencies via `bun install`
9. Starts the Vite dev server

**Options:**

| Flag | Description |
|------|-------------|
| *(none)* | Start with debug logging enabled (`LOG_LEVEL=DEBUG`) |
| `--no-debug` | Start with default log level (no debug output) |
| `--help` | Show usage information |

**Service addresses (dev):**

| Service | Address |
|---------|---------|
| Frontend | `localhost` on `FRONTEND_PORT` (default: 4017) |
| Backend API | `localhost` on `BACKEND_PORT` (default: 10105) |
| Interactive API Docs | `localhost:10105/docs` |
| Database | `localhost:6543` |

Press `Ctrl+C` to gracefully stop all services.

---

## Production: `deploy.sh`

`deploy.sh` builds and runs the full stack using Docker Compose. All three services — the database, the backend, and the frontend — run as containers. The backend entrypoint automatically runs migrations before starting the server with 8 workers.

**Initial deploy (build + start):**

```bash
./deploy.sh
```

This performs a zero-downtime deploy: images are built first while the existing containers keep running, then the new version is swapped in.

**Available commands:**

| Command | Description |
|---------|-------------|
| `./deploy.sh` | Build images and start/update all services |
| `./deploy.sh --status` | Show container status |
| `./deploy.sh --logs` | Stream logs from all containers |
| `./deploy.sh --restart` | Restart all containers |
| `./deploy.sh --down` | Stop and remove all containers |
| `./deploy.sh --help` | Show usage information |

**Service addresses (production):**

The frontend container is exposed on `FRONTEND_PORT` (default: 4017). The backend API is served under the `/api` path, proxied through the frontend container — so there is only one public-facing port in production.

**Container overview:**

| Container | Description |
|-----------|-------------|
| `heym-db` | Relational database |
| `heym-backend` | FastAPI API server (8 workers, built from `backend/Dockerfile`) |
| `heym-frontend` | Frontend preview container serving the built Vue app (built from `frontend/Dockerfile`) |

---

## Prebuilt Image: `docker run`

If you prefer not to build the app locally, you can pull the published container image and run it directly.

The image starts the frontend and backend together in one container. PostgreSQL is still external, but you can provide either `DATABASE_URL` or the `POSTGRES_*` variables from `.env.example`.

```bash
docker pull ghcr.io/heymrun/heym:latest

docker run --rm \
  --env-file .env \
  -p 4017:4017 \
  ghcr.io/heymrun/heym:latest
```

**Minimum environment variables for direct image runs:**

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Optional | Full PostgreSQL connection string override |
| `POSTGRES_HOST` | Yes, if `DATABASE_URL` is empty | PostgreSQL host |
| `POSTGRES_PORT` | Yes, if `DATABASE_URL` is empty | PostgreSQL port |
| `POSTGRES_USER` | Yes, if `DATABASE_URL` is empty | PostgreSQL username |
| `POSTGRES_PASSWORD` | Yes, if `DATABASE_URL` is empty | PostgreSQL password |
| `POSTGRES_DB` | Yes, if `DATABASE_URL` is empty | PostgreSQL database name |
| `SECRET_KEY` | Yes | JWT signing secret |
| `ENCRYPTION_KEY` | Yes | Credential encryption key |
| `FRONTEND_URL` | Recommended | Public browser URL, especially for OAuth callbacks |
| `CORS_ORIGINS` | Recommended | Allowed browser origins |
| `ALLOW_REGISTER` | Recommended | Set `false` in production unless open signup is intended |

**Notes:**

- The image exposes port `4017`
- The backend stays internal and is proxied under `/api`
- When `POSTGRES_HOST=localhost`, the release image automatically rewrites it to `host.docker.internal` when needed so the same `.env` works with a host-level PostgreSQL container on macOS Docker/Desktop tools
- Mount persistent storage if you want uploaded/generated files to survive container restarts

---

## Common Workflows

**First-time setup:**

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY and ENCRYPTION_KEY at minimum
./run.sh          # development
# or
./deploy.sh       # production
```

**Update production after a code change:**

```bash
git pull
./deploy.sh       # rebuilds images, zero-downtime swap
```

**Check production logs:**

```bash
./deploy.sh --logs
```

**Stop production services:**

```bash
./deploy.sh --down
```

---

## Related

- [Introduction](./introduction.md) – Platform overview
- [Quick Start](./quick-start.md) – Build your first workflow
- [Security](../reference/security.md) – JWT, encryption, and CORS settings
