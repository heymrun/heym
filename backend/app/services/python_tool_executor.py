"""
Execute user-defined Python tool code with blacklist and timeout.
"""

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

BLACKLIST_BUILTINS = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "open",
        "input",
        "globals",
        "locals",
        "vars",
        "dir",
        "delattr",
        "setattr",
        "breakpoint",
        "exit",
        "quit",
        "help",
        "getattr",
        "memoryview",
        "bytearray",
        "super",
        "property",
        "staticmethod",
        "classmethod",
        "__build_class__",
    }
)

BLACKLIST_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "ftplib",
        "urllib",
        "http",
        "requests",
        "webbrowser",
        "ctypes",
        "pickle",
        "shelve",
        "marshal",
        "code",
        "codeop",
        "importlib",
        "runpy",
        "builtins",
        "posix",
        "nt",
        "pwd",
        "grp",
        "termios",
        "tty",
        "pty",
        "fcntl",
        "pipes",
        "resource",
        "signal",
        "threading",
        "multiprocessing",
        "traceback",
        "warnings",
        "ast",
        "dis",
        "inspect",
    }
)

_RUNNER_SCRIPT = '''
import json
import sys

BLACKLIST_BUILTINS = set(json.loads("""__BLACKLIST_BUILTINS__"""))
BLACKLIST_MODULES = set(json.loads("""__BLACKLIST_MODULES__"""))
_real_import = __import__

def _safe_import(name, *args, **kwargs):
    root = name.split(".")[0]
    if root in BLACKLIST_MODULES:
        raise ImportError(f"Module '{name}' is not allowed")
    return _real_import(name, *args, **kwargs)

def _create_safe_builtins():
    import builtins
    safe = {}
    for k, v in vars(builtins).items():
        if k not in BLACKLIST_BUILTINS:
            safe[k] = v
    safe["__import__"] = _safe_import
    return safe

def main():
    data = json.load(sys.stdin)
    code = data["code"]
    function_name = data["function_name"]
    arguments = data["arguments"]

    safe_builtins = _create_safe_builtins()
    namespace = {"__builtins__": safe_builtins}

    exec(code, namespace)
    fn = namespace.get(function_name)
    if fn is None:
        raise NameError(f"Function '{function_name}' not found in code")

    result = fn(**arguments)
    print(json.dumps({"success": True, "result": result}, default=str))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}, default=str))
    sys.exit(0)
'''


def _get_runner_script() -> str:
    bl_builtins = json.dumps(list(BLACKLIST_BUILTINS))
    bl_modules = json.dumps(list(BLACKLIST_MODULES))
    return _RUNNER_SCRIPT.replace("__BLACKLIST_BUILTINS__", bl_builtins).replace(
        "__BLACKLIST_MODULES__", bl_modules
    )


def execute_tool(
    code: str,
    function_name: str,
    arguments: dict,
    timeout_seconds: float = 30.0,
) -> object:
    """
    Execute user Python tool code with blacklist and timeout.

    Args:
        code: Python function code (e.g. "def count_characters(text: str): return len(text)")
        function_name: Name of the function to call
        arguments: Dict of keyword arguments to pass to the function
        timeout_seconds: Max execution time in seconds

    Returns:
        The return value of the function (must be JSON-serializable).

    Raises:
        TimeoutError: If execution exceeds timeout_seconds
        ValueError: If tool returns an error
    """
    payload = {
        "code": code,
        "function_name": function_name,
        "arguments": arguments,
    }
    payload_json = json.dumps(payload, default=str)

    runner = _get_runner_script()
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
    ) as f:
        f.write(runner)
        runner_path = f.name

    try:
        proc = subprocess.Popen(
            [sys.executable, runner_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(
                input=payload_json,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise TimeoutError(f"Tool execution timed out after {timeout_seconds} seconds")

        if stderr:
            logger.warning("Tool stderr: %s", stderr)

        try:
            out = json.loads(stdout.strip())
        except json.JSONDecodeError as e:
            raise ValueError(f"Tool output invalid: {stdout[:200]}") from e

        if not out.get("success") and "error" in out:
            raise ValueError(f"Tool error: {out['error']}")

        return out.get("result")
    finally:
        Path(runner_path).unlink(missing_ok=True)
