# Heym on Kubernetes

Example manifests for running Heym without a Docker socket. Every sandbox (Python
tools, skills, the Code node, file analysis, Playwright, MCP stdio, Codex, OpenCode)
runs as its own pod through the Kubernetes API.

## Requirements

- Kubernetes 1.30 or newer (sandbox stdin uses the `v5.channel.k8s.io` attach protocol).
- A CNI that enforces NetworkPolicy. Heym checks this before the first offline
  sandbox and refuses to run offline sandboxes when a test pod can still connect.
- A kubelet `podPidsLimit`. Pods have no per-pod PID limit field, so this is the only
  fork-bomb guard besides memory, CPU and the deadline.

## Install

    kubectl apply -k deploy/kubernetes/base
    kubectl -n heym create secret generic heym-secrets \
      --from-literal=DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/heym \
      --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
      --from-literal=ENCRYPTION_KEY=$(openssl rand -hex 32)

## Storage

`heym-data` holds Drive files, plugins and the Codex/OpenCode workspaces. Sandbox
pods mount one subPath of it per run. With `ReadWriteMany` they can run on any node.
With `ReadWriteOnce` they are pinned to the backend's node. `ReadWriteOncePod` does
not work.

## A dedicated sandbox namespace

Set `HEYM_SANDBOX_K8S_NAMESPACE` to run sandboxes elsewhere, label that namespace
`pod-security.kubernetes.io/enforce: restricted`, move the Role there, and keep a
Role in Heym's namespace that grants `get` on `pods`. Workspace sandboxes then need
a claim named `heym-data` in the sandbox namespace bound to the same RWX share
(a second, statically provisioned PersistentVolume).

## Scheduling

`HEYM_SANDBOX_K8S_POD_OVERRIDES` takes JSON with `nodeSelector`, `tolerations`,
`runtimeClassName` (for example gVisor), `imagePullSecrets` and `priorityClassName`.
Nothing else is accepted.

## Local test on OrbStack

    docker compose build backend
    kubectl --context orbstack apply -k deploy/kubernetes/overlays/orbstack
    kubectl --context orbstack -n heym create secret generic heym-secrets \
      --from-literal=DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/heym \
      --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
      --from-literal=ENCRYPTION_KEY=$(openssl rand -hex 32)
    ./scripts/k8s-sandbox-smoke.sh
