#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

show_help() {
    echo -e "${BLUE}Heym Deployment Script${NC}"
    echo ""
    echo "Usage: ./deploy.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --down      Stop and remove containers"
    echo "  --logs      View container logs"
    echo "  --restart   Restart all services"
    echo "  --status    Show container status"
    echo "  --help      Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh           # Build and deploy"
    echo "  ./deploy.sh --logs    # View logs"
    echo "  ./deploy.sh --down    # Stop services"
}

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
        SECRET_KEY_WAS_GENERATED=true
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

# Prepare .env and load it. Only invoked for subcommands that actually deploy;
# read-only subcommands (--help, --logs, --status, --down) must never mutate .env.
prepare_env() {
    SECRET_KEY_WAS_GENERATED=false

    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${YELLOW}Creating .env from .env.example...${NC}"
        cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
    fi

    # Host dirs for the docker-compose bind mounts (files + installed plugins).
    # Plugins persist here across container recreates; their pip dependencies are
    # reinstalled into the backend container on startup (see app startup).
    mkdir -p "$PROJECT_ROOT/data/files" "$PROJECT_ROOT/data/plugins"

    # Backfill both keys in all cases: empty SECRET_KEY and empty ENCRYPTION_KEY are
    # safe to generate regardless of whether .env is new or pre-existing. The legacy
    # placeholder ENCRYPTION_KEY triggers an explicit error instead of silent rotation.
    backfill_secret_key
    backfill_encryption_key

    source "$ENV_FILE"
}

VERSION=$(cat "$PROJECT_ROOT/VERSION" 2>/dev/null)

cd "$PROJECT_ROOT"

dc() {
    if command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        docker compose "$@"
    fi
}

case "${1:-}" in
    --help|-h)
        show_help
        exit 0
        ;;
    --down)
        echo -e "${YELLOW}Stopping services...${NC}"
        dc down
        echo -e "${GREEN}Services stopped.${NC}"
        exit 0
        ;;
    --logs)
        dc logs -f
        exit 0
        ;;
    --restart)
        prepare_env
        echo -e "${YELLOW}Restarting services...${NC}"
        if [ "$SECRET_KEY_WAS_GENERATED" = "true" ]; then
            # dc restart does not propagate new env vars to existing containers.
            # A new SECRET_KEY was just written to .env — recreate containers to pick it up.
            echo -e "${YELLOW}New SECRET_KEY generated — recreating containers to propagate environment...${NC}"
            dc up -d
        else
            dc restart
        fi
        ;;
    --status)
        dc ps
        exit 0
        ;;
    "")
        prepare_env
        # Zero-downtime deploy: build first (containers keep running), then swap
        echo -e "${YELLOW}Building Docker images v${VERSION} (containers stay up)...${NC}"
        if ! dc build --build-arg APP_VERSION=$VERSION --no-cache; then
            echo -e "${RED}Build failed. Existing containers unchanged.${NC}"
            exit 1
        fi
        echo -e "${YELLOW}Deploying Heym v${VERSION}...${NC}"
        dc up -d
        ;;
    *)
        echo -e "${RED}Unknown option: $1${NC}"
        show_help
        exit 1
        ;;
esac

echo -e "\n${YELLOW}Waiting for services to be healthy...${NC}"
sleep 5

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}   Deployment Complete - v${VERSION}${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${BLUE}Frontend:${NC}  http://localhost:${FRONTEND_PORT:-4017}"
echo -e "${BLUE}API:${NC}       http://localhost:${FRONTEND_PORT:-4017}/api"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "View logs: ${YELLOW}./deploy.sh --logs${NC}"
echo -e "Stop:      ${YELLOW}./deploy.sh --down${NC}"