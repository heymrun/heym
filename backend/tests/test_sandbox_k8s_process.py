import io
import signal
import unittest
from unittest.mock import MagicMock, patch

from app.services.sandbox.kubernetes import process
from app.services.sandbox.kubernetes.lifecycle import PodExit, PodStart

MANIFEST = {"metadata": {"name": "heym-mcp-stdio-1"}}


class _Session:
    def __init__(self, frames: list) -> None:
        self.frames = list(frames)
        self.sent: list[bytes] = []
        self.closed_stdin = False

    def send_stdin(self, data: bytes) -> None:
        self.sent.append(data)

    def close_stdin(self) -> None:
        self.closed_stdin = True

    def receive(self, timeout):  # noqa: ANN001, ANN201
        return self.frames.pop(0) if self.frames else None

    def close(self) -> None:
        pass


class BridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        for caught in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self.addCleanup(signal.signal, caught, signal.getsignal(caught))

    def test_pumps_both_ways_and_returns_the_exit_code(self) -> None:
        session = _Session([(1, b'{"jsonrpc":"2.0"}\n'), (2, b"log\n")])
        client = MagicMock()
        stdout, stderr = io.BytesIO(), io.BytesIO()
        with (
            patch.object(process, "wait_started", return_value=PodStart("running")),
            patch.object(process, "open_gated_attach", return_value=session),
            patch.object(process, "wait_terminated", return_value=PodExit(0)),
        ):
            code = process.run_attached(
                client,
                MANIFEST,
                start_gate=True,
                stdin=io.BytesIO(b"request\n"),
                stdout=stdout,
                stderr=stderr,
            )
            process.join_stdin_pump()
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), b'{"jsonrpc":"2.0"}\n')
        self.assertEqual(stderr.getvalue(), b"log\n")
        self.assertEqual(session.sent[0], b"\n")
        self.assertIn(b"request\n", session.sent)
        self.assertTrue(session.closed_stdin)
        client.delete_pod.assert_called_once_with("heym-mcp-stdio-1")

    def test_start_failure_reports_and_deletes(self) -> None:
        client = MagicMock()
        stderr = io.BytesIO()
        with patch.object(
            process, "wait_started", return_value=PodStart("failed", "ErrImagePull: x")
        ):
            code = process.run_attached(
                client,
                MANIFEST,
                start_gate=False,
                stdin=io.BytesIO(),
                stdout=io.BytesIO(),
                stderr=stderr,
            )
        self.assertEqual(code, 125)
        self.assertIn(b"ErrImagePull", stderr.getvalue())
        client.delete_pod.assert_called_once()
