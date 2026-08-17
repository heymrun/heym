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
    echo "  --down              Stop and remove containers"
    echo "  --logs              View container logs"
    echo "  --restart           Restart all services"
    echo "  --status            Show container status"
    echo "  --migrate-pgdata    Copy a pre-existing data/postgres directory into the"
    echo "                      heym-postgres-data Docker volume, then rebuild indexes"
    echo "                      (one-time migration). Add --skip-reindex to skip the"
    echo "                      rebuild on a large, known-healthy database."
    echo "  --help              Show this help message"
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

# PostgreSQL storage moved from the ./data/postgres bind mount to a Docker named
# volume: bind mounts on macOS (virtiofs) and Windows/WSL2 do not honour the fsync
# and close guarantees PostgreSQL needs, which corrupts the cluster over time.
PG_VOLUME="heym-postgres-data"
LEGACY_PGDATA="$PROJECT_ROOT/data/postgres"
SKIP_REINDEX=false

# PG_VERSION, not the directory: Docker auto-creates an empty bind-mount source,
# so the directory alone proves nothing.
legacy_pgdata_present() {
    [ -f "$LEGACY_PGDATA/PG_VERSION" ]
}

volume_has_pgdata() {
    docker volume inspect "$PG_VOLUME" >/dev/null 2>&1 || return 1
    docker run --rm --entrypoint test -v "$PG_VOLUME:/v" postgres:16 -f /v/PG_VERSION >/dev/null 2>&1
}

# Fail before the build rather than letting the postgres container's own guard trip
# after several minutes of `docker build --no-cache`.
assert_pgdata_migrated() {
    legacy_pgdata_present || return 0
    volume_has_pgdata && return 0

    echo -e "${RED}Existing database found at data/postgres, but the ${PG_VOLUME} volume is empty.${NC}"
    echo ""
    echo -e "${YELLOW}Heym now stores PostgreSQL in a Docker named volume. Host bind mounts on${NC}"
    echo -e "${YELLOW}macOS (virtiofs) and Windows/WSL2 do not give PostgreSQL the fsync guarantees${NC}"
    echo -e "${YELLOW}it requires and corrupt the cluster over time.${NC}"
    echo ""
    echo -e "Copy your database into the named volume, then deploy again:"
    echo -e "  ${BLUE}./deploy.sh --migrate-pgdata${NC}"
    echo ""
    echo -e "${RED}Deploying now would initialise an empty database and lose your workflows.${NC}"
    exit 1
}

# The copy above is byte-for-byte, so any index damage the bind mount caused travels
# with it. Rebuilding indexes on the new volume is the point of the exercise: a
# virtiofs-corrupted cluster typically carries index entries pointing past the end of
# the heap, which a clean pg_amcheck does not detect.
#
# Runs through the compose postgres service, not a bare postgres:16 container: that
# entrypoint installs pgvector at start, and an index built on the vector opclass
# cannot be rebuilt without $libdir/vector. Only postgres comes up, so the app stays
# down until the cluster is known good.
reindex_pgdata() {
    local pg_user="$1" pg_db="$2"

    dc up -d postgres

    # The entrypoint installs the pgvector package before Postgres boots, so this can
    # take noticeably longer than starting a plain postgres container.
    local ready=false
    for _ in {1..120}; do
        if dc exec -T postgres pg_isready -U "$pg_user" >/dev/null 2>&1; then
            ready=true
            break
        fi
        sleep 1
    done

    # Any failure below removes the volume. The guard treats a non-empty volume as
    # "migrated", so a half-repaired cluster must never be left behind to be deployed.
    if [ "$ready" != "true" ]; then
        echo -e "${RED}The migrated cluster did not accept connections. Last log lines:${NC}"
        dc logs --tail 20 postgres 2>&1 || true
        dc down
        docker volume rm "$PG_VOLUME" >/dev/null 2>&1 || true
        echo -e "${RED}Volume removed. data/postgres is untouched — investigate before retrying.${NC}"
        exit 1
    fi

    if ! dc exec -T postgres reindexdb -U "$pg_user" -d "$pg_db"; then
        dc down
        docker volume rm "$PG_VOLUME" >/dev/null 2>&1 || true
        echo -e "${RED}REINDEX failed. Volume removed; data/postgres is untouched.${NC}"
        exit 1
    fi

    # Clean shutdown, so the first real start does not begin with crash recovery.
    dc stop -t 60 postgres
}

# Copy (never move) the legacy cluster into the named volume. The source is left
# untouched so a failed migration is always recoverable.
migrate_pgdata() {
    if ! legacy_pgdata_present; then
        echo -e "${GREEN}Nothing to migrate: no PostgreSQL data directory at data/postgres.${NC}"
        exit 0
    fi
    if volume_has_pgdata; then
        echo -e "${RED}Volume ${PG_VOLUME} already contains a database. Refusing to overwrite it.${NC}"
        echo -e "${YELLOW}Remove the volume first if you really want to re-import data/postgres:${NC}"
        echo -e "  docker volume rm ${PG_VOLUME}"
        exit 1
    fi

    # Read POSTGRES_* for the reindex step. Deliberately not prepare_env: a migration
    # has no business generating keys or rewriting .env.
    if [ -f "$ENV_FILE" ]; then
        source "$ENV_FILE"
    fi
    local pg_user="${POSTGRES_USER:-postgres}"
    local pg_db="${POSTGRES_DB:-heym}"

    echo -e "${YELLOW}Stopping services so the database is not written to during the copy...${NC}"
    dc down

    echo -e "${YELLOW}Copying data/postgres into the ${PG_VOLUME} volume...${NC}"
    dc up --no-start postgres >/dev/null 2>&1 || docker volume create "$PG_VOLUME" >/dev/null
    if ! docker run --rm \
        -v "$LEGACY_PGDATA:/legacy:ro" \
        -v "$PG_VOLUME:/pgdata" \
        --entrypoint sh postgres:16 -c 'cp -a /legacy/. /pgdata/'; then
        docker volume rm "$PG_VOLUME" >/dev/null 2>&1 || true
        echo -e "${RED}Copy failed. Volume removed; data/postgres is unchanged.${NC}"
        exit 1
    fi

    if [ "$SKIP_REINDEX" = "true" ]; then
        echo -e "${YELLOW}Skipping REINDEX (--skip-reindex).${NC}"
        echo -e "${YELLOW}Index damage caused by the old bind mount, if any, was copied along.${NC}"
    else
        echo -e "${YELLOW}Rebuilding indexes on the migrated cluster (database: ${pg_db})...${NC}"
        echo -e "${YELLOW}This can take a while on a large database. Use --skip-reindex to bypass.${NC}"
        reindex_pgdata "$pg_user" "$pg_db"
        echo -e "${GREEN}Indexes rebuilt.${NC}"
    fi

    echo -e "${GREEN}Migration complete. data/postgres was left in place as a backup.${NC}"
    echo -e "Start the stack with: ${BLUE}./deploy.sh${NC}"
    echo -e "Once you have confirmed your data is intact, you may delete data/postgres."
    echo ""
    echo -e "${YELLOW}Note: REINDEX repairs index entries that point at missing heap rows.${NC}"
    echo -e "${YELLOW}It cannot bring back heap pages the old filesystem already lost.${NC}"
    exit 0
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
    --migrate-pgdata)
        if [ "${2:-}" = "--skip-reindex" ]; then
            SKIP_REINDEX=true
        elif [ -n "${2:-}" ]; then
            echo -e "${RED}Unknown option for --migrate-pgdata: $2${NC}"
            exit 1
        fi
        migrate_pgdata
        ;;
    --restart)
        prepare_env
        assert_pgdata_migrated
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
        assert_pgdata_migrated
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