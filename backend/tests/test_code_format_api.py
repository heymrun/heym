import subprocess
import unittest
from unittest.mock import MagicMock, patch

from app.services import code_formatter


class BuildFormatCommandTest(unittest.TestCase):
    def test_format_container_is_hardened_and_offline(self) -> None:
        cmd = code_formatter._build_format_command(image="img", name="heym-fmt-abc")
        self.assertIn("--rm", cmd)
        self.assertIn("--read-only", cmd)
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")
        self.assertEqual(cmd[cmd.index("--cap-drop") + 1], "ALL")
        self.assertEqual(cmd[cmd.index("--security-opt") + 1], "no-new-privileges")
        self.assertEqual(cmd[cmd.index("--user") + 1], "65534:65534")
        self.assertEqual(cmd[cmd.index("--memory") + 1], "512m")
        self.assertEqual(cmd[cmd.index("--pids-limit") + 1], "256")
        self.assertNotIn("docker.sock", " ".join(cmd))

    def test_backend_secrets_are_not_passed_to_the_container(self) -> None:
        with patch.dict(
            "os.environ",
            {"SECRET_KEY": "jwt-key", "DATABASE_URL": "postgresql://u:p@db/x"},
        ):
            cmd = code_formatter._build_format_command(image="img", name="n")
        joined = " ".join(cmd)
        self.assertNotIn("jwt-key", joined)
        self.assertNotIn("postgresql://", joined)

    def test_ruff_runs_isolated_from_any_config_file(self) -> None:
        cmd = code_formatter._build_format_command(image="img", name="n")
        script = cmd[-1] if cmd[-1].startswith("for ") else " ".join(cmd)
        self.assertIn("--isolated", script)
        self.assertIn("format", script)

    def test_both_image_layouts_are_probed(self) -> None:
        script = " ".join(code_formatter._build_format_command(image="img", name="n"))
        self.assertIn("/app/.venv/bin/ruff", script)
        self.assertIn("/app/backend/.venv/bin/ruff", script)


class NormalizeSourceTest(unittest.TestCase):
    """Pasted code is repaired before Ruff sees it, instead of being rejected."""

    def test_a_uniformly_indented_paste_is_dedented(self) -> None:
        source = "    def main(params):\n        return 1\n"
        self.assertEqual(
            code_formatter._normalize_source(source), "def main(params):\n    return 1\n"
        )

    def test_leading_blank_lines_are_dropped_before_dedenting(self) -> None:
        source = "\n\n def main(params):\n     return 1\n"
        self.assertEqual(
            code_formatter._normalize_source(source), "def main(params):\n    return 1\n"
        )

    def test_leading_tabs_become_spaces_so_mixed_indentation_parses(self) -> None:
        source = "def main(params):\n    x = 1\n\ty = 2\n\treturn x\n"
        normalized = code_formatter._normalize_source(source)
        self.assertNotIn("\t", normalized)

    def test_tabs_inside_string_literals_are_preserved(self) -> None:
        source = 'def main(params):\n    return "a\\tb"\n'
        self.assertIn('"a\\tb"', code_formatter._normalize_source(source))

    def test_crlf_becomes_lf(self) -> None:
        self.assertEqual(
            code_formatter._normalize_source("def main(params):\r\n    return 1\r\n"),
            "def main(params):\n    return 1\n",
        )

    def test_well_formed_code_is_left_alone(self) -> None:
        source = 'def main(params):\n    return {"a": 1}\n'
        self.assertEqual(code_formatter._normalize_source(source), source)

    def test_a_missing_trailing_newline_is_added(self) -> None:
        self.assertEqual(
            code_formatter._normalize_source("def main(params):\n    return 1"),
            "def main(params):\n    return 1\n",
        )


class RepairIndentationTest(unittest.TestCase):
    """A near-miss indent is a typo, not a reason to refuse to format."""

    def test_one_stray_space_snaps_to_the_established_level(self) -> None:
        source = (
            "def main(params):\n"
            "     name = params.name\n"
            "    number = params.number\n"
            "    return name\n"
        )
        repaired = code_formatter._repair_indentation(source)
        self.assertIsNotNone(repaired)
        compile(repaired, "<repaired>", "exec")

    def test_bracket_continuations_are_left_alone(self) -> None:
        source = (
            "def main(params):\n"
            "     name = params.name\n"
            "    return {\n"
            '        "name": name,\n'
            "    }\n"
        )
        repaired = code_formatter._repair_indentation(source)
        self.assertIsNotNone(repaired)
        compile(repaired, "<repaired>", "exec")
        self.assertIn('        "name": name,', repaired)

    def test_lines_inside_a_triple_quoted_string_are_untouched(self) -> None:
        source = 'def main(params):\n     doc = """\n  keep\n    this\n"""\n     return doc\n'
        repaired = code_formatter._repair_indentation(source)
        if repaired is not None:
            self.assertIn("\n  keep\n", repaired)

    def test_well_formed_code_reports_no_repair(self) -> None:
        source = "def main(params):\n    return 1\n"
        self.assertIsNone(code_formatter._repair_indentation(source))

    def test_an_equally_plausible_pair_of_blocks_is_refused(self) -> None:
        # Levels 0 and 8 are established; a line at 4 is exactly between them,
        # so snapping either way would move the statement to a different block.
        source = "def main(params):\n        deep = 1\n    tied = 2\n        return deep\n"
        self.assertIsNone(code_formatter._repair_indentation(source))

    def test_an_indent_far_from_every_level_is_refused(self) -> None:
        source = "def main(params):\n    a = 1\n              b = 2\n    return a\n"
        repaired = code_formatter._repair_indentation(source)
        self.assertIsNone(repaired)

    def test_comment_lines_do_not_establish_a_level(self) -> None:
        source = "def main(params):\n        # note\n    return 1\n"
        self.assertIsNone(code_formatter._repair_indentation(source))


class FormatPythonTest(unittest.TestCase):
    def setUp(self) -> None:
        self._docker = patch.object(code_formatter, "docker_available", return_value=True)
        self._image = patch.object(code_formatter, "resolve_sandbox_image", return_value="img")
        self._docker.start()
        self._image.start()

    def tearDown(self) -> None:
        patch.stopall()

    @staticmethod
    def _sandbox(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
        return MagicMock(return_value=(returncode, stdout, stderr))

    def test_formatted_source_comes_back_from_the_sandbox(self) -> None:
        with patch.object(
            code_formatter, "run_sandbox_container", self._sandbox('x = {"a": 1}\n')
        ) as run:
            out = code_formatter.format_python('x={"a":1}\n')
        self.assertEqual(out, 'x = {"a": 1}\n')
        self.assertEqual(run.call_args.args[1], 'x={"a":1}\n')

    def test_blank_source_never_starts_a_container(self) -> None:
        with patch.object(code_formatter, "run_sandbox_container") as run:
            self.assertEqual(code_formatter.format_python("   "), "   ")
        run.assert_not_called()

    def test_oversized_source_is_rejected_before_starting_a_container(self) -> None:
        with patch.object(code_formatter, "run_sandbox_container") as run:
            with self.assertRaises(ValueError) as ctx:
                code_formatter.format_python("x = 1\n" * 200_000)
        run.assert_not_called()
        self.assertIn("too large", str(ctx.exception).lower())

    def test_syntax_error_is_reported_as_a_readable_location(self) -> None:
        failure = self._sandbox(
            "", "error: Failed to parse code.py:2:5: Expected an expression", returncode=2
        )
        with patch.object(code_formatter, "run_sandbox_container", failure):
            with self.assertRaises(ValueError) as ctx:
                code_formatter.format_python("def main(params:\n    return 1\n")
        self.assertEqual(str(ctx.exception), "Line 2, column 5: Expected an expression")

    def test_missing_ruff_in_the_image_fails_closed(self) -> None:
        missing = self._sandbox("", "ruff not found in the sandbox image", returncode=127)
        with patch.object(code_formatter, "run_sandbox_container", missing):
            with self.assertRaises(RuntimeError) as ctx:
                code_formatter.format_python("x=1\n")
        self.assertIn("ruff", str(ctx.exception).lower())

    def test_no_docker_fails_closed_without_formatting_on_the_host(self) -> None:
        patch.stopall()
        with patch.object(code_formatter, "docker_available", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                code_formatter.format_python("x=1\n")
        self.assertIn("docker", str(ctx.exception).lower())

    def test_timeout_is_reported(self) -> None:
        expired = TimeoutError("Code node formatting timed out after 20 seconds")
        with patch.object(code_formatter, "run_sandbox_container", side_effect=expired):
            with self.assertRaises(RuntimeError) as ctx:
                code_formatter.format_python("x=1\n")
        self.assertIn("timed out", str(ctx.exception).lower())

    def test_host_ruff_is_never_invoked(self) -> None:
        with (
            patch.object(code_formatter, "run_sandbox_container", self._sandbox("x = 1\n")),
            patch.object(subprocess, "run") as host_run,
        ):
            code_formatter.format_python("x=1\n")
        host_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
