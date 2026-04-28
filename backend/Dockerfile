FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

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

# AGENTS.md for dashboard chat system prompt (Heym platform context)
COPY AGENTS.md /app/AGENTS.md
COPY VERSION /app/VERSION

# Documentation for chat search (used by search_documentation tool)
COPY frontend/src/docs/content /app/docs
ENV DOCS_DIR=/app/docs

RUN chmod +x entrypoint.sh

EXPOSE 10105

ENTRYPOINT ["./entrypoint.sh"]
