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

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    echo -e "${YELLOW}Run: cp .env.example .env${NC}"
    exit 1
fi

source "$PROJECT_ROOT/.env"

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
        echo -e "${YELLOW}Restarting services...${NC}"
        dc restart
        ;;
    --status)
        dc ps
        exit 0
        ;;
    "")
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