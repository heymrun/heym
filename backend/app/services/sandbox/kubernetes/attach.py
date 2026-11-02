"""The ``v5.channel.k8s.io`` attach protocol over a websocket.

Every binary message starts with a channel byte: 0 stdin, 1 stdout, 2 stderr,
3 status (a JSON ``metav1.Status``), 255 close. The close message, new in v5, is
the only way to give the container's stdin EOF, which every Heym runner waits for.
"""

from __future__ import annotations

import json
import time

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from app.services.sandbox.kubernetes.client import KubeClient

SUBPROTOCOL = "v5.channel.k8s.io"
STDIN, STDOUT, STDERR, STATUS, CLOSE = 0, 1, 2, 3, 255
_CHUNK = 32 * 1024


class AttachSession:
    """One attached container: send stdin, receive ``(channel, payload)`` frames."""

    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection

    def send_stdin(self, data: bytes) -> None:
        """Write to the container's stdin."""
        for start in range(0, len(data), _CHUNK):
            self._connection.send(bytes([STDIN]) + data[start : start + _CHUNK])

    def close_stdin(self) -> None:
        """Give the container's stdin EOF."""
        self._connection.send(bytes([CLOSE, STDIN]))

    def receive(self, timeout: float | None) -> tuple[int, bytes] | None:
        """The next frame, None once the server closed the stream. Raises TimeoutError."""
        try:
            message = self._connection.recv(timeout=timeout)
        except ConnectionClosed:
            return None
        if isinstance(message, str):
            message = message.encode("utf-8")
        if not message:
            return (-1, b"")
        return message[0], message[1:]

    def close(self) -> None:
        """Close the websocket."""
        self._connection.close()


def open_attach(client: KubeClient, pod_name: str) -> AttachSession:
    """Attach to the sandbox container of ``pod_name``."""
    url = client.attach_url(pod_name)
    token = client.config.bearer_token()
    connection = connect(
        url,
        ssl=client.config.ssl_context() if url.startswith("wss://") else None,
        additional_headers={"Authorization": f"Bearer {token}"} if token else None,
        subprotocols=[SUBPROTOCOL],
        max_size=None,
        open_timeout=30,
        ping_interval=None,
        proxy=None,
    )
    if connection.subprotocol != SUBPROTOCOL:
        connection.close()
        raise RuntimeError(
            f"the API server did not accept {SUBPROTOCOL}; Kubernetes 1.30 or newer is required"
        )
    return AttachSession(connection)


def exit_code_from_status(payload: bytes) -> int | None:
    """Exit code from a channel-3 ``metav1.Status`` message, if it carries one."""
    try:
        status = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(status, dict):
        return None
    if status.get("status") == "Success":
        return 0
    for cause in (status.get("details") or {}).get("causes") or []:
        if isinstance(cause, dict) and cause.get("reason") == "ExitCode":
            try:
                return int(cause.get("message"))
            except (TypeError, ValueError):
                return None
    return None


def exchange(
    session: AttachSession, stdin: bytes | None, deadline: float
) -> tuple[bytes, bytes, int | None]:
    """Send ``stdin`` then EOF; collect stdout, stderr and the status exit code.

    Raises TimeoutError when ``deadline`` (``time.monotonic()``) passes.
    """
    if stdin:
        session.send_stdin(stdin)
    session.close_stdin()
    out, err = bytearray(), bytearray()
    code: int | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        frame = session.receive(timeout=remaining)
        if frame is None:
            return bytes(out), bytes(err), code
        channel, payload = frame
        if channel == STDOUT:
            out.extend(payload)
        elif channel == STDERR:
            err.extend(payload)
        elif channel == STATUS:
            code = exit_code_from_status(payload)
