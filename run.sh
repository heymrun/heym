#!/bin/bash

# Re-exec under bash when invoked as `sh run.sh` so bash-specific syntax works.
if [ -z "${BASH:-}" ] || [ "${BASH##*/}" = "sh" ]; then
    exec bash "$0" "$@"
fi

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PID=""
FRONTEND_PID=""
DEBUG_MODE=true
OPEN_BROWSER=true

open_app_url() {
    local url="$1"
    if command -v open >/dev/null 2>&1; then
        open "$url"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 &
    fi
}

show_help() {
    echo -e "${BLUE}Heym - AI Workflow Platform${NC}"
    echo ""
    echo "Usage: ./run.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --no-debug     Disable debug logging (default: debug enabled)"
    echo "  --no-open      Do not open the frontend URL in a browser after startup"
    echo "                 (env: HEYM_RUN_NO_OPEN=1 has the same effect)"
    echo "  -h, --help     Show this help message"
    echo ""
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-debug)
            DEBUG_MODE=false
            shift
            ;;
        --no-open)
            OPEN_BROWSER=false
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

cleanup() {
    echo -e "\n${YELLOW}Shutting down services...${NC}"
    if [ -n "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    if [ -n "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    echo -e "${GREEN}Services stopped.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

check_command() {
    if ! command -v $1 &> /dev/null; then
        echo -e "${RED}Error: $1 is not installed${NC}"
        exit 1
    fi
}

kill_port() {
    local port=$1
    local pid=$(lsof -ti:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        echo -e "${YELLOW}Killing process on port $port (PID: $pid)...${NC}"
        kill -9 $pid 2>/dev/null || true
        sleep 1
    fi
}

VERSION=$(cat "$PROJECT_ROOT/VERSION" 2>/dev/null)

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Heym - AI Workflow Platform${NC}"
echo -e "${BLUE}   Version: $VERSION${NC}"
echo -e "${BLUE}========================================${NC}"

echo -e "\n${YELLOW}Checking prerequisites...${NC}"
check_command "docker"
check_command "bun"
check_command "uv"
echo -e "${GREEN}All prerequisites found.${NC}"

# Codex CLI is only needed by the Codex node. Auto-install it (best-effort) when missing.
if ! command -v codex &> /dev/null; then
    if command -v npm &> /dev/null; then
        echo -e "${YELLOW}Installing Codex CLI (@openai/codex) for the Codex node...${NC}"
        if npm install -g @openai/codex >/dev/null 2>&1; then
            echo -e "${GREEN}Codex CLI installed.${NC}"
        else
            echo -e "${YELLOW}Could not auto-install Codex CLI (npm global install failed — may need sudo). Install manually: npm install -g @openai/codex (or set HEYM_CODEX_CLI_COMMAND).${NC}"
        fi
    else
        echo -e "${YELLOW}Note: 'codex' CLI and npm not found. The Codex node needs '@openai/codex' — install Node/npm, then 'npm install -g @openai/codex'.${NC}"
    fi
fi

ENV_FILE="$PROJECT_ROOT/.env"
ENCRYPTION_KEY_PLACEHOLDER="change_this_to_a_random_32_byte_hex_value"

backfill_secret_key() {
    # Populate SECRET_KEY only when it is empty. Safe for both new and existing
    # .env files: an empty SECRET_KEY has never signed a token worth preserving.
    if grep -q '^SECRET_KEY=$' "$ENV_FILE" 2>/dev/null; then
        local generated
        generated=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
        sed -i.bak "s|^SECRET_KEY=$|SECRET_KEY=${generated}|" "$ENV_FILE"
        rm -f "$ENV_FILE.bak"
        echo -e "${GREEN}Generated random SECRET_KEY${NC}"
    fi
}

backfill_encryption_key() {
    # Populate ENCRYPTION_KEY only when it is empty. Safe for both new and existing
    # .env files: no data could have been encrypted with an empty key.
    # If the legacy placeholder is present, fail loudly — overwriting would make
    # previously-encrypted credentials unreadable (InvalidToken).
    if grep -q "^ENCRYPTION_KEY=${ENCRYPTION_KEY_PLACEHOLDER}\$" "$ENV_FILE" 2>/dev/null; then
        echo -e "${RED}Error: ENCRYPTION_KEY is set to the legacy placeholder value.${NC}"
        echo -e "${YELLOW}Generate a new key and set it in .env:${NC}"
        echo -e "  python3 -c 'import secrets; print(secrets.token_hex(32))'"
        echo -e "${RED}Do NOT auto-generate over an existing placeholder — data encrypted with the old key would be lost.${NC}"
        exit 1
    fi
    if grep -q '^ENCRYPTION_KEY=$' "$ENV_FILE" 2>/dev/null; then
        local generated
        generated=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
        sed -i.bak "s|^ENCRYPTION_KEY=$|ENCRYPTION_KEY=${generated}|" "$ENV_FILE"
        rm -f "$ENV_FILE.bak"
        echo -e "${GREEN}Generated random ENCRYPTION_KEY${NC}"
    fi
}

if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}Creating .env from .env.example...${NC}"
    cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
fi

# Backfill both keys in all cases: empty SECRET_KEY and empty ENCRYPTION_KEY are
# safe to generate regardless of whether .env is new or pre-existing. The legacy
# placeholder ENCRYPTION_KEY triggers an explicit error instead of silent rotation.
backfill_secret_key
backfill_encryption_key

set -a
source "$PROJECT_ROOT/.env"
set +a

if [ -n "${TIMEZONE:-}" ] && [ -z "${TZ:-}" ]; then
    export TZ="$TIMEZONE"
elif [ -n "${TZ:-}" ] && [ -z "${TIMEZONE:-}" ]; then
    export TIMEZONE="$TZ"
elif [ -z "${TIMEZONE:-}" ] && [ -z "${TZ:-}" ]; then
    export TIMEZONE="Europe/Berlin"
    export TZ="$TIMEZONE"
fi

echo -e "${BLUE}Timezone:${NC} ${TIMEZONE:-$TZ}"

echo -e "\n${YELLOW}Starting PostgreSQL on port 6543...${NC}"
if docker ps -a --format '{{.Names}}' | grep -q '^heym-postgres$'; then
    if docker ps --format '{{.Names}}' | grep -q '^heym-postgres$'; then
        echo -e "${GREEN}PostgreSQL is already running.${NC}"
    else
        docker start heym-postgres
        echo -e "${GREEN}PostgreSQL started.${NC}"
    fi
else
    docker run --name heym-postgres \
        -e POSTGRES_USER=${POSTGRES_USER:-postgres} \
        -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-postgres} \
        -e POSTGRES_DB=${POSTGRES_DB:-heym} \
        -p 6543:5432 \
        -d postgres:16
    echo -e "${GREEN}PostgreSQL container created and started.${NC}"
fi

sleep 2

# Enable the pgvector extension on the stock postgres:16 image (opt-in Postgres
# RAG backend). We keep the official postgres:16 image untouched — so existing
# data dirs and their collation are never changed — and just add the extension
# package at runtime. Non-fatal: if it cannot be installed (e.g. no network),
# Qdrant RAG keeps working and the migration skips the pgvector table.
ensure_pgvector() {
    if docker exec heym-postgres sh -c "dpkg -s postgresql-16-pgvector >/dev/null 2>&1"; then
        return 0
    fi
    echo -e "${YELLOW}Installing pgvector extension into PostgreSQL...${NC}"
    docker exec -u root heym-postgres sh -c \
        "apt-get update -qq && apt-get install -y -qq --no-install-recommends postgresql-16-pgvector" \
        >/dev/null 2>&1 \
        && echo -e "${GREEN}pgvector installed.${NC}" \
        || echo -e "${YELLOW}pgvector install skipped (Qdrant RAG still works).${NC}"
}
ensure_pgvector

echo -e "\n${YELLOW}Setting up backend...${NC}"
cd "$PROJECT_ROOT/backend"
uv sync
echo -e "${GREEN}Backend dependencies installed.${NC}"

echo -e "\n${YELLOW}Running database migrations...${NC}"
uv run python -m alembic upgrade head
echo -e "${GREEN}Migrations complete.${NC}"

echo -e "\n${YELLOW}Cleaning up existing ports...${NC}"
kill_port ${BACKEND_PORT:-10105}
kill_port ${FRONTEND_PORT:-4017}
echo -e "${GREEN}Ports cleared.${NC}"

# User-defined Python tools run as untrusted code. The Docker sandbox needs a
# resolvable backend image, which native (non-container) dev runs don't have.
# When the sandbox is left at the default "auto" with no explicit image, default
# native dev to the subprocess fallback so tools keep working. Setting
# HEYM_PYTHON_TOOL_SANDBOX or HEYM_PYTHON_TOOL_IMAGE explicitly overrides this.
if [ "${HEYM_PYTHON_TOOL_SANDBOX:-auto}" = "auto" ] && [ -z "${HEYM_PYTHON_TOOL_IMAGE:-}" ]; then
    export HEYM_PYTHON_TOOL_SANDBOX=subprocess
fi

echo -e "\n${YELLOW}Starting backend on port ${BACKEND_PORT:-10105}...${NC}"
if [ "$DEBUG_MODE" = true ]; then
    echo -e "${BLUE}Debug mode enabled - showing DEBUG level logs${NC}"
    # Only watch app/ for reload — codex writes many files under data/codex-workspaces which
    # would otherwise restart the server mid-execution and kill the Codex subprocess.
    LOG_LEVEL=DEBUG uv run python -m uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-10105} --reload --reload-dir app --log-level debug &
else
    uv run python -m uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-10105} --reload --reload-dir app &
fi
BACKEND_PID=$!
sleep 2

echo -e "\n${YELLOW}Setting up frontend...${NC}"
cd "$PROJECT_ROOT/frontend"
bun install
echo -e "${GREEN}Frontend dependencies installed.${NC}"

echo -e "\n${YELLOW}Starting frontend on port ${FRONTEND_PORT:-4017}...${NC}"
bun run dev &
FRONTEND_PID=$!

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}   Services Running${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${BLUE}Frontend:${NC}  http://localhost:${FRONTEND_PORT:-4017}"
echo -e "${BLUE}Backend:${NC}   http://localhost:${BACKEND_PORT:-10105}"
echo -e "${BLUE}API Docs:${NC}  http://localhost:${BACKEND_PORT:-10105}/docs"
echo -e "${BLUE}Database:${NC}  localhost:6543"
if [ "$DEBUG_MODE" = true ]; then
    echo -e "${YELLOW}Log Level:${NC} DEBUG"
fi
echo -e "${GREEN}========================================${NC}"
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}\n"

if [ "$OPEN_BROWSER" = true ] && [ -z "${HEYM_RUN_NO_OPEN:-}" ]; then
    FE_URL="http://localhost:${FRONTEND_PORT:-4017}"
    (
        sleep 3
        open_app_url "$FE_URL"
    ) &
fi

wait
