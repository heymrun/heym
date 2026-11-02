#!/usr/bin/env bash
# Docker smoke test of every sandbox, from a backend container wired like docker-compose.yml:
# the Docker socket, the two workspace volumes and the image variables.
# Usage: scripts/docker-sandbox-smoke.sh [image]   (build it first: docker compose build backend)
set -euo pipefail
IMAGE="${1:-heym-backend:local}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SECRET="smoke-test-only-secret-key-0123456789abcdef"

docker volume create heym-sandbox-smoke-codex >/dev/null
docker volume create heym-sandbox-smoke-opencode >/dev/null
cleanup() { docker volume rm heym-sandbox-smoke-codex heym-sandbox-smoke-opencode >/dev/null 2>&1 || true; }
trap cleanup EXIT

status=0
docker run --rm -i \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v heym-sandbox-smoke-codex:/app/data/codex-workspaces \
  -v heym-sandbox-smoke-opencode:/app/data/opencode-workspaces \
  -e SECRET_KEY="$SECRET" -e ENCRYPTION_KEY="$SECRET" \
  -e HEYM_CODEX_WORKSPACE_DIR=/app/data/codex-workspaces \
  -e HEYM_CODEX_DOCKER_WORKSPACE_VOLUME=heym-sandbox-smoke-codex \
  -e HEYM_OPENCODE_WORKSPACE_DIR=/app/data/opencode-workspaces \
  -e HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME=heym-sandbox-smoke-opencode \
  -e HEYM_CODEX_DOCKER_IMAGE="$IMAGE" -e HEYM_OPENCODE_DOCKER_IMAGE="$IMAGE" \
  -e HEYM_PYTHON_TOOL_IMAGE="$IMAGE" -e HEYM_SKILL_IMAGE="$IMAGE" \
  -e HEYM_PLAYWRIGHT_SANDBOX_IMAGE="$IMAGE" -e HEYM_MCP_STDIO_IMAGE="$IMAGE" \
  --entrypoint sh "$IMAGE" -c 'cd /app && exec /app/.venv/bin/python -' \
  < "$HERE/sandbox_smoke.py" || status=$?

LEFT="$(docker ps -aq --filter name=heym-pytool- --filter name=heym-code- \
  --filter name=heym-files- --filter name=heym-skill- --filter name=heym-pw- \
  --filter name=heym-mcp-stdio- --filter name=heym-codex- --filter name=heym-opencode- | wc -l | tr -d ' ')"
if [ "$LEFT" != "0" ]; then
  echo "FAIL: $LEFT sandbox containers left behind"
  exit 1
fi
echo "OK: no sandbox containers left behind"
exit "$status"
