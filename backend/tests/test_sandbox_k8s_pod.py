import unittest

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.pod import (
    PodContext,
    PodVolume,
    build_pod,
    env_entries,
    parse_overrides,
    quantity,
    run_as,
)
from app.services.sandbox.spec import SandboxSpec, Tmpfs

CTX = PodContext(instance="heym-backend-0")


def _spec(**kwargs) -> SandboxSpec:  # noqa: ANN003
    base = dict(
        site="pytool",
        name="heym-pytool-1",
        image="img",
        entrypoint="python",
        args=("-c", "x"),
        tmpfs=(Tmpfs("/tmp", "rw,nosuid", "64m"),),
        memory="256m",
        cpus="1",
    )
    base.update(kwargs)
    return SandboxSpec(**base)


class PodTest(unittest.TestCase):
    def test_restricted_baseline(self) -> None:
        pod = build_pod(_spec(), CTX)
        spec = pod["spec"]
        container = spec["containers"][0]
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertFalse(spec["enableServiceLinks"])
        self.assertEqual(spec["restartPolicy"], "Never")
        self.assertEqual(spec["securityContext"]["runAsUser"], 65534)
        self.assertEqual(spec["securityContext"]["seccompProfile"], {"type": "RuntimeDefault"})
        self.assertEqual(container["securityContext"]["capabilities"], {"drop": ["ALL"]})
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(container["stdin"] and container["stdinOnce"])
        self.assertEqual(container["command"], ["python"])
        self.assertEqual(container["resources"]["limits"], {"memory": "256Mi", "cpu": "1"})
        self.assertEqual(spec["volumes"][0]["emptyDir"], {"medium": "Memory", "sizeLimit": "64Mi"})
        self.assertEqual(pod["metadata"]["labels"]["heym.run/network"], "none")
        self.assertEqual(spec["activeDeadlineSeconds"], 86400)

    def test_privileged_spec_fields_never_reach_the_pod(self) -> None:
        pod = build_pod(
            _spec(
                user=None,
                cap_drop_all=False,
                no_new_privileges=False,
                docker_extra_args=("--cap-add", "SYS_ADMIN"),
                network="bridge",
            ),
            CTX,
        )
        container = pod["spec"]["containers"][0]
        self.assertEqual(container["securityContext"]["capabilities"], {"drop": ["ALL"]})
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(pod["spec"]["securityContext"]["runAsUser"], 65534)
        self.assertEqual(pod["metadata"]["labels"]["heym.run/network"], "egress")

    def test_openshift_lets_the_scc_pick_the_uid(self) -> None:
        pod = build_pod(_spec(), PodContext(instance="i", openshift=True))
        self.assertNotIn("runAsUser", pod["spec"]["securityContext"])
        self.assertTrue(pod["spec"]["securityContext"]["runAsNonRoot"])

    def test_start_gate_and_image_default_entrypoint(self) -> None:
        gated = build_pod(_spec(entrypoint="codex", args=("exec",), start_gate=True), CTX)
        self.assertEqual(
            gated["spec"]["containers"][0]["command"][:3],
            ["sh", "-c", 'head -c1 >/dev/null; exec "$@"'],
        )
        self.assertEqual(gated["spec"]["containers"][0]["args"], ["exec"])
        plain = build_pod(_spec(entrypoint=None, args=("serve",)), CTX)
        self.assertNotIn("command", plain["spec"]["containers"][0])

    def test_volumes_share_one_claim_and_mount_subpaths(self) -> None:
        pod = build_pod(
            _spec(),
            CTX,
            (
                PodVolume("data", "codex-workspaces/a", "/w/a", False),
                PodVolume("data", "codex-workspaces/a.codex-home", "/w/a.codex-home", True),
            ),
        )
        claims = [v for v in pod["spec"]["volumes"] if "persistentVolumeClaim" in v]
        self.assertEqual(len(claims), 1)
        mounts = pod["spec"]["containers"][0]["volumeMounts"]
        self.assertIn(
            {
                "name": "ws-0",
                "mountPath": "/w/a.codex-home",
                "subPath": "codex-workspaces/a.codex-home",
                "readOnly": True,
            },
            mounts,
        )

    def test_helpers(self) -> None:
        self.assertEqual(
            [quantity(v) for v in ("512m", "1g", "64k", "1024")], ["512Mi", "1Gi", "64Ki", "1024"]
        )
        self.assertEqual(run_as("1000:2000"), (1000, 2000))
        self.assertEqual(run_as("0:0"), (65534, 65534))
        self.assertEqual(run_as("nobody"), (65534, 65534))
        self.assertEqual(
            env_entries(("A=1", "BARE", "A=2", "B=x=y")),
            [
                {"name": "A", "value": "2"},
                {"name": "B", "value": "x=y"},
                {"name": "HOME", "value": "/tmp"},
            ],
        )

    def test_overrides_allow_scheduling_keys_only(self) -> None:
        self.assertEqual(
            parse_overrides('{"runtimeClassName": "gvisor"}'), {"runtimeClassName": "gvisor"}
        )
        for raw in (
            '{"hostNetwork": true}',
            '{"securityContext": {}}',
            '{"volumes": []}',
            "[]",
            "{bad",
        ):
            with self.subTest(raw), self.assertRaises(SandboxConfigError):
                parse_overrides(raw)
        pod = build_pod(
            _spec(), PodContext(instance="i", overrides={"nodeSelector": {"pool": "sb"}})
        )
        self.assertEqual(pod["spec"]["nodeSelector"], {"pool": "sb"})
