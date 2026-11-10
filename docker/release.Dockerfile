# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS frontend-builder

# Keep vue-tsc on real Node.js, as in PR checks. Bun-only images alias node to bun.
COPY --from=oven/bun:1.4.2 /usr/local/bin/bun /usr/local/bin/bun

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


# `vite preview` serves the built frontend and proxies /api, websockets and the OAuth routes
# (see vite.config.ts), so the runtime keeps vite. It does not need the rest of the build
# toolchain: vite.config.ts imports only vite and @vitejs/plugin-vue. Installing just those
# two against bun.lock keeps their locked versions, and their own dependencies', in about
# 37 MB instead of the full ~300 MB tree.
FROM node:22-bookworm-slim AS frontend-runtime-deps

COPY --from=oven/bun:1.4.2 /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /app

COPY frontend/package.json frontend/bun.lock* ./
RUN node -e ' \
    const fs = require("fs"); \
    const pkg = JSON.parse(fs.readFileSync("package.json", "utf8")); \
    const keep = ["vite", "@vitejs/plugin-vue"]; \
    pkg.dependencies = Object.fromEntries(keep.map((name) => [name, pkg.devDependencies[name]])); \
    delete pkg.devDependencies; \
    fs.writeFileSync("package.json", JSON.stringify(pkg, null, 2)); \
    ' \
    && bun install \
    && node node_modules/vite/bin/vite.js --version


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
    ripgrep \
    tzdata \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 LTS, for Codex, MCP stdio servers started with npx, and `vite preview`. Copied
# from the official image the frontend builds on, instead of Debian's nodejs and npm.
COPY --from=frontend-runtime-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-runtime-deps /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version \
    && npm --version

# Converter node file support. WeasyPrint is the pandoc PDF engine used by fileConvert; its
# Python package comes from docker/converter-requirements.txt below, and Pango, HarfBuzz and
# shared-mime-info are its system libraries. OCR (imageToText/pdfToText) needs Tesseract plus
# poppler's pdftoppm, which rasterizes PDF pages before recognition. `osd` and the script models are what make the "auto" language
# setting work. OSD detects the script, then a script model such as Latin reads every
# language written in it. Debian installs the script models without the "script/" prefix,
# so tesseract lists them as Latin, Cyrillic, HanS, and so on.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    shared-mime-info \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-osd \
    tesseract-ocr-eng \
    tesseract-ocr-tur \
    tesseract-ocr-deu \
    tesseract-ocr-fra \
    tesseract-ocr-spa \
    tesseract-ocr-ita \
    tesseract-ocr-por \
    tesseract-ocr-nld \
    tesseract-ocr-rus \
    tesseract-ocr-ara \
    tesseract-ocr-chi-sim \
    tesseract-ocr-jpn \
    tesseract-ocr-kor \
    tesseract-ocr-script-latn \
    tesseract-ocr-script-cyrl \
    tesseract-ocr-script-arab \
    tesseract-ocr-script-hans \
    tesseract-ocr-script-jpan \
    tesseract-ocr-script-hang \
    && rm -rf /var/lib/apt/lists/* \
    && tesseract --version \
    && pdftoppm -v

# Whisper model for the Converter node's audioToText conversion, baked in so no container
# downloads it at runtime. The packages that run it come from uv sync.
COPY docker/install-stt-model.sh /tmp/install-stt-model.sh
RUN sh /tmp/install-stt-model.sh /opt/heym/stt && rm /tmp/install-stt-model.sh

# OpenAI Codex CLI (required by the Codex node). Pin via the HEYM_CODEX_CLI_VERSION build arg.
ARG HEYM_CODEX_CLI_VERSION=latest
RUN npm install -g @openai/codex@${HEYM_CODEX_CLI_VERSION}

# OpenCode CLI (required by the OpenCode Go node). Pin via the HEYM_OPENCODE_CLI_VERSION build arg.
ARG HEYM_OPENCODE_CLI_VERSION=latest
RUN ARCH="$(uname -m)" \
    && case "$ARCH" in \
        x86_64)  OA=x64   ;; \
        aarch64) OA=arm64 ;; \
        *) echo "Unsupported arch for OpenCode CLI: $ARCH" && exit 1 ;; \
    esac \
    && if [ "${HEYM_OPENCODE_CLI_VERSION}" = "latest" ]; then \
        OC_URL="https://github.com/anomalyco/opencode/releases/latest/download/opencode-linux-${OA}.tar.gz"; \
    else \
        OC_VER="${HEYM_OPENCODE_CLI_VERSION#v}"; \
        OC_URL="https://github.com/anomalyco/opencode/releases/download/v${OC_VER}/opencode-linux-${OA}.tar.gz"; \
    fi \
    && curl -fsSL --retry 5 --retry-all-errors --retry-delay 2 -o /tmp/opencode.tar.gz "$OC_URL" \
    && tar xz -C /usr/local/bin -f /tmp/opencode.tar.gz opencode \
    && rm /tmp/opencode.tar.gz \
    && chmod +x /usr/local/bin/opencode \
    && opencode --version

# Install Docker CLI (static binary — no daemon needed, connects via mounted socket)
RUN ARCH="$(uname -m)" \
    && case "$ARCH" in \
        x86_64)  DA=x86_64  ;; \
        aarch64) DA=aarch64 ;; \
        armv7l)  DA=armv7   ;; \
        *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DA}/docker-29.9.3.tgz" \
        | tar xz --strip-components=1 -C /usr/local/bin docker/docker

ENV DOCS_DIR=/app/docs \
    PLAYWRIGHT_INSTALL_AT_STARTUP=false \
    FRONTEND_PORT=4017 \
    BACKEND_PORT=10105 \
    BACKEND_WORKERS=8

RUN pip install uv

# The file-analysis sandbox runs this image's system Python (not the venv) with no
# network, so its libraries are baked in here.
COPY docker/sandbox-requirements.txt /tmp/sandbox-requirements.txt
RUN uv pip install --system --no-cache -r /tmp/sandbox-requirements.txt \
    && rm /tmp/sandbox-requirements.txt

COPY docker/converter-requirements.txt /tmp/converter-requirements.txt
RUN uv pip install --system --no-cache -r /tmp/converter-requirements.txt \
    && rm /tmp/converter-requirements.txt \
    && weasyprint --info

ARG APP_VERSION
ENV APP_VERSION=${APP_VERSION}

# Image the sibling sandboxes below start. The release workflow passes the
# published tag; the default keeps an argless local build from baking in a
# dangling `ghcr.io/heymrun/heym:` (APP_VERSION is empty there).
ARG HEYM_RELEASE_IMAGE=ghcr.io/heymrun/heym:latest

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
COPY --from=frontend-runtime-deps /app/node_modules /app/frontend/node_modules
COPY --from=frontend-builder /app/vite.config.ts /app/frontend/vite.config.ts
COPY docker/release-entrypoint.sh /app/release-entrypoint.sh
COPY docker/heym-codex-docker /usr/local/bin/heym-codex-docker
COPY docker/heym-opencode-docker /usr/local/bin/heym-opencode-docker

# Playwright: install Chromium and final-stage system dependencies into the release image.
# Outside root's home so a non-root sandbox (Kubernetes runs it as 65534) can read the browsers.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN cd /app/backend && uv run python -m playwright install --with-deps chromium

ENV HEYM_CODEX_CLI_COMMAND=/usr/local/bin/heym-codex-docker \
    HEYM_CODEX_DOCKER_IMAGE=${HEYM_RELEASE_IMAGE} \
    HEYM_CODEX_DOCKER_WORKSPACE_VOLUME=heym-codex-workspaces \
    HEYM_CODEX_NETWORK_ACCESS=true \
    HEYM_CODEX_WORKSPACE_DIR=/app/data/codex-workspaces \
    HEYM_OPENCODE_CLI_COMMAND=/usr/local/bin/heym-opencode-docker \
    HEYM_OPENCODE_DOCKER_IMAGE=${HEYM_RELEASE_IMAGE} \
    HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME=heym-opencode-workspaces \
    HEYM_OPENCODE_WORKSPACE_DIR=/app/data/opencode-workspaces \
    HEYM_SKILL_IMAGE=${HEYM_RELEASE_IMAGE} \
    HEYM_PLAYWRIGHT_SANDBOX_IMAGE=${HEYM_RELEASE_IMAGE} \
    HEYM_PLAYWRIGHT_SANDBOX_PYTHON=/app/backend/.venv/bin/python \
    HEYM_MCP_STDIO_IMAGE=${HEYM_RELEASE_IMAGE}

RUN chmod +x /app/release-entrypoint.sh /usr/local/bin/heym-codex-docker /usr/local/bin/heym-opencode-docker

EXPOSE 4017

ENTRYPOINT ["/app/release-entrypoint.sh"]
