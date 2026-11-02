"""Load distribution on Kubernetes, checked from inside the main pod.

Run by ``k8s-cluster-smoke.sh``. It proves four things on a real cluster:

1. main and the worker both heartbeat into Postgres, agree on schema and keys, and
   report a reachable sandbox backend;
2. a queued run lands on the worker when the worker holds all the weight;
3. that run's Code node sandbox is a pod the worker created (its instance label);
4. the run's result comes back to main and into execution history.
"""

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update

API = "http://127.0.0.1:10105"
WORKER_ID = os.environ.get("SMOKE_WORKER_ID", "worker-1")
RUNS = 3
CODE = (
    "import socket, time\ndef main(params):\n    time.sleep(3)\n    return socket.gethostname()\n"
)


async def wait_for_cluster(timeout: float = 240.0):  # noqa: ANN201
    from app.db.models import ClusterInstance
    from app.db.session import async_session_maker

    deadline = time.monotonic() + timeout
    rows: dict = {}
    while time.monotonic() < deadline:
        async with async_session_maker() as db:
            rows = {row.id: row for row in (await db.execute(select(ClusterInstance))).scalars()}
        now = datetime.now(timezone.utc)
        fresh = [
            rows.get(name) is not None and now - rows[name].heartbeat_at < timedelta(seconds=30)
            for name in ("main", WORKER_ID)
        ]
        if all(fresh):
            return rows["main"], rows[WORKER_ID]
        await asyncio.sleep(3)
    raise AssertionError(f"main and {WORKER_ID} did not both heartbeat; rows: {sorted(rows)}")


async def route_everything_to_worker() -> None:
    from app.db.models import ClusterInstance
    from app.db.session import async_session_maker

    async with async_session_maker() as db:
        for instance_id, weight in (("main", 0), (WORKER_ID, 100)):
            await db.execute(
                update(ClusterInstance)
                .where(ClusterInstance.id == instance_id)
                .values(weight=weight, enabled=True, weight_configured=True)
            )
        await db.commit()


async def make_user() -> str:
    from app.db.models import User
    from app.db.session import async_session_maker
    from app.services.auth import create_access_token, hash_password

    async with async_session_maker() as db:
        user = User(
            email=f"cluster-smoke-{uuid.uuid4().hex[:8]}@heym.local",
            name="Cluster Smoke",
            hashed_password=hash_password(uuid.uuid4().hex),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return create_access_token(user.id)


async def history(workflow_id: str) -> list:
    from app.db.models import ExecutionHistory
    from app.db.session import async_session_maker

    async with async_session_maker() as db:
        rows = await db.execute(
            select(ExecutionHistory).where(ExecutionHistory.workflow_id == uuid.UUID(workflow_id))
        )
        return list(rows.scalars())


def watch_sandbox_pods(seen: dict[str, str], stop: threading.Event) -> None:
    """Record every Code node sandbox pod and the instance that created it."""
    from app.services.sandbox.kubernetes.client import KubeClient
    from app.services.sandbox.kubernetes.config import load_in_cluster

    client = KubeClient(load_in_cluster())
    while not stop.is_set():
        for pod in client.list_pods("heym.run/sandbox=code-run"):
            meta = pod.get("metadata") or {}
            seen[meta.get("name", "")] = (meta.get("labels") or {}).get("heym.run/instance", "")
        time.sleep(0.5)


def worker_pod_names() -> set[str]:
    from app.services.sandbox.kubernetes.client import KubeClient
    from app.services.sandbox.kubernetes.config import load_in_cluster

    config = load_in_cluster()
    client = KubeClient(config)
    pods = client.request(
        "GET",
        f"/api/v1/namespaces/{config.own_namespace}/pods",
        params={"labelSelector": "app.kubernetes.io/name=heym-worker"},
    )
    return {pod["metadata"]["name"] for pod in (pods or {}).get("items", [])}


async def main() -> int:
    main_row, worker_row = await wait_for_cluster()
    print(f"OK   heartbeats: main and {WORKER_ID} are live", flush=True)
    assert main_row.docker_ok and worker_row.docker_ok, "a sandbox backend is not reachable"
    print("OK   sandbox backend reachable on both instances (docker_ok)", flush=True)
    for field in ("version", "schema_revision", "keys_fingerprint"):
        assert getattr(main_row, field) == getattr(worker_row, field), f"{field} differs"
    print("OK   same version, schema revision and keys on both instances", flush=True)

    await route_everything_to_worker()
    await asyncio.sleep(6)
    print(f"OK   weights set: main 0, {WORKER_ID} 100", flush=True)

    token = await make_user()
    headers = {"Authorization": f"Bearer {token}"}
    nodes = [
        {
            "id": "input",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "input"},
        },
        {
            "id": "code",
            "type": "code",
            "position": {"x": 320, "y": 0},
            "data": {"label": "sandbox", "codeSource": CODE},
        },
    ]
    edges = [{"id": "e1", "source": "input", "target": "code"}]
    seen: dict[str, str] = {}
    stop = threading.Event()
    watcher = threading.Thread(target=watch_sandbox_pods, args=(seen, stop), daemon=True)
    watcher.start()
    outputs: list[str] = []
    async with httpx.AsyncClient(base_url=API, headers=headers, timeout=300) as http:
        created = await http.post("/api/workflows", json={"name": "Cluster smoke"})
        created.raise_for_status()
        workflow_id = created.json()["id"]
        saved = await http.put(
            f"/api/workflows/{workflow_id}", json={"nodes": nodes, "edges": edges}
        )
        saved.raise_for_status()
        for _ in range(RUNS):
            response = await http.post(
                f"/api/workflows/{workflow_id}/execute",
                json={"text": "go"},
                headers={"X-Simple-Response": "false"},
            )
            response.raise_for_status()
            body = response.json()
            assert body.get("status") == "success", body
            outputs.append(json.dumps(body["outputs"]))
    stop.set()
    watcher.join(5)

    rows = await history(workflow_id)
    placed = sorted({row.executed_by_instance_id or "?" for row in rows})
    assert len(rows) == RUNS and placed == [WORKER_ID], f"runs placed on {placed}: {len(rows)} rows"
    print(
        f"OK   {RUNS} queued runs executed on {WORKER_ID} and returned success to main", flush=True
    )
    assert all("heym-code-" in output for output in outputs), outputs
    print("OK   each run's Code node returned its sandbox pod's hostname", flush=True)
    workers = worker_pod_names()
    creators = set(seen.values())
    assert seen and creators <= workers, f"sandbox pods {seen} vs worker pods {workers}"
    print(
        f"OK   {len(seen)} sandbox pods, all created by the worker pod {sorted(creators)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except AssertionError as exc:
        print(f"FAIL {exc}", flush=True)
        sys.exit(1)
