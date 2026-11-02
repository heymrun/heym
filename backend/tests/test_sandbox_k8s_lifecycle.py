import unittest
from unittest.mock import MagicMock

from app.services.sandbox.kubernetes.lifecycle import wait_started, wait_terminated


def _pod(state: dict | None = None, phase: str = "Pending", conditions: list | None = None) -> dict:
    statuses = [{"name": "sandbox", "state": state}] if state is not None else []
    return {
        "status": {"phase": phase, "containerStatuses": statuses, "conditions": conditions or []}
    }


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _client(*pods: dict | None) -> MagicMock:
    client = MagicMock()
    client.get_pod.side_effect = list(pods)
    return client


class WaitStartedTest(unittest.TestCase):
    def _wait(self, client: MagicMock, timeout: float = 120.0):  # noqa: ANN202
        clock = _Clock()
        return wait_started(client, "p", timeout=timeout, sleep=clock.sleep, clock=clock)

    def test_running_after_creating(self) -> None:
        client = _client(_pod({"waiting": {"reason": "ContainerCreating"}}), _pod({"running": {}}))
        self.assertEqual(self._wait(client).state, "running")

    def test_image_pull_failure_is_a_start_failure(self) -> None:
        client = _client(
            _pod({"waiting": {"reason": "ImagePullBackOff", "message": "no such image"}})
        )
        start = self._wait(client)
        self.assertEqual(start.state, "failed")
        self.assertIn("ImagePullBackOff", start.reason)

    def test_start_error_is_a_start_failure(self) -> None:
        client = _client(_pod({"terminated": {"reason": "StartError", "exitCode": 128}}))
        self.assertEqual(self._wait(client).state, "failed")

    def test_finished_before_attach(self) -> None:
        client = _client(_pod({"terminated": {"reason": "Completed", "exitCode": 0}}))
        self.assertEqual(self._wait(client).state, "terminated")

    def test_unschedulable_times_out_with_the_reason(self) -> None:
        unschedulable = _pod(
            conditions=[
                {
                    "type": "PodScheduled",
                    "status": "False",
                    "reason": "Unschedulable",
                    "message": "0/1 nodes",
                }
            ]
        )
        client = MagicMock()
        client.get_pod.return_value = unschedulable
        start = self._wait(client, timeout=1.0)
        self.assertEqual(start.state, "failed")
        self.assertIn("Unschedulable", start.reason)


class WaitTerminatedTest(unittest.TestCase):
    def test_exit_code_and_oom(self) -> None:
        clock = _Clock()
        done = wait_terminated(
            _client(_pod({"running": {}}), _pod({"terminated": {"exitCode": 3}})),
            "p",
            sleep=clock.sleep,
            clock=clock,
        )
        self.assertEqual(done.code, 3)
        oom = wait_terminated(
            _client(_pod({"terminated": {"exitCode": 1, "reason": "OOMKilled"}})),
            "p",
            sleep=clock.sleep,
            clock=clock,
        )
        self.assertEqual(oom.code, 137)
