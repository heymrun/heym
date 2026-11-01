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

# OCR for the Converter node (imageToText/pdfToText): Tesseract plus poppler's pdftoppm,
# which rasterizes PDF pages before recognition. `osd` and the script models are what make
# the "auto" language setting work. OSD detects the script, then a script model such as
# Latin reads every language written in it. Debian installs the script models without the
# "script/" prefix, so tesseract lists them as Latin, Cyrillic, HanS, and so on.
RUN apt-get update && apt-get install -y --no-install-recommends \
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

# OpenAI Codex CLI (required by the Codex node). Pin via the HEYM_CODEX_CLI_VERSION build arg.
ARG HEYM_CODEX_CLI_VERSION=latest
RUN npm install -g @openai/codex@${HEYM_CODEX_CLI_VERSION}

# Bun (required for frontend lint/typecheck from this image, e.g. opencode isolated execution).
RUN curl -fsSL https://bun.sh/install | bash \
    && ln -sf /root/.bun/bin/bun /usr/local/bin/bun \
    && bun --version

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
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DA}/docker-27.3.1.tgz" \
        | tar xz --strip-components=1 -C /usr/local/bin docker/docker

ENV TZ=Europe/Berlin

RUN pip install uv

# The file-analysis sandbox runs this image's system Python (not the venv) with no
# network, so its libraries are baked in here.
COPY docker/sandbox-requirements.txt /tmp/sandbox-requirements.txt
RUN uv pip install --system --no-cache -r /tmp/sandbox-requirements.txt \
    && rm /tmp/sandbox-requirements.txt

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
