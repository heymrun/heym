"""Watch labelled Secrets and keep this process's store current, like a client-go informer.

Every process runs one: each serves runs, and values never leave memory, so each needs
its own copy. Startup never waits for the first list (the release image runs eight
processes per instance, and the UI must stay up while the API server is unreachable).
Until it completes, this process claims no queued runs and its credentials raise
"not synced yet". After it, a broken watch keeps the last-known values while it
re-lists.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings
from app.services.k8s_credentials.secret import LABEL, parse_secret
from app.services.k8s_credentials.store import SecretCredentialStore
from app.services.k8s_credentials.store import store as default_store
from app.services.sandbox.kubernetes.config import (
    KubeConfig,
    in_cluster_available,
    load_in_cluster,
    load_kubeconfig,
)

logger = logging.getLogger("k8s_credentials")

LABEL_SELECTOR = f"{LABEL}=true"
# A watch ends after this long and the cache re-lists, as an informer resyncs. The
# re-list also retries Secrets whose owner had not signed in yet.
RESYNC_SECONDS = 300
_MAX_BACKOFF_SECONDS = 30.0


class SecretsForbiddenError(RuntimeError):
    """The ServiceAccount may not list or watch Secrets. A configuration error."""


def load_config() -> KubeConfig:
    """The pod's ServiceAccount, or the current kubeconfig context outside a cluster."""
    return load_in_cluster() if in_cluster_available() else load_kubeconfig()


def watched_namespace(config: KubeConfig) -> str:
    return settings.k8s_credentials_namespace.strip() or config.own_namespace


class SecretWatcher:
    """List, then watch, labelled Secrets in one namespace; repeat forever."""

    def __init__(
        self,
        config: KubeConfig,
        namespace: str,
        *,
        store: SecretCredentialStore = default_store,
        transport: httpx.AsyncBaseTransport | None = None,
        on_change: Any = None,
    ) -> None:
        self.config = config
        self.namespace = namespace
        self.store = store
        self._on_change = on_change
        verify: Any = True if transport is not None else config.ssl_context()
        self._http = httpx.AsyncClient(
            base_url=config.server,
            verify=verify,
            transport=transport,
            timeout=httpx.Timeout(30.0, connect=10.0, read=RESYNC_SECONDS + 30.0),
            trust_env=False,
        )
        self._task: asyncio.Task[None] | None = None

    def _headers(self) -> dict[str, str]:
        token = self.config.bearer_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    @property
    def _path(self) -> str:
        return f"/api/v1/namespaces/{quote(self.namespace)}/secrets"

    async def can(self, verb: str) -> bool:
        """SelfSubjectAccessReview for `verb secrets` in the watched namespace."""
        review = {
            "apiVersion": "authorization.k8s.io/v1",
            "kind": "SelfSubjectAccessReview",
            "spec": {
                "resourceAttributes": {
                    "namespace": self.namespace,
                    "verb": verb,
                    "resource": "secrets",
                }
            },
        }
        response = await self._http.post(
            "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews",
            json=review,
            headers=self._headers(),
        )
        response.raise_for_status()
        return bool((response.json().get("status") or {}).get("allowed"))

    async def check_permissions(self) -> None:
        """Raise SecretsForbiddenError when the API server says list or watch is denied.

        An unreachable API server is not a configuration error: that raises the
        transport error, and the caller carries on and lets the watch retry.
        """
        denied = [verb for verb in ("list", "watch") if not await self.can(verb)]
        if denied:
            raise SecretsForbiddenError(
                f"HEYM_K8S_CREDENTIALS is on, but the ServiceAccount may not "
                f"{' or '.join(denied)} secrets in namespace {self.namespace!r}. "
                "Grant get, list and watch on secrets there (see deploy/kubernetes)."
            )

    async def list_once(self) -> str:
        """Replace the store with a full list. Returns the resourceVersion to watch from."""
        response = await self._http.get(
            self._path, params={"labelSelector": LABEL_SELECTOR}, headers=self._headers()
        )
        if response.status_code == 403:
            raise SecretsForbiddenError(f"list secrets in {self.namespace!r} is forbidden")
        response.raise_for_status()
        body = response.json()
        self.store.replace_all([parse_secret(item) for item in body.get("items") or []])
        logger.info(
            "Synced %d Kubernetes credential Secret(s) from namespace %s",
            len(self.store.items()),
            self.namespace,
        )
        await self._changed()
        return str((body.get("metadata") or {}).get("resourceVersion") or "")

    async def watch_once(self, resource_version: str) -> None:
        """Apply watch events until the server ends the watch or it breaks."""
        params = {
            "labelSelector": LABEL_SELECTOR,
            "watch": "1",
            "resourceVersion": resource_version,
            "timeoutSeconds": str(RESYNC_SECONDS),
            "allowWatchBookmarks": "true",
        }
        async with self._http.stream(
            "GET", self._path, params=params, headers=self._headers()
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip() and not await self._apply(json.loads(line)):
                    return

    async def _apply(self, event: dict[str, Any]) -> bool:
        """Apply one event. False means the watch is stale and must re-list."""
        kind = event.get("type")
        obj = event.get("object") or {}
        if kind == "ERROR":
            # 410 Gone: the resourceVersion is too old. Anything else: start over too.
            logger.info("Secret watch ended: %s", obj.get("message") or obj)
            return False
        if kind == "BOOKMARK":
            return True
        parsed = parse_secret(obj)
        if kind == "DELETED":
            self.store.remove(parsed.pointer)
        elif kind in ("ADDED", "MODIFIED"):
            self.store.upsert(parsed)
        await self._changed()
        return True

    async def _changed(self) -> None:
        if self._on_change is not None:
            try:
                await self._on_change()
            except Exception:
                logger.exception("Kubernetes credential row sync failed")

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                resource_version = await self.list_once()
                backoff = 1.0
                await self.watch_once(resource_version)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Keep the last-known values: a blip must not drop working credentials.
                self.store.last_error = str(exc) or type(exc).__name__
                logger.warning(
                    "Kubernetes credential watch failed (%s); retrying in %.0fs",
                    self.store.last_error,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._http.aclose()
