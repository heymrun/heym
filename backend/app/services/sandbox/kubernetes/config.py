"""Where the Kubernetes API is and how to authenticate to it.

In a pod: the ServiceAccount token, CA and namespace files plus
``KUBERNETES_SERVICE_HOST``/``PORT``. Out of a cluster (only when
``HEYM_SANDBOX_BACKEND=kubernetes`` is forced, for development and live tests): a
kubeconfig with static credentials. Credential plugins are refused.
"""

from __future__ import annotations

import base64
import os
import ssl
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
NAMESPACE_ENV = "HEYM_SANDBOX_K8S_NAMESPACE"


class KubeConfigError(RuntimeError):
    """The API endpoint or credentials cannot be used. Callers fail closed."""


@dataclass(frozen=True)
class KubeConfig:
    """API endpoint, credentials, and the namespaces involved."""

    server: str
    namespace: str
    own_namespace: str
    in_cluster: bool
    ca_file: str | None = None
    ca_data: str | None = None
    token_file: str | None = None
    token: str | None = None
    client_cert_data: str | None = None
    client_key_data: str | None = None

    def bearer_token(self) -> str | None:
        """The bearer token, re-read from disk each time because bound tokens rotate."""
        if self.token_file:
            return Path(self.token_file).read_text(encoding="utf-8").strip()
        return self.token

    def ssl_context(self) -> ssl.SSLContext:
        """TLS context trusting the cluster CA, with the client certificate if any."""
        context = ssl.create_default_context(cafile=self.ca_file, cadata=self.ca_data)
        if self.client_cert_data and self.client_key_data:
            with tempfile.TemporaryDirectory() as tmp:
                cert = Path(tmp) / "client.crt"
                key = Path(tmp) / "client.key"
                cert.write_text(self.client_cert_data, encoding="utf-8")
                key.write_text(self.client_key_data, encoding="utf-8")
                os.chmod(key, 0o600)
                context.load_cert_chain(str(cert), str(key))
        return context

    def to_dict(self) -> dict[str, Any]:
        """Plain dict, for handing the config to the bridge process."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KubeConfig:
        """Inverse of :meth:`to_dict`."""
        return cls(**data)


def in_cluster_available() -> bool:
    """True inside a pod that has a ServiceAccount token mounted."""
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST")) and (SA_DIR / "token").is_file()


def _sandbox_namespace(default: str) -> str:
    return (os.environ.get(NAMESPACE_ENV) or "").strip() or default


def load_in_cluster() -> KubeConfig:
    """Config from the pod's ServiceAccount."""
    host = (os.environ.get("KUBERNETES_SERVICE_HOST") or "").strip()
    port = (os.environ.get("KUBERNETES_SERVICE_PORT") or "").strip() or "443"
    if not host or not (SA_DIR / "token").is_file():
        raise KubeConfigError("not running inside a Kubernetes pod with a ServiceAccount token")
    if ":" in host:
        host = f"[{host}]"
    own = (SA_DIR / "namespace").read_text(encoding="utf-8").strip()
    return KubeConfig(
        server=f"https://{host}:{port}",
        namespace=_sandbox_namespace(own),
        own_namespace=own,
        in_cluster=True,
        ca_file=str(SA_DIR / "ca.crt"),
        token_file=str(SA_DIR / "token"),
    )


def _named(items: object, name: object, kind: str) -> dict[str, Any]:
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("name") == name:
            value = item.get(kind)
            return value if isinstance(value, dict) else {}
    raise KubeConfigError(f"kubeconfig has no {kind} named {name!r}")


def _decoded(value: object) -> str | None:
    return base64.b64decode(str(value)).decode("utf-8") if value else None


def _file(value: object) -> str | None:
    return Path(str(value)).read_text(encoding="utf-8") if value else None


def load_kubeconfig(path: str | None = None) -> KubeConfig:
    """Config from the current context of a kubeconfig (token or client certificate)."""
    try:
        import yaml
    except ImportError as exc:
        raise KubeConfigError("reading a kubeconfig needs PyYAML") from exc
    raw = path or (os.environ.get("KUBECONFIG") or "").split(os.pathsep)[0]
    config_path = Path(raw) if raw else Path.home() / ".kube" / "config"
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise KubeConfigError(f"cannot read kubeconfig {config_path}: {exc}") from exc
    context = _named(data.get("contexts"), data.get("current-context"), "context")
    cluster = _named(data.get("clusters"), context.get("cluster"), "cluster")
    user = _named(data.get("users"), context.get("user"), "user")
    if cluster.get("insecure-skip-tls-verify"):
        raise KubeConfigError("the kubeconfig disables TLS verification; refusing to use it")
    if "exec" in user or "auth-provider" in user:
        raise KubeConfigError(
            "kubeconfig credential plugins (exec, auth-provider) are not supported; "
            "use a token or a client certificate"
        )
    token = user.get("token") or (_file(user.get("tokenFile")) or "").strip() or None
    cert = _decoded(user.get("client-certificate-data")) or _file(user.get("client-certificate"))
    key = _decoded(user.get("client-key-data")) or _file(user.get("client-key"))
    if not token and not (cert and key):
        raise KubeConfigError("the kubeconfig user has neither a token nor a client certificate")
    namespace = str(context.get("namespace") or "default")
    return KubeConfig(
        server=str(cluster.get("server") or "").rstrip("/"),
        namespace=_sandbox_namespace(namespace),
        own_namespace=namespace,
        in_cluster=False,
        ca_file=cluster.get("certificate-authority"),
        ca_data=_decoded(cluster.get("certificate-authority-data")),
        token=token,
        client_cert_data=cert,
        client_key_data=key,
    )
