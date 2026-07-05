# syntax=docker/dockerfile:1.7

FROM oven/bun:1 AS frontend-builder

WORKDIR /app

COPY frontend/package.json frontend/bun.lock* ./
RUN bun install --frozen-lockfile

COPY VERSION /app/VERSION
COPY frontend/ .

ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION}

ARG VITE_HEYM_WEB_URL=https://heym.run
ENV VITE_HEYM_WEB_URL=${VITE_HEYM_WEB_URL}

RUN bun run build


FROM python:3.14-slim AS backend-builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-dev

COPY backend/ .
COPY AGENTS.md /app/AGENTS.md
COPY VERSION /app/VERSION
COPY frontend/src/docs/content /app/docs


FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bubblewrap \
    ca-certificates \
    curl \
    git \
    nodejs \
    npm \
    ripgrep \
    tzdata \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# OpenAI Codex CLI (required by the Codex node). Pin via the HEYM_CODEX_CLI_VERSION build arg.
ARG HEYM_CODEX_CLI_VERSION=latest
RUN npm install -g @openai/codex@${HEYM_CODEX_CLI_VERSION}

# Install Docker CLI (static binary — no daemon needed, connects via mounted socket)
RUN ARCH="$(uname -m)" \
    && case "$ARCH" in \
        x86_64)  DA=x86_64  ;; \
        aarch64) DA=aarch64 ;; \
        armv7l)  DA=armv7   ;; \
        *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DA}/docker-27.3.1.tgz" \
        | tar xz --strip-components=1 -C /usr/local/bin docker/docker

ENV DOCS_DIR=/app/docs \
    PLAYWRIGHT_INSTALL_AT_STARTUP=false \
    FRONTEND_PORT=4017 \
    BACKEND_PORT=10105 \
    BACKEND_WORKERS=8

RUN pip install uv

ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION}

ARG OCI_SOURCE=https://github.com/heymrun/heym
ARG OCI_URL=https://heym.run
ARG OCI_DOCUMENTATION_URL=https://github.com/heymrun/heym

LABEL org.opencontainers.image.title="Heym" \
    org.opencontainers.image.description="Heym single-container release image" \
    org.opencontainers.image.version="${APP_VERSION}" \
    org.opencontainers.image.source="${OCI_SOURCE}" \
    org.opencontainers.image.url="${OCI_URL}" \
    org.opencontainers.image.documentation="${OCI_DOCUMENTATION_URL}" \
    org.opencontainers.image.vendor="Heym" \
    org.opencontainers.image.licenses="MIT with Commons Clause condition" \
    org.label-schema.name="Heym" \
    org.label-schema.description="Heym single-container release image" \
    org.label-schema.vendor="Heym" \
    org.label-schema.url="${OCI_URL}" \
    org.label-schema.vcs-url="${OCI_SOURCE}" \
    org.label-schema.version="${APP_VERSION}" \
    org.label-schema.usage="${OCI_DOCUMENTATION_URL}" \
    org.label-schema.schema-version="1.0"

COPY --from=backend-builder /app /app/backend
COPY --from=backend-builder /app/AGENTS.md /app/AGENTS.md
COPY --from=backend-builder /app/docs /app/docs
COPY --from=frontend-builder /app/dist /app/frontend/dist
COPY --from=frontend-builder /app/package.json /app/frontend/package.json
COPY --from=frontend-builder /app/node_modules /app/frontend/node_modules
COPY --from=frontend-builder /app/vite.config.ts /app/frontend/vite.config.ts
COPY docker/release-entrypoint.sh /app/release-entrypoint.sh
COPY docker/heym-codex-docker /usr/local/bin/heym-codex-docker

# Playwright: install Chromium and final-stage system dependencies into the release image.
RUN cd /app/backend && uv run python -m playwright install --with-deps chromium

ENV HEYM_CODEX_CLI_COMMAND=/usr/local/bin/heym-codex-docker \
    HEYM_CODEX_DOCKER_IMAGE=ghcr.io/heymrun/heym:${APP_VERSION} \
    HEYM_CODEX_DOCKER_WORKSPACE_VOLUME=heym-codex-workspaces \
    HEYM_CODEX_NETWORK_ACCESS=true \
    HEYM_CODEX_WORKSPACE_DIR=/app/data/codex-workspaces

RUN chmod +x /app/release-entrypoint.sh /usr/local/bin/heym-codex-docker

EXPOSE 4017

ENTRYPOINT ["/app/release-entrypoint.sh"]
