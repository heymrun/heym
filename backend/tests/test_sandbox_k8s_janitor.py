import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.services.sandbox.kubernetes.janitor import sweep

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _pod(name: str, phase: str, age_minutes: int, instance: str = "heym-0") -> dict:
    created = (NOW - timedelta(minutes=age_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "metadata": {
            "name": name,
            "creationTimestamp": created,
            "labels": {"heym.run/instance": instance},
        },
        "status": {"phase": phase},
    }


class SweepTest(unittest.TestCase):
    def _client(self, pods: list[dict], live_instances: set[str]) -> MagicMock:
        client = MagicMock()
        client.list_pods.return_value = pods
        client.config.own_namespace = "heym"
        client.get_pod.side_effect = lambda name, namespace=None: (
            {} if name in live_instances else None
        )
        return client

    def test_finished_pods_go_after_the_grace_period(self) -> None:
        client = self._client([_pod("old", "Succeeded", 30), _pod("new", "Failed", 1)], {"heym-0"})
        self.assertEqual(sweep(client, in_cluster=True, now=NOW), ["old"])

    def test_running_pods_of_a_dead_instance_go_in_cluster_only(self) -> None:
        pods = [_pod("orphan", "Running", 5, "heym-gone"), _pod("live", "Running", 5, "heym-0")]
        self.assertEqual(
            sweep(self._client(pods, {"heym-0"}), in_cluster=True, now=NOW), ["orphan"]
        )
        self.assertEqual(sweep(self._client(pods, {"heym-0"}), in_cluster=False, now=NOW), [])
