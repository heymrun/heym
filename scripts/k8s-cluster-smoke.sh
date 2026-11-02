#!/usr/bin/env bash
# Load distribution on Kubernetes: main plus a worker, each running its own sandbox pods.
# Usage: scripts/k8s-cluster-smoke.sh [context]
# Deploy first: kubectl apply -k deploy/kubernetes/overlays/orbstack-cluster (plus heym-secrets).
set -euo pipefail
CONTEXT="${1:-orbstack}"
HERE="$(cd "$(dirname "$0")" && pwd)"
k() { kubectl --context "$CONTEXT" -n heym "$@"; }

k rollout status deploy/heym --timeout=300s
k rollout status deploy/heym-worker --timeout=300s
POD="$(k get pod -l app.kubernetes.io/name=heym -o jsonpath='{.items[0].metadata.name}')"
k exec -i "$POD" -- sh -c '
  for py in /app/.venv/bin/python /app/backend/.venv/bin/python; do
    if [ -x "$py" ]; then cd "$(dirname "$(dirname "$(dirname "$py")")")" && exec "$py" -; fi
  done
  echo "backend virtualenv not found" >&2; exit 127
' < "$HERE/k8s_cluster_smoke.py"

WORKER="$(k get pod -l app.kubernetes.io/name=heym-worker -o jsonpath='{.items[0].metadata.name}')"
echo "Sandbox smoke from inside the worker pod $WORKER:"
k exec -i "$WORKER" -- sh -c 'cd /app && exec /app/.venv/bin/python -' < "$HERE/sandbox_smoke.py"

sleep 2
LEFT="$(kubectl --context "$CONTEXT" get pods -A -l app.kubernetes.io/managed-by=heym --no-headers 2>/dev/null | wc -l | tr -d ' ')"
if [ "$LEFT" != "0" ]; then
  echo "FAIL: $LEFT sandbox pods left behind"
  exit 1
fi
echo "OK: no sandbox pods left behind"
