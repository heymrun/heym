#!/usr/bin/env bash
# In-cluster smoke test of every sandbox site. Usage: scripts/k8s-sandbox-smoke.sh [context]
set -euo pipefail
CONTEXT="${1:-orbstack}"
HERE="$(cd "$(dirname "$0")" && pwd)"
k() { kubectl --context "$CONTEXT" -n heym "$@"; }

k rollout status deploy/heym --timeout=300s
POD="$(k get pod -l app.kubernetes.io/name=heym -o jsonpath='{.items[0].metadata.name}')"
k exec -i "$POD" -- sh -c '
  for py in /app/.venv/bin/python /app/backend/.venv/bin/python; do
    if [ -x "$py" ]; then cd "$(dirname "$(dirname "$(dirname "$py")")")" && exec "$py" -; fi
  done
  echo "backend virtualenv not found" >&2; exit 127
' < "$HERE/k8s_sandbox_smoke.py"

sleep 2
LEFT="$(kubectl --context "$CONTEXT" get pods -A -l app.kubernetes.io/managed-by=heym --no-headers 2>/dev/null | wc -l | tr -d ' ')"
if [ "$LEFT" != "0" ]; then
  echo "FAIL: $LEFT sandbox pods left behind"
  kubectl --context "$CONTEXT" get pods -A -l app.kubernetes.io/managed-by=heym
  exit 1
fi
echo "OK: no sandbox pods left behind"
