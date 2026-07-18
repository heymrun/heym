FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bubblewrap \
    curl \
    ca-certificates \
    tzdata \
    nodejs \
    npm \
    git \
    ripgrep \
    unzip \
    wget \
    weasyprint \
    && rm -rf /var/lib/apt/lists/*

# OpenAI Codex CLI (required by the Codex node). Pin via the HEYM_CODEX_CLI_VERSION build arg.
ARG HEYM_CODEX_CLI_VERSION=latest
RUN npm install -g @openai/codex@${HEYM_CODEX_CLI_VERSION}

# OpenCode CLI (Go) required by the OpenCode Go node. The runner executes it inside a hardened
# sibling container of this same image. Pin via the HEYM_OPENCODE_CLI_VERSION build arg; the
# installer resolves "latest" only when VERSION is unset (passing VERSION=latest looks up a literal
# "vlatest" tag and fails), so pass VERSION only for a pinned version.
ARG HEYM_OPENCODE_CLI_VERSION=latest
RUN if [ "${HEYM_OPENCODE_CLI_VERSION}" = "latest" ]; then \
        curl -fsSL https://opencode.ai/install | bash; \
    else \
        curl -fsSL https://opencode.ai/install | VERSION="${HEYM_OPENCODE_CLI_VERSION}" bash; \
    fi \
    && ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode \
    && opencode --version

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

ENV TZ=Europe/Berlin

RUN pip install uv

ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION}

COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-dev

# Playwright: install Chromium and system dependencies for browser automation
RUN uv run python -m playwright install --with-deps chromium

# Skip redundant install at container startup (already in image)
ENV PLAYWRIGHT_INSTALL_AT_STARTUP=false

COPY backend/ .
COPY docker/heym-codex-docker /usr/local/bin/heym-codex-docker
COPY docker/heym-opencode-docker /usr/local/bin/heym-opencode-docker

# AGENTS.md for dashboard chat system prompt (Heym platform context)
COPY AGENTS.md /app/AGENTS.md
COPY VERSION /app/VERSION

# Documentation for chat search (used by search_documentation tool)
COPY frontend/src/docs/content /app/docs
ENV DOCS_DIR=/app/docs

ENV HEYM_CODEX_CLI_COMMAND=/usr/local/bin/heym-codex-docker \
    HEYM_CODEX_DOCKER_IMAGE=heym-backend:local \
    HEYM_CODEX_DOCKER_WORKSPACE_VOLUME=heym-codex-workspaces \
    HEYM_CODEX_NETWORK_ACCESS=true \
    HEYM_CODEX_WORKSPACE_DIR=/app/data/codex-workspaces

# OpenCode Go node: run the OpenCode CLI in a dedicated hardened sibling runner container that
# shares the workspace named volume (mirrors the Codex setup).
ENV HEYM_OPENCODE_CLI_COMMAND=/usr/local/bin/heym-opencode-docker \
    HEYM_OPENCODE_DOCKER_IMAGE=heym-backend:local \
    HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME=heym-opencode-workspaces \
    HEYM_OPENCODE_WORKSPACE_DIR=/app/data/opencode-workspaces

RUN chmod +x entrypoint.sh /usr/local/bin/heym-codex-docker /usr/local/bin/heym-opencode-docker

EXPOSE 10105

ENTRYPOINT ["./entrypoint.sh"]
