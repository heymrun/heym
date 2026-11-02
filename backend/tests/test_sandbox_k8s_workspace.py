import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.workspace import (
    ClaimMount,
    claim_mounts,
    placement_node,
    resolve_volume,
)

BACKEND_POD = {
    "spec": {
        "nodeName": "node-a",
        "volumes": [
            {"name": "data", "persistentVolumeClaim": {"claimName": "heym-data"}},
            {"name": "oc", "persistentVolumeClaim": {"claimName": "heym-opencode"}},
            {"name": "tmp", "emptyDir": {}},
        ],
        "containers": [
            {
                "name": "heym",
                "volumeMounts": [
                    {"name": "data", "mountPath": "/app/data"},
                    {"name": "oc", "mountPath": "/app/data/opencode-workspaces", "subPath": "ws"},
                    {"name": "tmp", "mountPath": "/tmp"},
                ],
            }
        ],
    }
}


class WorkspaceTest(unittest.TestCase):
    def test_claim_mounts_skip_non_pvc_volumes(self) -> None:
        self.assertEqual(
            claim_mounts(BACKEND_POD),
            [
                ClaimMount("/app/data", "heym-data", ""),
                ClaimMount("/app/data/opencode-workspaces", "heym-opencode", "ws"),
            ],
        )

    def test_longest_prefix_wins_and_subpaths_nest(self) -> None:
        mounts = claim_mounts(BACKEND_POD)
        code = resolve_volume(mounts, Path("/app/data/codex-workspaces/_code-runs/abc"), "/x", True)
        self.assertEqual(
            (code.claim, code.sub_path, code.readonly),
            ("heym-data", "codex-workspaces/_code-runs/abc", True),
        )
        oc = resolve_volume(mounts, Path("/app/data/opencode-workspaces/r1"), "/y", False)
        self.assertEqual((oc.claim, oc.sub_path), ("heym-opencode", "ws/r1"))

    def test_refuses_paths_off_any_claim_and_whole_claims(self) -> None:
        mounts = claim_mounts(BACKEND_POD)
        with self.assertRaisesRegex(SandboxConfigError, "not on a PersistentVolumeClaim"):
            resolve_volume(mounts, Path("/tmp/heym-code-runs/abc"), "/x", False)
        with self.assertRaisesRegex(SandboxConfigError, "whole claim"):
            resolve_volume(mounts, Path("/app/data"), "/x", False)

    def test_placement_by_access_mode(self) -> None:
        client = MagicMock()
        client.namespace = "heym"
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteMany"]}}
        self.assertIsNone(placement_node(client, {"heym-data"}, BACKEND_POD))
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteOnce"]}}
        self.assertEqual(placement_node(client, {"heym-data"}, BACKEND_POD), "node-a")
        client.get_pvc.return_value = {"status": {"accessModes": ["ReadWriteOncePod"]}}
        with self.assertRaises(SandboxConfigError):
            placement_node(client, {"heym-data"}, BACKEND_POD)
        client.get_pvc.return_value = None
        with self.assertRaisesRegex(SandboxConfigError, "does not exist"):
            placement_node(client, {"heym-data"}, BACKEND_POD)
