"""Every sandbox pod is Pod Security ``restricted`` and carries no backend secret.

Builds the real spec of every call site and renders it as a pod, so a new site or a
changed spec cannot quietly loosen the boundary.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import (
    code_formatter,
    code_python_executor,
    mcp_stdio_sandbox,
    playwright_sandbox,
    python_tool_executor,
    skill_python_executor,
)
from app.services.sandbox.coding_agents import CODEX, OPENCODE, agent_spec, run_scope
from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.pod import PodContext, build_pod, parse_overrides

SECRETS = {
    "SECRET_KEY": "advisory-secret-key",
    "ENCRYPTION_KEY": "advisory-encryption-key",
    "DATABASE_URL": "postgresql://advisory",
    "OPENAI_API_KEY": "sk-advisory",
}
RUN = "0123456789abcdef0123456789abcdef"


def _all_specs() -> dict:
    root = Path(tempfile.mkdtemp()).resolve()
    for name in (RUN, f"{RUN}.codex-home", f"{RUN}.oc-home"):
        (root / name).mkdir()
    codex_env = {"HEYM_CODEX_WORKSPACE_DIR": str(root), "CODEX_HOME": f"{root}/{RUN}.codex-home"}
    oc_env = {"HEYM_OPENCODE_WORKSPACE_DIR": str(root), "HOME": f"{root}/{RUN}.oc-home"}
    return {
        "pytool": python_tool_executor._tool_spec("img", "n"),
        "formatter": code_formatter._format_spec("img", "n"),
        "code_run": code_python_executor._run_spec("img", "n", False, (), None),
        "code_install": code_python_executor._install_spec("img", "n", (), Path("/r"), "uv"),
        "playwright": playwright_sandbox._playwright_spec("img", "n"),
        "skill": skill_python_executor._skill_spec("img", "n", root, root / RUN, "main.py"),
        "mcp": mcp_stdio_sandbox._mcp_spec(
            name="n", image="img", entrypoint="npx", args=[], workdir="/tmp", extra_env=[]
        ),
        "codex": agent_spec(
            CODEX,
            run_scope(CODEX, root / RUN, codex_env),
            [],
            codex_env,
            image="img",
            name="n",
            kubernetes=True,
            cwd=root / RUN,
        ),
        "opencode": agent_spec(
            OPENCODE,
            run_scope(OPENCODE, root / RUN, oc_env),
            [],
            oc_env,
            image="img",
            name="n",
            kubernetes=True,
            cwd=root / RUN,
        ),
    }


class RestrictedPodAdvisoryTest(unittest.TestCase):
    def test_every_site_pod_is_restricted_and_secret_free(self) -> None:
        with patch.dict(os.environ, SECRETS):
            specs = _all_specs()
        for site, spec in specs.items():
            with self.subTest(site):
                pod = build_pod(spec, PodContext(instance="heym-0"))
                pod_spec = pod["spec"]
                self.assertFalse(pod_spec["automountServiceAccountToken"])
                for key in ("hostNetwork", "hostPID", "hostIPC"):
                    self.assertNotIn(key, pod_spec)
                self.assertTrue(all("hostPath" not in v for v in pod_spec["volumes"]))
                self.assertTrue(pod_spec["securityContext"]["runAsNonRoot"])
                self.assertGreater(pod_spec["securityContext"]["runAsUser"], 0)
                self.assertGreater(pod_spec["activeDeadlineSeconds"], 0)
                for container in pod_spec["containers"]:
                    context = container["securityContext"]
                    self.assertFalse(context["allowPrivilegeEscalation"])
                    self.assertEqual(context["capabilities"], {"drop": ["ALL"]})
                    self.assertNotIn("privileged", context)
                dumped = json.dumps(pod)
                for value in SECRETS.values():
                    self.assertNotIn(value, dumped)

    def test_overrides_cannot_touch_security(self) -> None:
        for key in (
            "securityContext",
            "hostNetwork",
            "hostPID",
            "volumes",
            "containers",
            "serviceAccountName",
            "automountServiceAccountToken",
        ):
            with self.subTest(key), self.assertRaises(SandboxConfigError):
                parse_overrides(json.dumps({key: True}))
