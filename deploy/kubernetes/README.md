# Heym on Kubernetes

Deploy Heym on Kubernetes without a Docker socket. Run every sandbox as its own pod, with guides for storage, networking, and workers.

Example manifests for running Heym without a Docker socket. Every sandbox (Python
tools, skills, the Code node, file analysis, Playwright, MCP stdio, Codex, OpenCode)
runs as its own pod through the Kubernetes API.

## Requirements

- Kubernetes 1.30 or newer (sandbox stdin uses the `v5.channel.k8s.io` attach protocol).
- A CNI that enforces NetworkPolicy. Heym checks this before the first offline
  sandbox and refuses to run offline sandboxes when a test pod can still connect.
- A kubelet `podPidsLimit`. Pods have no per-pod PID limit field, so this is the only
  fork-bomb guard besides memory, CPU and the deadline. Heym cannot check it: a
  container's `/sys/fs/cgroup/pids.max` is its own cgroup's, not the pod's. Talos
  ships without one.

## Install

    kubectl apply -k deploy/kubernetes/base
    kubectl -n heym create secret generic heym-secrets \
      --from-literal=DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/heym \
      --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
      --from-literal=ENCRYPTION_KEY=$(openssl rand -hex 32)

## Helm

[heym-helm](https://github.com/amasolov/heym-helm) is a community chart maintained by
Alexey Masolov and published on
[Artifact Hub](https://artifacthub.io/packages/helm/heym/heym), with platform presets for
OpenShift, EKS, AKS and GKE:

    helm install heym oci://ghcr.io/amasolov/charts/heym -n heym --create-namespace -f values.yaml

## Storage

`heym-data` holds Drive files, plugins and the Codex/OpenCode workspaces. Sandbox
pods mount one subPath of it per run. With `ReadWriteMany` they can run on any node.
With `ReadWriteOnce` they are pinned to the backend's node. `ReadWriteOncePod` does
not work.

## Custom CA bundles

Mount your CA bundle into the backend pod and point `SSL_CERT_FILE` (or
`REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`) at it. Heym copies the file to
`codex-workspaces/_ca/` on the claim and mounts that copy read-only at the same
path in every sandbox that receives the variable. With a `ReadWriteOnce` claim,
those sandboxes run on the backend's node.

A CA does not open the network. Sandbox egress reaches public addresses only, so an
internal package mirror, proxy or API needs its own rule, for example:

    apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata:
      name: heym-sandbox-egress-internal-mirror
    spec:
      podSelector:
        matchLabels:
          app.kubernetes.io/managed-by: heym
          heym.run/network: egress
      policyTypes: [Egress]
      egress:
        - to:
            - ipBlock: {cidr: 10.20.30.40/32}
          ports:
            - {protocol: TCP, port: 443}

## A dedicated sandbox namespace

Set `HEYM_SANDBOX_K8S_NAMESPACE` to run sandboxes elsewhere, label that namespace
`pod-security.kubernetes.io/enforce: restricted`, move the Role there, and keep a
Role in Heym's namespace that grants `get` on `pods`. Workspace sandboxes then need
a claim named `heym-data` in the sandbox namespace bound to the same RWX share
(a second, statically provisioned PersistentVolume).

## OpenShift

    kubectl apply -k deploy/kubernetes/overlays/openshift

OVN-Kubernetes evaluates egress policy after the DNS Service is translated to a DNS
pod, and OpenShift's DNS pods listen on 5353, not 53. With the base policy, networked
sandboxes reach the internet by IP but every name lookup times out. The overlay
changes only that rule:

- It allows UDP and TCP 5353, the DNS pods' port, not the Service's 53.
- It selects the DNS namespace by `kubernetes.io/metadata.name: openshift-dns`.
  `network.openshift.io/policy-group: dns` is not set on every cluster.
- The public `ipBlock` rule keeps excluding private, link-local and CGNAT ranges.

## Cilium with kube-proxy replacement

The base gives the backend pod no egress policy. If you add one, a plain `ipBlock`
cannot allow the API server: the Service address is rewritten to a node's `:6443`
before policy applies, and that address carries Cilium's `kube-apiserver` identity.
Allow it with a `CiliumNetworkPolicy`. It also selects workers, which start sandbox
pods too (see Load distribution):

    apiVersion: cilium.io/v2
    kind: CiliumNetworkPolicy
    metadata:
      name: heym-kube-apiserver
    spec:
      endpointSelector:
        matchExpressions:
          - key: app.kubernetes.io/name
            operator: In
            values: [heym, heym-worker]
      egress:
        - toEntities: [kube-apiserver]
          toPorts:
            - ports: [{port: "6443", protocol: TCP}]

## Scheduling

`HEYM_SANDBOX_K8S_POD_OVERRIDES` takes JSON with `nodeSelector`, `tolerations`,
`runtimeClassName` (for example gVisor), `imagePullSecrets` and `priorityClassName`.
Nothing else is accepted.

## Load distribution

Workers are more Deployments of the same image with `HEYM_INSTANCE_ROLE=worker`, the
same `SECRET_KEY` and `ENCRYPTION_KEY`, and the `heym-backend` ServiceAccount, so they
can start sandbox pods too. A worker runs the Code node, so it needs a claim at the
workspace directory for Code node dependencies: its own `ReadWriteOnce` claim works,
because those directories only live for one run. `overlays/orbstack-cluster` adds one
worker; `scripts/k8s-cluster-smoke.sh` checks that queued runs land on it and that
their sandbox pods are the worker's.

Start workers with uvicorn directly, as `overlays/orbstack-cluster/worker.yaml` does.
The image entrypoint runs database migrations, and those belong to main. Give each
worker a unique, stable `HEYM_INSTANCE_ID`; a StatefulSet pod name works. Runs queued
for a worker that stops are moved to another instance by the leader.

## Local test on OrbStack

    docker compose build backend
    kubectl --context orbstack apply -k deploy/kubernetes/overlays/orbstack
    kubectl --context orbstack -n heym create secret generic heym-secrets \
      --from-literal=DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/heym \
      --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
      --from-literal=ENCRYPTION_KEY=$(openssl rand -hex 32)
    ./scripts/k8s-sandbox-smoke.sh

For main plus a worker, apply `overlays/orbstack-cluster` instead and run
`./scripts/k8s-cluster-smoke.sh`.
