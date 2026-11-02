import json
import threading
import time
import unittest

from websockets.sync.server import serve

from app.services.sandbox.kubernetes.attach import (
    SUBPROTOCOL,
    exchange,
    exit_code_from_status,
    open_attach,
)
from app.services.sandbox.kubernetes.client import KubeClient
from app.services.sandbox.kubernetes.config import KubeConfig

_FAILURE = {
    "status": "Failure",
    "reason": "NonZeroExitCode",
    "details": {"causes": [{"reason": "ExitCode", "message": "3"}]},
}


def _echo_server(handler_log: list[str]):  # noqa: ANN202
    def handler(connection) -> None:  # noqa: ANN001
        handler_log.append(connection.subprotocol or "")
        data = b""
        while True:
            message = connection.recv()
            if message[0] == 0:
                data += message[1:]
            elif message[:2] == bytes([255, 0]):
                break
        connection.send(bytes([1]) + b"out:" + data)
        connection.send(bytes([2]) + b"err")
        connection.send(bytes([3]) + json.dumps(_FAILURE).encode())
        connection.close()

    server = serve(handler, "127.0.0.1", 0, subprotocols=[SUBPROTOCOL])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class AttachTest(unittest.TestCase):
    def test_stdin_eof_reaches_the_server_and_channels_split(self) -> None:
        log: list[str] = []
        server = _echo_server(log)
        self.addCleanup(server.shutdown)
        port = server.socket.getsockname()[1]
        config = KubeConfig(
            server=f"http://127.0.0.1:{port}", namespace="sb", own_namespace="sb", in_cluster=False
        )
        session = open_attach(KubeClient(config), "p")
        out, err, code = exchange(session, b"hello", time.monotonic() + 5)
        session.close()
        self.assertEqual(log, [SUBPROTOCOL])
        self.assertEqual((out, err, code), (b"out:hello", b"err", 3))

    def test_status_parsing(self) -> None:
        self.assertEqual(exit_code_from_status(b'{"status": "Success"}'), 0)
        self.assertEqual(exit_code_from_status(json.dumps(_FAILURE).encode()), 3)
        self.assertIsNone(exit_code_from_status(b"not json"))
