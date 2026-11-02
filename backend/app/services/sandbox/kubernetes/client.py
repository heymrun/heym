"""A small synchronous Kubernetes API client. Only the calls the sandbox needs."""

from __future__ import annotations

import ssl
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.services.sandbox.kubernetes.config import KubeConfig

CONTAINER = "sandbox"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class KubeApiError(RuntimeError):
    """The API server refused a request."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Kubernetes API {status}: {message}")
        self.status = status


def _message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message") or response.text)[:500]
    except ValueError:
        return response.text[:500]


class KubeClient:
    """REST calls against one namespace, authenticated as the backend's ServiceAccount."""

    def __init__(self, config: KubeConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        verify: ssl.SSLContext | bool = True if transport is not None else config.ssl_context()
        # trust_env=False: API calls never go through an HTTP proxy from the environment.
        self._http = httpx.Client(
            base_url=config.server,
            verify=verify,
            transport=transport,
            timeout=_TIMEOUT,
            trust_env=False,
        )

    @property
    def namespace(self) -> str:
        """The namespace sandbox pods live in."""
        return self.config.namespace

    def _headers(self) -> dict[str, str]:
        token = self.config.bearer_token()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, str] | None = None,
        allow_404: bool = False,
    ) -> Any:
        """One API call; JSON bodies come back parsed, text bodies as ``str``."""
        response = self._http.request(
            method, path, json=json, params=params, headers=self._headers()
        )
        if response.status_code == 404 and allow_404:
            return None
        if response.status_code >= 400:
            raise KubeApiError(response.status_code, _message(response))
        if not response.content:
            return None
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        return response.text

    def _pods(self, namespace: str | None = None) -> str:
        return f"/api/v1/namespaces/{quote(namespace or self.namespace)}/pods"

    def create_pod(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Create a pod in the sandbox namespace."""
        return self.request("POST", self._pods(), json=manifest)

    def get_pod(self, name: str, namespace: str | None = None) -> dict[str, Any] | None:
        """The pod, or None when it does not exist."""
        return self.request("GET", f"{self._pods(namespace)}/{quote(name)}", allow_404=True)

    def delete_pod(self, name: str) -> None:
        """Delete now (grace period 0). A missing pod is not an error."""
        self.request(
            "DELETE",
            f"{self._pods()}/{quote(name)}",
            params={"gracePeriodSeconds": "0"},
            allow_404=True,
        )

    def list_pods(self, label_selector: str) -> list[dict[str, Any]]:
        """Pods in the sandbox namespace matching ``label_selector``."""
        result = self.request("GET", self._pods(), params={"labelSelector": label_selector})
        return list((result or {}).get("items") or [])

    def pod_log(self, name: str) -> str:
        """The sandbox container's log (stdout and stderr merged)."""
        log = self.request(
            "GET",
            f"{self._pods()}/{quote(name)}/log",
            params={"container": CONTAINER},
            allow_404=True,
        )
        return log if isinstance(log, str) else ""

    def get_pvc(self, name: str) -> dict[str, Any] | None:
        """A PersistentVolumeClaim in the sandbox namespace, or None."""
        return self.request(
            "GET",
            f"/api/v1/namespaces/{quote(self.namespace)}/persistentvolumeclaims/{quote(name)}",
            allow_404=True,
        )

    def can_i(self, verb: str, resource: str, subresource: str = "") -> bool:
        """SelfSubjectAccessReview for ``verb resource[/subresource]`` in the sandbox namespace."""
        review = {
            "apiVersion": "authorization.k8s.io/v1",
            "kind": "SelfSubjectAccessReview",
            "spec": {
                "resourceAttributes": {
                    "namespace": self.namespace,
                    "verb": verb,
                    "resource": resource,
                    "subresource": subresource,
                }
            },
        }
        result = self.request(
            "POST", "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", json=review
        )
        return bool(((result or {}).get("status") or {}).get("allowed"))

    def has_api_group(self, group: str) -> bool:
        """True when the API server serves ``group`` (discovery needs no extra RBAC)."""
        return self.request("GET", f"/apis/{group}", allow_404=True) is not None

    def server_version(self) -> tuple[int, int]:
        """``(major, minor)`` of the API server."""
        info = self.request("GET", "/version") or {}
        major = str(info.get("major") or "0").rstrip("+") or "0"
        minor = str(info.get("minor") or "0").rstrip("+") or "0"
        return int(major), int(minor)

    def attach_url(self, name: str) -> str:
        """Websocket URL attaching stdin, stdout and stderr of the sandbox container."""
        base = self.config.server.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        query = urlencode(
            {"container": CONTAINER, "stdin": "true", "stdout": "true", "stderr": "true"}
        )
        return f"{base}{self._pods()}/{quote(name)}/attach?{query}"

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self._http.close()
