# Sandbox Manager and Kubernetes Sandbox Backend

**Date:** 2026-11-02
**Status:** Design, awaiting review
**Issue:** [heymrun/heym#832](https://github.com/heymrun/heym/issues/832) (Kubernetes sandbox backend, no Docker socket)

## Problem

Every sandbox in Heym starts a sibling container through the `docker` CLI and
`/var/run/docker.sock`. Kubernetes nodes on Talos, Bottlerocket, containerd-only
EKS/AKS/GKE pools and OpenShift have no Docker daemon, and mounting a host socket
is either impossible or unacceptable. On those clusters the Code node, the file
sandbox, the formatter, Codex and OpenCode fail outright, and the Python tool,
skill, Playwright and MCP stdio paths only work with `subprocess`, which the docs
call trusted single-user only.

The maintainer reply on the issue commits to the shape of the fix: a Manager
class that owns execution, routes to today's Docker path in Docker environments,
and uses Kubernetes-native APIs for pod management when Heym runs in Kubernetes.

## Goal

1. One `SandboxManager` in `backend/app/services/sandbox/` that every sandbox call
   site goes through. It picks a backend once per process and exposes the same
   operations for both.
2. A `DockerBackend` that renders exactly the `docker run` argv each site renders
   today. Moving a site behind the manager changes no flag.
3. A `KubernetesBackend` that runs the same work as one Pod per call, under Pod
   Security `restricted`, with no ServiceAccount token, failing closed the same way
   the Docker path does.
4. All thirteen call sites work on Kubernetes, including the ones that need a
   workspace (skills, Code node dependencies, file sandbox, Codex, OpenCode).
5. A Codex or OpenCode run sees only its own workspace and home directory, on both
   backends. Today the Docker runners mount the whole workspace volume (see Findings).

Docker stays the default and keeps its behavior, except for goal 5, which is a
deliberate security fix. No schema change, migration, UI change or public API change.

## Decisions (made with the user, do not relitigate)

| Question | Decision |
|---|---|
| Kubernetes backend in-tree? | Yes, behind a Manager class (maintainer comment on #832). |
| How workspaces reach a pod | **Volume only.** The backend's own workspace PVC, one `subPath` per run. No tar streaming in v1. |
| Codex on Kubernetes | `--sandbox danger-full-access`; the pod is the boundary. Bubblewrap cannot run under `restricted`. |
| Deploy artifacts | Example manifests under `deploy/kubernetes/` (kustomize base plus an OrbStack overlay). No Helm chart in-tree. |
| Codex/OpenCode Docker wrappers mount the whole workspace volume | **Fix it here, on both backends.** Each run mounts only its workspace and home (see Coding-agent run scope). |
| Delivery | **One branch, one PR:** `impl/native-k8s-api-and-pod-management`. The phases below are milestones inside it, not separate PRs. |

Backend selection (`HEYM_SANDBOX_BACKEND=auto`, see the Manager section) follows the
maintainer comment's "when running in Kubernetes" and is this spec's proposal, open
to review.

## Non-goals

- Tar-over-attach ("stream") workspaces. Revisit only if a user without any
  shareable storage asks for it.
- A Helm chart. The issue author offered to maintain one as a community chart.
- A warm pod pool. Pod start costs about 3 s (measured below); accept it in v1.
- Changing the Codex Docker runner's privileges (see Findings).
- The Logs tab's Docker log viewer (`DockerLogsViewer.vue`, `docker_logs_enabled`).
  It reads the backend's own container logs and is unrelated to sandboxes.
- Changing node placement. Every instance in a cluster has its own sandbox
  backend, Docker socket or Kubernetes API, so `ANYWHERE` still holds.

## Current state (verified 2026-11-02)

### Call sites

The issue counted nine `docker run` builders. There are thirteen now: the file
sandbox (#842), the Code node with `codeFiles` and the Code node's install phase
came later.

| # | Site | Module | stdin/stdout | Network | Workspace | Mode switch |
|---|---|---|---|---|---|---|
| 1 | Agent Python tool | `python_tool_executor.py` | one-shot | `none` (env) | none | `HEYM_PYTHON_TOOL_SANDBOX` |
| 2 | Code formatter (Ruff) | `code_formatter.py` | one-shot | `none` | none | none, fails closed |
| 3 | Code node, no requirements | `code_python_executor.py` | one-shot | `none` or `bridge` | none | none, fails closed |
| 4 | Code node install phase | `code_python_executor.py` | one-shot | `bridge` | run dir rw | none, fails closed |
| 5 | Code node run with deps | `code_python_executor.py` | one-shot | `none` or `bridge` | run dir ro | none, fails closed |
| 6 | File sandbox | `file_sandbox/executor.py` | one-shot | `none` | `/input` ro, `/work` rw | none, fails closed |
| 7 | Custom Playwright | `playwright_sandbox.py` | one-shot | `bridge` | none | `HEYM_PLAYWRIGHT_SANDBOX` |
| 8 | Skill | `skill_python_executor.py` | one-shot | `bridge` | run dir rw | `HEYM_PYTHON_TOOL_SANDBOX` |
| 9 | MCP stdio, backend image | `mcp_stdio_sandbox.py` | long-lived process | `bridge` | optional operator mount | `HEYM_MCP_STDIO_SANDBOX` |
| 10 | MCP stdio, `docker run IMAGE` | `mcp_stdio_sandbox.py` | long-lived process | `bridge` | optional operator mount | `HEYM_MCP_STDIO_SANDBOX` |
| 11 | Codex | `docker/heym-codex-docker` | long-lived process | `bridge` | whole volume | `HEYM_CODEX_CLI_COMMAND` |
| 12 | OpenCode | `docker/heym-opencode-docker` | long-lived process | `bridge` | whole volume | `HEYM_OPENCODE_CLI_COMMAND` |
| 13 | Code node with `codeFiles` | `file_sandbox/code_node.py` | one-shot | `none` or `bridge` | `/input` ro, `/work` rw | none, fails closed |

Sites 2, 4, 5 and 6 reuse `hardening_args`, `resolve_mount`, `run_sandbox_container`
and `docker_available` from `code_python_executor.py`.

### Duplication

- `docker_available` / `_docker_available`: five copies (code, python tool, skill,
  Playwright, MCP stdio), plus a socket probe in `cluster/registry.py`.
- Image resolution through `docker inspect <hostname>`: five copies, each with its own
  env override order.
- `_force_remove_container`: five copies, plus `docker rm -f` in
  `opencode_runner_service.py`.
- Container mount inspection (`_current_container_mounts`): two copies in Python, two
  in the wrappers.
- Exit codes 125/126/127 ("container never started"): three copies.

### Measured on OrbStack Kubernetes (v1.36.5, docker runtime, `local-path` storage)

- **NetworkPolicy is enforced.** Without a policy a pod reached the API server and
  `1.1.1.1:443`; with a deny-all policy both were refused. `none` sandboxes are
  testable locally.
- **Attach works for our runners.** A pod running `heym-backend:local` as uid 65534,
  with read-only root, `drop: [ALL]`, `RuntimeDefault` seccomp and no SA token, got
  its JSON on stdin, saw EOF, returned stdout and stderr separately, and its exit code
  (3) reached the client.
- **Latency.** The `kubectl run -i --rm` round trip took 3.4 s, against under 1 s for
  `docker run`.
- `heym-backend:local` exists locally and the node uses the docker runtime, so pods
  can use the image with `imagePullPolicy: IfNotPresent` and no registry.

### Findings

- **Codex/OpenCode Docker runners see every workspace (in scope).** Both wrappers
  mount the whole workspace volume at the workspace root. Workspaces persist for
  resume (they stay at the root of the volume), and Codex's home with `auth.json`
  sits next to each one as `<id>.codex-home` (OpenCode uses `<id>.oc-home`). Codex's
  `workspace-write` sandbox limits writes but not reads, and OpenCode has no inner
  sandbox, so a prompt-injected run can read other users' repositories and Codex
  credentials. Fixed here on both backends; see Coding-agent run scope.
- **Codex Docker runner privileges (outside scope).** To let bubblewrap run, the
  Codex container gets `--cap-add SYS_ADMIN`, unconfined seccomp and AppArmor, and
  `systempaths=unconfined`. Codex's own sandbox is then the inner boundary and the
  container a weakened outer one. Run scoping still holds while bubblewrap holds.
  Whether Docker should switch to `danger-full-access` with a hardened container (the
  posture this spec uses on Kubernetes and OpenCode already uses) is a separate
  decision.

## Architecture

```
backend/app/services/sandbox/
  __init__.py          get_sandbox_manager()
  spec.py              SandboxSpec, Tmpfs, WorkspaceMount, OperatorMount, SandboxResult
  manager.py           SandboxManager: backend selection, availability, delegation
  errors.py            SandboxTimeoutError, SandboxConfigError
  env.py               shared env allowlists (the three prefix tuples that exist today)
  docker_backend.py    argv rendering, run, force_remove, self image, mount resolution
  coding_agents.py     RunScope + SandboxSpec for Codex and OpenCode (stdlib only)
  wrapper_cli.py       `python -m app.services.sandbox.wrapper_cli codex|opencode ...`
  kubernetes/
    client.py          minimal API client on httpx + websockets (sync)
    config.py          in-cluster config; kubeconfig only when the backend is forced
    pod.py             SandboxSpec -> Pod manifest (pure)
    backend.py         KubernetesBackend: run, process_argv, force_remove, availability
    attach.py          attach protocol (v5.channel.k8s.io) framing and pumps
    process.py         `python -m app.services.sandbox.kubernetes.process`: the bridge
    network.py         egress canary for `none` pods
    janitor.py         reaps leaked pods
    workspace.py       backend pod's mounts -> PVC claim + subPath
```

**Import rule.** Nothing under `app/services/sandbox/` imports `app.config`. The
bridge process runs with the MCP SDK's minimal environment (no `SECRET_KEY`), and the
module set should stay importable without settings, as the Heym Work import rule
already requires for other modules. A test asserts this.

### `SandboxSpec`

A frozen dataclass that describes one container run without naming a backend:

| Field | Meaning | Docker | Kubernetes |
|---|---|---|---|
| `site` | stable site id (`pytool`, `code-run`, `mcp-stdio`, ...) | unused | label `heym.run/sandbox` |
| `name` | container or pod name, DNS-1123, at most 63 chars | `--name` | `metadata.name` |
| `image`, `entrypoint`, `args` | what runs | `--entrypoint E IMAGE ARGS` | `command: [E]`, `args` |
| `network` | the raw Docker network string (`none`, `bridge`, a custom name) | `--network` | `none` gives label `heym.run/network: none`, anything else gives `egress` |
| `user` | `"65534:65534"` or `None` (image default) | `--user` | `runAsUser`/`runAsGroup`; `None` becomes 65534 on Kubernetes |
| `read_only_root` | bool | `--read-only` | `readOnlyRootFilesystem` |
| `tmpfs` | `Tmpfs(path, options, size)` | `--tmpfs path:options,size=` | `emptyDir{medium: Memory, sizeLimit}` |
| `shm_size` | optional | `--shm-size` | `emptyDir{medium: Memory}` at `/dev/shm` |
| `memory`, `memory_swap`, `cpus`, `pids` | limits; `memory_swap=None` omits the flag | the four flags | `limits.memory`, `limits.cpu`; pids has no pod field (see Gaps) |
| `cap_drop_all`, `no_new_privileges` | bool | `--cap-drop ALL`, `--security-opt no-new-privileges` | `capabilities.drop: [ALL]`, `allowPrivilegeEscalation: false` |
| `env` | ordered pairs | `--env K=V` in order | `env` in order |
| `workdir` | optional | `--workdir` | `workingDir` |
| `workspace_mounts` | `WorkspaceMount(host_path, target, readonly)` | existing `resolve_mount` logic | PVC `subPath` (see Workspaces) |
| `operator_mount` | MCP files mount (volume or host dir) | existing flags | PVC; host dir is refused |
| `deadline_seconds` | hard wall clock | unused | `activeDeadlineSeconds` |
| `start_gate` | wait for one byte on stdin before exec | unused | wraps the command (see Attach) |

`SandboxResult(returncode, stdout, stderr)` replaces the per-site checks: its
`start_failed` property is true for 125/126/127 and `oom_killed` for 137. The
Kubernetes backend reports a pod that never started as 125, so one check covers both
backends.

### `SandboxManager`

```python
class SandboxManager:
    backend_name: str                      # "docker" | "kubernetes" | "none"
    def available(self) -> bool
    def resolve_image(self, overrides: tuple[str, ...]) -> str | None
    def run(self, spec: SandboxSpec, stdin: str | None, timeout: float) -> SandboxResult
    def process_command(self, spec: SandboxSpec) -> ProcessCommand   # argv + env for a child process
    def force_remove(self, name: str | None) -> None
    def uses_shared_workspace(self) -> bool   # Docker: today's /.dockerenv rule; Kubernetes: always
```

- **Selection** happens once per process. `HEYM_SANDBOX_BACKEND`:
  - `auto` (default): `docker` when `docker version` answers; else `kubernetes` when
    in-cluster credentials exist (`KUBERNETES_SERVICE_HOST` plus the SA token file) and
    a SelfSubjectAccessReview allows `create pods` and `create pods/attach` in the
    sandbox namespace; else the Docker backend, which then reports itself unavailable.
  - `docker` or `kubernetes`: forced. A forced backend that is unreachable reports
    `available() == False`; it never falls back to the other one.
  - Today's behavior is the `auto` result on every existing Docker deployment,
    including Kubernetes clusters that mount a Docker socket.
- With neither backend reachable, every site fails closed with the message it has
  today. The Kubernetes backend logs why it is unavailable (version, RBAC, config).
- **Per-site mode variables keep their meaning.** `HEYM_PYTHON_TOOL_SANDBOX`,
  `HEYM_PLAYWRIGHT_SANDBOX` and `HEYM_MCP_STDIO_SANDBOX` still choose between a
  container sandbox (`auto`, `docker`) and `subprocess`. The value `docker` now reads
  as "container sandbox required, never subprocess", whichever backend the manager
  picked. `HEYM_SANDBOX_BACKEND` alone chooses Docker or Kubernetes.
- `resolve_image(overrides)` returns the first non-empty variable in `overrides` (each
  site passes the order it uses today), then the backend's own image: `docker inspect
  <hostname>` on Docker, the backend pod's container image on Kubernetes.

## Milestone 1: Manager and Docker parity (no behavior change)

- Add `app/services/sandbox/` with `spec.py`, `errors.py`, `env.py`,
  `docker_backend.py` and `manager.py`, with Docker as the only backend.
- Move sites 1 to 10 onto `SandboxSpec` plus `manager.run` (one-shot) or
  `manager.process_command` (MCP stdio). Delete the duplicated helpers. Modules that
  other code imports (`docker_available`, `resolve_sandbox_image`, `hardening_args`,
  `resolve_mount`) either move or become thin re-exports, whichever keeps the diff
  smaller. Tests patch the manager, not module internals.
- The Codex and OpenCode wrappers move in Milestone 2, together with their mount fix,
  so that their argv changes in one reviewed step.
- Remove the `/.dockerenv` assumption from workspace placement. `_is_containerized()`
  is false in a containerd pod, which would put workspaces in a temp dir the sandbox
  cannot see. The backend answers through `manager.uses_shared_workspace()`: Docker
  keeps today's rule, Kubernetes always uses the workspace mount.

**Parity contract.** Before any site moves, a snapshot test records the current argv
of every site for a fixed set of inputs (env combinations included: custom network,
custom user, MCP files volume or host dir, `docker run IMAGE` with `-e`/`-w`/
`--entrypoint`). After the move, the test compares the new argv to the snapshot after
normalizing: `docker run`, then the set of `(flag, value)` pairs, then the `--env`
values in order, then `--entrypoint`, image and trailing args exactly. Flag order is
not part of the contract, since Docker ignores it. Values, the env order and the tail
are.

## Milestone 2: Coding-agent run scope (both backends)

**Rule.** A Codex or OpenCode run mounts exactly two directories from its workspace
volume, each at the same absolute path the backend uses:

| Agent | Workspace | Home |
|---|---|---|
| Codex | `<root>/<id>` | `<root>/<id>.codex-home` (from `CODEX_HOME`) |
| OpenCode | `<root>/<id>` | `<root>/<id>.oc-home` (from `HOME`; the `XDG_*` dirs live under it) |

`<root>` is `HEYM_CODEX_WORKSPACE_DIR` or `HEYM_OPENCODE_WORKSPACE_DIR`. Nothing else
on the volume is visible: not the root, not other runs, not other homes.

**`RunScope`** (`coding_agents.py`, stdlib only) is derived from the process cwd and
env, which the runner services already set correctly. All three spawn points
(`codex login`, `codex exec`, `opencode run`) start with cwd at the run's workspace
and the home in env; `git clone` is the only command that runs at the root, and it
runs on the backend, not in a runner.
- `<id>` is the first path component of the cwd relative to `<root>`. A cwd at the
  root itself or outside it is refused.
- The home must resolve to exactly `<root>/<id>.codex-home` (or `.oc-home`).
  Anything else (unset, another run's home, the legacy root-level `.codex-home`) is
  refused with exit 2. The wrapper's legacy fallback to `<root>/.codex-home` goes
  away: the runner sets a per-run `CODEX_HOME` on every call.
- Both directories must already exist (the runner creates them before spawning).
  Docker's `volume-subpath` fails on a missing path, and refusing early gives a clear
  message.

**Docker rendering.**
- Named volume: `--mount type=volume,src=<vol>,dst=<root>/<id>,volume-subpath=<id>`,
  and the same for the home. This requires Docker Engine 25+. Codex already needs it
  for `systempaths=unconfined`; OpenCode now needs it too when it uses a named volume,
  as skills already do.
- Bind (`HEYM_CODEX_HOST_WORKSPACE_DIR`, `HEYM_OPENCODE_HOST_WORKSPACE_DIR`, or an
  inspected bind mount): `--mount type=bind,src=<host>/<id>,dst=<root>/<id>`, and the
  same for the home.
- Every other flag of both wrappers stays the same; the parity snapshot covers the
  rest of the argv. The Codex privileges are untouched (see Findings).
- Existing workspaces keep working: resume reuses the same `<id>`.

**The wrappers become shims.** `docker/heym-codex-docker` and
`docker/heym-opencode-docker` keep their paths, so `HEYM_*_CLI_COMMAND`, Compose and
both Dockerfiles stay as they are. Each becomes a short stdlib script that finds the
backend venv interpreter (`/app/.venv/bin/python` or `/app/backend/.venv/bin/python`,
the probe the formatter already uses) and execs `python -m
app.services.sandbox.wrapper_cli codex|opencode <args>` with `PYTHONPATH` at the
backend root. `wrapper_cli` builds the `RunScope` and the `SandboxSpec`, gets the
command from the manager, and runs it. Removing the container on SIGTERM, SIGINT and
SIGHUP, which only the OpenCode wrapper does today, now applies to both. The two
near-identical wrappers stop being duplicates.

**Backend agreement.** The runner services pass the manager's resolved backend to the
child (`HEYM_SANDBOX_BACKEND=docker|kubernetes` in its env), so the wrapper never
detects a different one. The Codex runner reads the same value to choose
`workspace-write` (Docker) or `danger-full-access` (Kubernetes, and only when the
shim runs Codex: a host `codex` binary keeps its own sandbox on every backend).

Native development (`run.sh`, `HEYM_CODEX_CLI_COMMAND=codex`) runs the host binary
without a wrapper and is unchanged.

## Milestone 3: Kubernetes backend for sites without a workspace

Sites 1, 2, 3, 7, 9 and 10 (MCP without an operator mount).

### API client

- Sync `httpx.Client` for REST and `websockets.sync.client` for attach. Both are
  existing dependencies; no new package.
- **Config.** In-cluster: `KUBERNETES_SERVICE_HOST`/`PORT`, the SA CA bundle, and the
  token file, re-read on every request because bound tokens rotate. When
  `HEYM_SANDBOX_BACKEND=kubernetes` is forced and there are no in-cluster credentials,
  a minimal kubeconfig loader reads `KUBECONFIG` or `~/.kube/config`: current context,
  server, CA data, and client cert/key data or a token. Exec and auth-provider plugins
  are refused with a message. This exists for native development and live tests
  against OrbStack; `auto` never reads a kubeconfig.
- Calls: create/get/delete/list pods, get the backend's own pod, get PVC,
  SelfSubjectAccessReview, attach.
- **Minimum server version: 1.30.** Attach uses the `v5.channel.k8s.io` subprotocol,
  whose close frame half-closes stdin. Every runner reads stdin to EOF, so v4 is not
  enough. Availability fails with a clear message on older servers.

### Pod

Built by `kubernetes/pod.py`, a pure function covered by golden tests.

```yaml
metadata:
  name: <spec.name>
  labels:
    app.kubernetes.io/managed-by: heym
    heym.run/sandbox: <spec.site>
    heym.run/network: none | egress
    heym.run/instance: <backend pod name>
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  enableServiceLinks: false
  activeDeadlineSeconds: <timeout + 30 for one-shot; caller deadline for processes>
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534        # omitted on OpenShift, see below
    runAsGroup: 65534       # omitted on OpenShift
    seccompProfile: {type: RuntimeDefault}
  containers:
  - name: sandbox
    image: <spec.image>
    imagePullPolicy: IfNotPresent
    command: [<entrypoint>]
    args: [...]
    workingDir: <spec.workdir>
    stdin: true
    stdinOnce: true
    tty: false
    env: [...]
    resources:
      limits: {memory: <memory>, cpu: <cpus>}
      requests: {memory: <memory>, cpu: 100m}
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: <spec.read_only_root>
      capabilities: {drop: [ALL]}
    volumeMounts: [tmpfs, shm, workspace subPaths]
  volumes: [emptyDir Memory with sizeLimit, ...]
```

`HEYM_SANDBOX_K8S_POD_OVERRIDES` (JSON) may set only `nodeSelector`, `tolerations`,
`runtimeClassName` (gVisor or Kata), `imagePullSecrets` and `priorityClassName`. Any
other key makes the backend unavailable (fail closed), so an override can never
loosen the security context.

**OpenShift.** `restricted-v2` assigns each namespace its own UID range and rejects
a fixed `runAsUser: 65534`. The backend checks API discovery once for
`security.openshift.io/v1` (discovery needs no extra RBAC). When that group exists,
the pod leaves out `runAsUser`/`runAsGroup` and keeps `runAsNonRoot: true`, so the
SCC assigns the UID. Everything that sandboxes write to is already world-writable
(`/tmp` emptyDir, 0777 run dirs, `chmod -R a+rwX` for Codex/OpenCode), so an
arbitrary UID works. This path cannot be tested on OrbStack; the issue author offered
to verify it.

### One-shot lifecycle (`manager.run`)

1. Create the pod.
2. Wait until the container is running or terminated. This **startup wait** is a
   constant 120 s and is separate from the site's execution timeout, so a first image
   pull does not eat the run's budget. `ErrImagePull`, `ImagePullBackOff`,
   `CreateContainerConfigError`, `InvalidImageName`, an unschedulable pod, or a
   container that terminates with reason `StartError` all give `start_failed=True`
   (the Docker 125/126/127 equivalent).
3. Attach (stdin, stdout, stderr). Send stdin, then the v5 close frame for channel 0.
   Collect channels 1 and 2 until the stream ends or the execution timeout fires.
4. Read the exit code from the pod status (`state.terminated.exitCode`), polling
   briefly until it is set. The channel-3 status message is only a fallback.
   `reason: OOMKilled` sets `oom_killed`.
5. Delete the pod with grace period 0, on every exit path. On timeout, delete first,
   then raise `SandboxTimeoutError`, which subclasses `TimeoutError` so each site's
   existing message still applies.

If the container already finished before the attach connected (only possible for a
program that does not read stdin first, which no Heym runner does), stdout falls back
to `pods/log`, with stdout and stderr merged.

### Long-lived processes (`manager.process_command`)

MCP stdio, Codex and OpenCode hand a command to something that spawns a process. On
Kubernetes that process is the bridge. Codex and OpenCode already run inside their
wrapper process (`wrapper_cli`), which calls the bridge code directly. MCP stdio gets
the bridge as its command:

```
<backend venv python> -m app.services.sandbox.kubernetes.process
env: HEYM_SANDBOX_PROCESS_SPEC=<JSON: SandboxSpec + API endpoint + namespace>
```

The bridge creates the pod, attaches, pumps its own stdin to channel 0 and channels
1 and 2 to its stdout and stderr, exits with the container's exit code, and deletes
the pod on exit and on SIGTERM, SIGINT and SIGHUP. The MCP SDK's `stdio_client`
needs no change. The spec travels in the child's environment, not its argv, so
user-supplied MCP env values do not show up in `ps` (the Docker path passes them as
`--env K=V` argv today; unchanged in this work).

Deadlines for process pods: Codex and OpenCode use the run's configured timeout plus
60 s. MCP stdio has no run-level timeout at the transport, so its pods get a 24 h
ceiling, and the bridge deletes the pod when the session closes.

**Start gate.** Attach only sees output written after it connects. A process that
reads stdin before writing anything (every one-shot runner, an MCP server) is safe.
Codex and OpenCode may print first, so their specs set `start_gate=True`: the command
becomes `sh -c 'head -c1 >/dev/null; exec "$@"' -- <entrypoint> <args>` and the bridge
sends one byte after attaching. That needs `sh` and `head`, which the backend image
has. Arbitrary `docker run IMAGE` MCP images do not get the gate.

### Network

- `none` pods carry `heym.run/network: none`; everything else carries `egress`.
  Operators apply the shipped NetworkPolicies: deny all ingress to sandbox pods, deny
  all egress for `none`, and for `egress` allow everything except cluster CIDRs and
  `169.254.169.254/32` (the cloud metadata service), plus DNS.
- **Fail closed when policy is not enforced.** A label does nothing without a CNI that
  enforces NetworkPolicy. Before the first `none` run in a process, the backend
  starts a canary pod labeled `none` that tries a TCP connect to
  `$KUBERNETES_SERVICE_HOST:$KUBERNETES_SERVICE_PORT` with a 3 s timeout. If the
  connect succeeds, every `none` site fails closed with a message naming the missing
  policy. The result is cached for the process. There is no opt-out in v1: sites
  without a subprocess mode (Code node, file sandbox, formatter) fail today on such
  clusters too, so this is no regression. Sites that have one can still choose
  `subprocess` explicitly.

### Images

- Site overrides as today (`HEYM_PYTHON_TOOL_IMAGE`, `HEYM_PLAYWRIGHT_SANDBOX_IMAGE`,
  ...). Fallback: the backend pod's own image, read with `GET pods/$HOSTNAME`. With
  more than one container in the pod and no override, resolution fails closed and
  names the variable to set.
- **Playwright on `restricted`.** Docker runs Playwright as root because Chromium is
  installed under `/root/.cache`. A restricted pod cannot run as root. Both
  Dockerfiles set `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` before `playwright
  install`, so a non-root user can read the browsers. On Kubernetes, Playwright runs as
  `HEYM_PLAYWRIGHT_SANDBOX_USER` or 65534. Docker keeps root by default. Custom code
  already has to launch Chromium with `--no-sandbox`.

### Namespace, RBAC, cleanup

- **Namespace:** `HEYM_SANDBOX_K8S_NAMESPACE`, default the backend's own namespace
  (read from the SA namespace file). Milestone 4 explains why workspace sites need the
  PVC in that namespace.
- **Role in the sandbox namespace:** `pods` create/get/list/watch/delete,
  `pods/attach` create and get (the verb the API server checks for websocket attach
  has changed between versions, so grant both), `pods/log` get,
  `persistentvolumeclaims` get. If the sandbox namespace is not the backend's, a
  second Role in the backend's namespace grants `get` on `pods` so the backend can
  read its own pod. Sandbox pods run under the namespace's `default` ServiceAccount,
  and its token is never mounted.
- **Janitor** (`janitor.py`, started from the app lifespan on every instance whose
  backend is `kubernetes`, every 10 minutes): delete terminated sandbox pods older than
  10 minutes, and, in-cluster, running pods whose backend pod
  (`heym.run/instance`) no longer exists. There is no startup sweep: the backend runs
  several uvicorn workers under one pod name, and a restarting worker must not delete
  its siblings' pods. Running pods of a crashed worker end at `activeDeadlineSeconds`.
- **Cluster heartbeat.** `cluster/registry.py` reports `docker_ok` from the sandbox
  backend: the socket probe on Docker, `available()` on Kubernetes. The column name
  stays (no migration); its meaning widens to "a sandbox backend is reachable".

### Hardening gaps against Docker (documented, accepted)

| Docker flag | Kubernetes | Handling |
|---|---|---|
| `--pids-limit` | no pod field | kubelet `podPidsLimit` (operator). Memory, CPU and the deadline still bound a fork bomb. |
| tmpfs `noexec` (Python tool) | emptyDir cannot be `noexec` | Accepted. The tool already runs arbitrary Python. |
| `--network none` | NetworkPolicy | Label plus the canary check above. |
| `--memory-swap` = memory | swap is off on most nodes | Nothing to map. |

## Milestone 4: Workspace sites on Kubernetes

Sites 4, 5, 6, 8, 11, 12, and site 9/10 with an operator mount.

### Workspace mapping

`kubernetes/workspace.py` reads the backend pod once, finds the `volumeMount` whose
`mountPath` is the longest prefix of the host path, and returns that volume's
`persistentVolumeClaim.claimName` and `subPath = <mount's own subPath>/<relative
path>`. This is the Kubernetes version of `docker inspect` on the backend's mounts.
No new variable is needed, and the two workspace roots that exist today
(`/app/data/codex-workspaces`, `/app/data/opencode-workspaces`) resolve to their own
claims.

- The target path inside the sandbox pod is the same absolute path the backend uses,
  as the skill path does with Docker today. Paths in env and args stay valid.
- **Access mode.** `ReadWriteMany`: no scheduling constraint. `ReadWriteOnce`: the
  pod is pinned to the backend's node (`spec.nodeName` from the backend pod), because
  pods on one node can share an RWO volume. That covers single-node clusters and
  OrbStack's `local-path`. `ReadWriteOncePod`: fails closed with a message.
- The PVC must exist in the sandbox namespace. With the default namespace that is
  automatic. A dedicated sandbox namespace needs a second claim on the same RWX share
  (static PV), described in the manifests' README.
- If a backend host path is not under any PVC mount, the site fails closed and says
  so, as Docker does today without a shared volume.

### Per site

| Site | Mounts | Notes |
|---|---|---|
| Code node install | run dir rw | network `egress` |
| Code node run with deps | run dir ro | `PYTHONPATH` at `.deps`, unchanged |
| File sandbox | `<base>/in` at `/input` ro, `<base>/work` at `/work` rw | network `none`; persistent chat workspaces live on the PVC |
| Skill | run dir rw | `.home` and `_output_files` already 0777 |
| MCP stdio operator mount | `HEYM_MCP_STDIO_FILES_VOLUME` read as a PVC name, `HEYM_MCP_STDIO_FILES_SUBPATH` as `subPath`, read-only unless `HEYM_MCP_STDIO_FILES_WRITABLE` | `HEYM_MCP_STDIO_FILES_HOST_DIR` is refused (hostPath breaks `restricted`) |
| Codex | `<id>` and `<id>.codex-home` | see below |
| OpenCode | `<id>` and `<id>.oc-home` | see below |

### Codex and OpenCode on Kubernetes

- The same shims run on Kubernetes. `wrapper_cli` builds the same `RunScope` and the
  same `SandboxSpec`, and the Kubernetes backend runs it in-process as the bridge (the
  wrapper is already the child process the runner supervises). The runner services
  keep spawning `[cli_command, ...]`; a custom `HEYM_*_CLI_COMMAND` is honored as-is.
- Each pod mounts only its run's workspace and home as two `subPath` mounts (the
  Milestone 2 rule).
- **Codex sandbox flag.** When the shim runs Codex on Kubernetes, the runner passes
  `--sandbox danger-full-access` (and `-c sandbox_mode="danger-full-access"` on
  resume) instead of `workspace-write`. Docker, and a host `codex` binary on any
  backend, keep `workspace-write`.
- **Deadline.** The runners put the run's timeout plus 60 s in
  `HEYM_SANDBOX_DEADLINE_SECONDS` in the child's environment (internal, not operator
  configuration); it becomes the pod's `activeDeadlineSeconds`.
- **Ownership.** The backend runs as root and clones as root; the pod runs as 65534.
  Before starting the pod, `wrapper_cli` (running as the backend's user) makes the
  run's two directories writable to everyone (`chmod -R a+rwX`), and the pod gets
  `GIT_CONFIG_COUNT=1, GIT_CONFIG_KEY_0=safe.directory, GIT_CONFIG_VALUE_0=*` so
  Codex's own `git` calls do not stop at "dubious ownership". The backend's
  commit/push steps run as root and are unaffected.
- `start_gate=True`. The deadline is the run's configured timeout plus 60 s.
- OpenCode's `docker rm -f heym-opencode-<run_id>` cleanup becomes
  `manager.force_remove(...)`. The pod has the same name.
- Resource defaults stay: 4g memory, 2 CPU, the same tuning variables.

## Security invariants (each one gets a test)

1. No sandbox pod mounts a ServiceAccount token, sets `hostNetwork`, `hostPID` or
   `hostIPC`, uses `hostPath`, runs as uid 0, keeps a capability, or allows privilege
   escalation. Every rendered pod passes Pod Security `restricted`.
2. The env allowlists are unchanged: no backend secret (`SECRET_KEY`,
   `ENCRYPTION_KEY`, `DATABASE_URL`, provider keys) reaches a pod. The same allowlist
   functions feed both backends.
3. `none` sites never run without a passing canary.
4. Every backend failure fails closed with the site's message. Nothing falls back to
   `subprocess` or to the other backend.
5. A workspace pod mounts only its run's `subPath`, never a claim's root.
6. Pod overrides cannot touch any security field.
7. Every pod has `activeDeadlineSeconds` and is deleted on every exit path of `run`
   and of the bridge.
8. A Codex or OpenCode run, on either backend, mounts exactly its workspace and its
   home, never the volume root or another run's directory. A cwd at or outside the
   root, or a home that is not the run's own, is refused before anything starts.

Invariants 1 to 7 go in `backend/tests/test_advisory_k8s_sandbox_*.py`, invariant 8 in
`backend/tests/test_advisory_coding_agent_run_scope.py`, following the repository's
advisory convention.

## Configuration

New variables (all optional):

| Variable | Meaning | Default |
|---|---|---|
| `HEYM_SANDBOX_BACKEND` | `auto`, `docker` or `kubernetes` | `auto` |
| `HEYM_SANDBOX_K8S_NAMESPACE` | namespace for sandbox pods | backend's namespace |
| `HEYM_SANDBOX_K8S_POD_OVERRIDES` | JSON: `nodeSelector`, `tolerations`, `runtimeClassName`, `imagePullSecrets`, `priorityClassName` | none |

Reused with a Kubernetes reading: `HEYM_MCP_STDIO_FILES_VOLUME` (PVC name),
`HEYM_MCP_STDIO_FILES_SUBPATH` (`subPath`). Every image, memory, CPU and network
variable keeps working on both backends. `ENVIRONMENT-VARIABLES.md` gets a
"Sandbox backend" section.

## Deploy artifacts

`deploy/kubernetes/`, applied with `kubectl apply -k`:

- `base/`: Namespace, backend ServiceAccount, Role and RoleBinding, NetworkPolicies
  (ingress deny for sandboxes, egress deny for `none`, egress allow minus cluster
  CIDRs and metadata for `egress`), workspace PVCs (Codex, OpenCode), backend
  Deployment and Service, frontend Deployment and Service, and a Secret template.
- `overlays/orbstack/`: `heym-backend:local` with `IfNotPresent`, `local-path` RWO
  claims, and a dev-only Postgres StatefulSet so the overlay runs on its own.
- `README.md`: prerequisites (Kubernetes 1.30+, a CNI that enforces NetworkPolicy,
  `podPidsLimit`), RWX versus RWO, and the dedicated-namespace variant.

## Testing

**Unit and parity (CI, no cluster)**
- Milestone 1: argv snapshot parity for all ten Python sites; manager selection;
  existing site tests moved to patch the manager.
- Milestone 2: `RunScope` derivation and every refusal (cwd at the root, cwd outside
  it, missing home, another run's home, the legacy `<root>/.codex-home`, a missing
  directory); Docker argv for both agents mounts exactly two `subPath`s for a named
  volume and two scoped binds for a bind mount, never the root; the rest of the argv
  matches the old wrappers' snapshot; the shims find the venv interpreter for both
  image layouts; signal cleanup for both agents; the runner passes the resolved
  backend to the child; `test_codex_docker_wrapper.py` moves to the new module.
- Milestone 3: golden pod manifests per site; config loading (in-cluster, kubeconfig
  cert/token, exec plugin refused); client calls against `httpx.MockTransport`;
  attach framing against a local `websockets` server in a thread (stdin close, stdout
  and stderr split, status channel); lifecycle mapping (image pull, `StartError`,
  unschedulable, OOM, timeout deleting the pod); canary open versus closed; janitor
  selection; the advisory invariants; the import rule.
- Milestone 4: workspace mapping (longest prefix, nested `subPath`, RWO pinning,
  `ReadWriteOncePod` refused, path outside every claim refused); Codex
  `danger-full-access` only on Kubernetes; ownership prep; OpenCode cleanup through
  the manager.

**Live (opt-in, OrbStack)**
- `backend/tests/live/test_k8s_sandbox_live.py`, skipped unless
  `HEYM_K8S_LIVE_CONTEXT` is set. From the host, with a kubeconfig and the backend
  forced to `kubernetes`, it runs sites 1, 2, 3 and 7, an MCP stdio echo server
  through the bridge, the canary in a namespace with and without the deny policy,
  and a pod in a namespace labeled `pod-security.kubernetes.io/enforce: restricted`.
- `scripts/k8s-sandbox-smoke.sh` deploys `overlays/orbstack`, then calls the API for a
  Code node with `requirements.txt`, a skill that writes an output file, a file
  sandbox call, an MCP stdio tool, and (with credentials present) one Codex and one
  OpenCode run. It checks that no pod remains afterwards.

**Live (Docker, local)**
- Run scope on Docker: with `docker compose` running, two concurrent runs, then
  `HEYM_CODEX_DOCKER_ENTRYPOINT=sh` and `-c "ls <root>; cat <root>/<other>.codex-home/auth.json"`
  through the shim. Only the run's own two directories are listed, and the read
  fails. The same check runs for OpenCode with its entrypoint override.
- `./check.sh` stays green after every milestone. Outside the coding-agent mounts,
  Docker behavior does not change.

## Delivery

One branch, `impl/native-k8s-api-and-pod-management`, and one PR to `main`. The
milestones are commit groups inside it, in this order, each one leaving `./check.sh`
green:

| Milestone | Contents | Behavior change |
|---|---|---|
| 1 | `sandbox/` package, Docker backend, sites 1 to 10 and 13 moved, duplicates removed, parity snapshots | none |
| 2 | `RunScope`, `wrapper_cli`, shim wrappers, scoped Codex/OpenCode mounts on Docker, advisory tests | Codex/OpenCode see only their own run (security fix); OpenCode with a named volume needs Docker Engine 25+ |
| 3 | Kubernetes client, pod builder, one-shot runner, bridge, canary, janitor, auto selection, cluster heartbeat, sites 1, 2, 3, 7, 9, 10, Playwright browser path, manifests | new backend only |
| 4 | Workspace mapping, sites 4, 5, 6, 8, 11, 12, 13 on Kubernetes, MCP operator mount, Codex `danger-full-access` on Kubernetes, docs | new backend only |

Milestone 2 changes Docker behavior, so the PR description calls it out on its own,
and the release notes say that OpenCode now needs Docker Engine 25+ when it uses a
named volume.

Docs (through the `heym-documentation` skill): `ENVIRONMENT-VARIABLES.md`,
`frontend/src/docs/content/reference/running-and-deployment.md` (new Kubernetes
section), `cluster.md` (meaning of `docker_ok`), and the node pages that say "requires
Docker" (Code, Playwright, Codex, OpenCode). AGENTS.md's node-placement paragraph
says "its own Docker socket"; it becomes "its own Docker socket or Kubernetes API
access". There is no release tour entry: nothing changes in the UI.

## Risks

| Risk | Mitigation |
|---|---|
| About 3 s per call, which adds up for agents calling a Python tool many times | Documented. A warm pool is a later, separate decision. |
| A 4 to 5 GB image pulled on a node that has not run one yet | Separate 120 s startup wait; README suggests a pre-pull DaemonSet. |
| Attach behaves differently across runtimes (containerd, CRI-O on OpenShift) | Pod status is the source of truth for exit codes, with a logs fallback. Live tests on OrbStack (docker runtime) only, so OpenShift stays a community-verified target. |
| OpenShift UID assignment under `restricted-v2` | Discovery-based detection (see Pod). Untested locally; verified by the issue author or a CRC/OpenShift Local run before claiming support. |
| Lost output before attach | Start gate for Codex and OpenCode; every other runner reads stdin first. |

## Implementation notes (2026-11-02)

Found while implementing and verifying on OrbStack; the code and tests already reflect them.

- **Host data in local images.** `.dockerignore` did not exclude `data` or `backend/data`,
  so a local build copied the developer's workspaces and Drive files into the image.
  The old whole-volume mount hid them under the workspace root; with scoped mounts a
  runner could list them. Both directories are now ignored (release images are built
  from a clean checkout and never had them).
- **Pod finished before the attach.** The network canary did not read stdin, finished
  before the attach arrived, and the API server answered HTTP 500. The canary now reads
  stdin first, and the backend falls back to the pod's exit status and log when an
  attach is refused.
- **Service links.** A Service named `postgres` makes Kubernetes inject
  `POSTGRES_PORT=tcp://...` into the backend pod, which breaks Heym's own
  `POSTGRES_PORT` setting. The example Deployment sets `enableServiceLinks: false`.
- **Tests and backend selection.** Selecting `auto` probes `docker version`. Tests that
  patch `subprocess` globally would hit that probe if the manager were built inside
  them, so `tests/conftest.py` builds a Docker-pinned manager before every test; tests
  about selection reset it themselves.
- `SandboxTimeout` is `SandboxTimeoutError` (Ruff N818).
