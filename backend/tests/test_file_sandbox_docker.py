"""File sandbox against a real container: isolation, persistence, inspector, Code node.

Skipped unless Docker is reachable and the sandbox image (``HEYM_PYTHON_TOOL_IMAGE``
or the backend's own image) has the libraries from ``docker/sandbox-requirements.txt``.
"""

import os
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from app.services.code_python_executor import docker_available, resolve_sandbox_image
from app.services.file_sandbox.executor import build_payload, run_in_sandbox
from app.services.file_sandbox.manifest import DriveFileRef
from app.services.file_sandbox.scope import RunFileScope
from app.services.file_sandbox.workspace import FileWorkspace

_IMAGE_READY: bool | None = None


def _image_ready() -> bool:
    global _IMAGE_READY
    if _IMAGE_READY is None:
        image = resolve_sandbox_image() if docker_available() else None
        if image is None:
            _IMAGE_READY = False
        else:
            probe = subprocess.run(
                ["docker", "run", "--rm", "--entrypoint", "python", image, "-c", "import pandas"],
                capture_output=True,
                timeout=120,
            )
            _IMAGE_READY = probe.returncode == 0
    return _IMAGE_READY


def _ref(path: Path) -> DriveFileRef:
    return DriveFileRef(
        id=uuid.uuid4(),
        name=path.name,
        mime=None,
        size=path.stat().st_size,
        created_at=datetime.now(timezone.utc),
        source="manual upload",
        workflow_id=None,
        shared=False,
        storage_path=path,
    )


@unittest.skipUnless(_image_ready(), "Docker or the sandbox libraries are not available")
class RealSandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sales"
        sheet.append(["Region", "Amount"])
        for index in range(10):
            sheet.append([f"R{index}", index])
        self.xlsx = self.dir / "q3.xlsx"
        workbook.save(self.xlsx)
        self.ws = FileWorkspace.for_run(uuid.uuid4())
        self.ws.ensure()
        self.entry = self.ws.add_inputs([_ref(self.xlsx)])[0]

    def tearDown(self) -> None:
        self.ws.delete()
        self._tmp.cleanup()

    def _python(self, code: str):  # noqa: ANN202 - SandboxOutcome
        return run_in_sandbox(self.ws, build_payload("python", code=code))

    def test_inspector_runs_inside_the_sandbox(self) -> None:
        outcome = run_in_sandbox(
            self.ws,
            build_payload("inspect", target={"path": self.entry["path"], "name": "q3.xlsx"}),
        )
        self.assertTrue(outcome.success, outcome.error)
        self.assertEqual(outcome.result["sheet_names"], ["Sales"])

    def test_a_scanned_pdf_is_read_with_ocr_inside_the_sandbox(self) -> None:
        from PIL import Image, ImageDraw, ImageFont

        page = Image.new("RGB", (1240, 1754), "white")
        ImageDraw.Draw(page).text(
            (120, 200), "INVOICE TOTAL 18816", fill="black", font=ImageFont.load_default(size=64)
        )
        scan = self.dir / "scan.pdf"
        page.save(scan, "PDF", resolution=150)
        entry = self.ws.add_inputs([_ref(scan)])[-1]
        outcome = run_in_sandbox(
            self.ws, build_payload("inspect", target={"path": entry["path"], "name": "scan.pdf"})
        )
        self.assertTrue(outcome.success, outcome.error)
        self.assertNotIn("ocr_error", outcome.result)
        self.assertTrue(outcome.result["scanned"])
        self.assertTrue(outcome.result["pages"][0]["ocr"])
        self.assertIn("18816", outcome.result["pages"][0]["text"])

    def test_network_is_blocked(self) -> None:
        outcome = self._python(
            "import socket\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
            "    print('open')\n"
            "except OSError:\n"
            "    print('blocked')\n"
        )
        self.assertEqual(outcome.stdout.strip(), "blocked")

    def test_backend_secrets_never_reach_the_sandbox(self) -> None:
        secrets = {
            "SECRET_KEY": "s3cr3t",
            "ENCRYPTION_KEY": "k3y",
            "DATABASE_URL": "postgresql://x",
            "OPENAI_API_KEY": "sk-x",
        }
        with patch.dict(os.environ, secrets):
            outcome = self._python(
                "import os\nprint(sorted(k for k in "
                "('SECRET_KEY','ENCRYPTION_KEY','DATABASE_URL','OPENAI_API_KEY') if k in os.environ))"
            )
        self.assertEqual(outcome.stdout.strip(), "[]")

    def test_inputs_are_read_only_and_the_sandbox_is_unprivileged(self) -> None:
        outcome = self._python(
            "import os\n"
            "try:\n"
            f"    open({self.entry['path']!r}, 'a')\n"
            "    print('writable')\n"
            "except OSError:\n"
            "    print('read-only')\n"
            "print(os.getuid(), os.path.exists('/var/run/docker.sock'))\n"
        )
        self.assertEqual(outcome.stdout.split(), ["read-only", "65534", "False"])

    def test_work_persists_and_outputs_are_collected(self) -> None:
        first = self._python(
            "import heym_files, pandas as pd, os\n"
            "df = pd.read_excel(heym_files.path('q3.xlsx'))\n"
            "df.to_pickle('/work/sales.pkl')\n"
            "df.to_csv(os.path.join(heym_files.out_dir(), 'summary.csv'), index=False)\n"
            "print(int(df.Amount.sum()))\n"
        )
        self.assertTrue(first.success, first.error)
        self.assertEqual(first.stdout.strip(), "45")
        second = self._python("import pandas as pd\nprint(len(pd.read_pickle('/work/sales.pkl')))")
        self.assertEqual(second.stdout.strip(), "10")
        collected, rejected = self.ws.collect_outputs()
        self.assertEqual([c.name for c in collected], ["summary.csv"])
        self.assertEqual(rejected, [])

    def test_a_symlink_planted_in_out_is_not_collected(self) -> None:
        self._python("import os\nos.symlink('/etc/passwd', '/work/out/passwd.txt')")
        collected, rejected = self.ws.collect_outputs()
        self.assertEqual(collected, [])
        self.assertTrue(rejected)

    def test_writes_to_fd1_do_not_break_the_envelope(self) -> None:
        outcome = self._python("import os\nos.write(1, b'noise')\nprint('ok')")
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.stdout.strip(), "ok")

    def test_errors_come_back_as_tracebacks(self) -> None:
        outcome = self._python("raise ValueError('bad sheet')")
        self.assertFalse(outcome.success)
        self.assertIn("ValueError: bad sheet", outcome.error)

    def test_code_node_reads_files_and_writes_outputs(self) -> None:
        from app.services.file_sandbox import code_node

        stored = [{"id": "x", "name": "out.csv"}]
        with (
            patch.object(code_node, "resolve_files", return_value=[_ref(self.xlsx)]),
            patch.object(code_node, "store_outputs", return_value=(stored, [])) as store,
            patch("app.db.session.SessionLocal"),
        ):
            result = code_node.execute_code_with_files(
                code=(
                    "import heym_files, pandas as pd, os\n"
                    "def main(params):\n"
                    "    df = pd.read_excel(heym_files.path(params.files[0].name))\n"
                    "    df.to_csv(os.path.join(heym_files.out_dir(), 'out.csv'))\n"
                    "    return {'total': int(df.Amount.sum()), 'name': params.files[0].name}\n"
                ),
                requirements="",
                params={},
                allow_network=False,
                file_refs=["q3.xlsx"],
                actor_id=uuid.uuid4(),
                scope=RunFileScope(),
                workflow_id=None,
                source_label="code",
            )
        self.assertEqual(result.result, {"total": 45, "name": "q3.xlsx"})
        self.assertEqual(result.files, stored)
        self.assertEqual([c.name for c in store.call_args.args[0]], ["out.csv"])


if __name__ == "__main__":
    unittest.main()
