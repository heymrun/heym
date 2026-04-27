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

show_help() {
    echo -e "${BLUE}Heym - AI Workflow Platform${NC}"
    echo ""
    echo "Usage: ./run.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --no-debug     Disable debug logging (default: debug enabled)"
    echo "  -h, --help     Show this help message"
    echo ""
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-debug)
            DEBUG_MODE=false
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

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${YELLOW}Creating .env from .env.example...${NC}"
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
fi

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

echo -e "\n${YELLOW}Starting backend on port ${BACKEND_PORT:-10105}...${NC}"
if [ "$DEBUG_MODE" = true ]; then
    echo -e "${BLUE}Debug mode enabled - showing DEBUG level logs${NC}"
    LOG_LEVEL=DEBUG uv run python -m uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-10105} --reload --log-level debug &
else
    uv run python -m uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-10105} --reload &
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

wait
