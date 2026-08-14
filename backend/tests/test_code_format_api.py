import subprocess
import unittest
from unittest.mock import MagicMock, patch

from app.services import code_formatter


class FormatPythonTest(unittest.TestCase):
    def test_formats_and_keeps_comments(self) -> None:
        source = 'def main(params):\n    # keep me\n    x={"a":1,   "b":2}\n    return   x\n'
        formatted = code_formatter.format_python(source)
        self.assertIn("# keep me", formatted)
        self.assertIn('x = {"a": 1, "b": 2}', formatted)
        self.assertIn("return x", formatted)

    def test_already_formatted_code_is_unchanged(self) -> None:
        source = 'def main(params):\n    return {"ok": True}\n'
        self.assertEqual(code_formatter.format_python(source), source)

    def test_blank_source_is_returned_as_is(self) -> None:
        self.assertEqual(code_formatter.format_python("   "), "   ")

    def test_syntax_error_raises_with_the_reason(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            code_formatter.format_python("def main(params:\n    return 1\n")
        self.assertTrue(str(ctx.exception))

    def test_oversized_source_is_rejected_before_spawning_ruff(self) -> None:
        oversized = "x = 1\n" * 200_000
        with patch.object(code_formatter.subprocess, "run") as run:
            with self.assertRaises(ValueError) as ctx:
                code_formatter.format_python(oversized)
        run.assert_not_called()
        self.assertIn("too large", str(ctx.exception).lower())

    def test_missing_ruff_reports_a_clear_error(self) -> None:
        with patch.object(code_formatter.subprocess, "run", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError) as ctx:
                code_formatter.format_python("x=1\n")
        self.assertIn("ruff", str(ctx.exception).lower())

    def test_timeout_reports_a_clear_error(self) -> None:
        expired = subprocess.TimeoutExpired(cmd="ruff", timeout=10)
        with patch.object(code_formatter.subprocess, "run", side_effect=expired):
            with self.assertRaises(RuntimeError) as ctx:
                code_formatter.format_python("x=1\n")
        self.assertIn("timed out", str(ctx.exception).lower())

    def test_ruff_is_invoked_in_stdin_format_mode(self) -> None:
        completed = MagicMock(returncode=0, stdout="x = 1\n", stderr="")
        with patch.object(code_formatter.subprocess, "run", return_value=completed) as run:
            code_formatter.format_python("x=1\n")
        cmd = run.call_args.args[0]
        self.assertIn("format", cmd)
        self.assertEqual(cmd[-1], "-")
        self.assertIn("--stdin-filename", cmd)


if __name__ == "__main__":
    unittest.main()
