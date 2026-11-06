"""Security regression tests: Playwright navigation is limited to http and https.

GHSA-hmfh-wpg2-vff4. Step-based Playwright scripts run inside the backend, and the
``navigate`` step and the AI step loop passed their URL straight to ``page.goto``. A
``file://`` URL followed by ``getText`` returned any backend file whose path was known,
including the Kubernetes ServiceAccount token. The generated script now checks the
scheme right before every ``page.goto``, after templates and AI output are resolved.

These tests run the generated script against a stand-in for Playwright, so they need no
browser.
"""

import ast
import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.nodes.playwright_node import _build_playwright_script
from app.services.playwright_code_generator import (
    _heym_navigable_url,
    generate_playwright_code,
)

_REJECTION = "only allows http and https"

_REJECTED_URLS = [
    "file:///var/run/secrets/kubernetes.io/serviceaccount/token",
    "FILE:///etc/passwd",
    "File:///etc/passwd",
    " file:///etc/passwd",
    "\tfile:///etc/passwd",
    "\x00file:///etc/passwd",
    "fi\nle:///etc/passwd",
    "fi\tle:///etc/passwd",
    "file:/etc/passwd",
    "file:etc/passwd",
    "file://localhost/etc/passwd",
    "view-source:file:///etc/passwd",
    "/etc/passwd",
    "etc/passwd",
    "//host/share",
    "",
    "data:text/html,<script>alert(1)</script>",
    "javascript:alert(1)",
    "about:blank",
    "chrome://settings",
    "ftp://example.com/x",
    "blob:https://example.com/uuid",
    "filesystem:https://example.com/temporary/x",
    "http://[::1",
]

_ACCEPTED_URLS = [
    "http://example.com",
    "https://example.com/path?q=1#frag",
    "HTTPS://EXAMPLE.COM",
    "https://user:pass@example.com:8443/",
    "http://127.0.0.1:8080/",
    "https://example.com/file:///etc/passwd",
]

# Playwright prefixes http:// to these itself (helper.completeUserURL), so they work
# today without a scheme and must keep working. Maps each input to what page.goto gets.
_SCHEMELESS_LOCAL_URLS = {
    "localhost:3000": "http://localhost:3000",
    "localhost:3000/path?q=1": "http://localhost:3000/path?q=1",
    "localhost": "http://localhost",
    "127.0.0.1:8080/x": "http://127.0.0.1:8080/x",
    "127.0.0.1": "http://127.0.0.1",
}

# Playwright does not prefix these either: its check is a raw, case-sensitive startsWith.
_REJECTED_URLS += [
    " localhost:3000",
    "LOCALHOST:3000",
    "file://localhost:3000/etc/passwd",
]


class NavigableUrlTests(unittest.TestCase):
    """The check itself, as it is copied into every generated script."""

    def test_non_http_schemes_are_rejected(self) -> None:
        for url in _REJECTED_URLS:
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, _REJECTION):
                    _heym_navigable_url(url)

    def test_http_and_https_pass_through_unchanged(self) -> None:
        for url in _ACCEPTED_URLS:
            with self.subTest(url=url):
                self.assertEqual(_heym_navigable_url(url), url)

    def test_schemeless_localhost_gets_http_like_playwright_does(self) -> None:
        for url, expected in _SCHEMELESS_LOCAL_URLS.items():
            with self.subTest(url=url):
                self.assertEqual(_heym_navigable_url(url), expected)

    def test_the_localhost_prefix_never_yields_another_scheme(self) -> None:
        for url in (
            "localhost:file:///etc/passwd",
            "localhost\nfile:///etc/passwd",
            "127.0.0.1/../file:///etc/passwd",
        ):
            with self.subTest(url=url):
                self.assertTrue(_heym_navigable_url(url).startswith("http://"))

    def test_non_string_values_are_checked_as_text(self) -> None:
        with self.assertRaisesRegex(ValueError, _REJECTION):
            _heym_navigable_url(None)
        with self.assertRaisesRegex(ValueError, _REJECTION):
            _heym_navigable_url(123)


def _fake_playwright() -> tuple[types.ModuleType, MagicMock]:
    """A ``playwright.sync_api`` stand-in whose page records every navigation."""
    page = MagicMock(name="page")
    page.content.return_value = "<html><body></body></html>"
    page.url = "about:blank"
    context = MagicMock(name="context")
    context.new_page.return_value = page
    browser = MagicMock(name="browser")
    browser.new_context.return_value = context
    pw = MagicMock(name="playwright")
    pw.chromium.launch.return_value = browser

    @contextlib.contextmanager
    def sync_playwright():  # noqa: ANN202 - mirrors the real factory
        yield pw

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = sync_playwright  # type: ignore[attr-defined]
    return module, page


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _run_script(
    steps: list[dict], inputs: dict | None = None, ai_steps: list[dict] | None = None
) -> tuple[list[str], str]:
    """Run the generated script; return the URLs it navigated to and its stderr."""
    code = generate_playwright_code(steps)
    script = _build_playwright_script(
        code,
        inputs or {},
        heym_api_url="http://heym.invalid",
        heym_execution_token="token",
    )
    module, page = _fake_playwright()
    package = types.ModuleType("playwright")
    package.sync_api = module  # type: ignore[attr-defined]
    stderr = io.StringIO()
    ai_response = _FakeResponse({"steps": ai_steps or []})
    with (
        patch.dict(sys.modules, {"playwright": package, "playwright.sync_api": module}),
        patch("urllib.request.urlopen", return_value=ai_response),
        contextlib.redirect_stderr(stderr),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        try:
            exec(compile(script, "<playwright-script>", "exec"), {"__name__": "__main__"})
        except SystemExit:
            pass
    urls = [str(call.args[0]) for call in page.goto.call_args_list]
    return urls, stderr.getvalue()


class GeneratedScriptTests(unittest.TestCase):
    """The scheme is enforced inside the generated script, at the point of navigation."""

    def test_every_goto_in_the_script_goes_through_the_check(self) -> None:
        code = generate_playwright_code(
            [
                {"action": "navigate", "url": "https://example.com"},
                {"action": "navigate", "url": "$src.url"},
                {"action": "aiStep", "instructions": "do it", "credentialId": "c"},
            ],
            auth_enabled=True,
            auth_fallback_steps=[{"action": "navigate", "url": "https://example.com/login"}],
        )
        gotos = [
            node
            for node in ast.walk(ast.parse(code))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "goto"
        ]
        self.assertGreaterEqual(len(gotos), 4)
        for call in gotos:
            with self.subTest(line=call.lineno):
                first = call.args[0]
                self.assertIsInstance(first, ast.Call)
                self.assertEqual(getattr(first.func, "id", None), "_heym_navigable_url")

    def test_a_file_url_in_a_navigate_step_never_reaches_the_browser(self) -> None:
        urls, stderr = _run_script(
            [
                {
                    "action": "navigate",
                    "url": "file:///var/run/secrets/kubernetes.io/serviceaccount/token",
                },
                {"action": "getText", "selector": "body", "outputKey": "leak"},
            ]
        )
        self.assertEqual(urls, [])
        self.assertIn(_REJECTION, stderr)

    def test_a_file_url_from_a_template_is_checked_after_it_resolves(self) -> None:
        urls, stderr = _run_script(
            [{"action": "navigate", "url": "$src.url"}],
            inputs={"src": {"url": "FILE:///etc/passwd"}},
        )
        self.assertEqual(urls, [])
        self.assertIn(_REJECTION, stderr)

    def test_a_file_url_chosen_by_an_ai_step_never_reaches_the_browser(self) -> None:
        urls, stderr = _run_script(
            [
                {"action": "navigate", "url": "https://example.com"},
                {"action": "aiStep", "instructions": "open the file", "credentialId": "c"},
            ],
            ai_steps=[{"action": "navigate", "url": "view-source:file:///etc/passwd"}],
        )
        self.assertEqual(urls, ["https://example.com"])
        self.assertIn(_REJECTION, stderr)

    def test_http_navigation_is_unchanged(self) -> None:
        urls, stderr = _run_script(
            [
                {"action": "navigate", "url": "https://example.com/a"},
                {"action": "navigate", "url": "$src.url"},
                {"action": "aiStep", "instructions": "next page", "credentialId": "c"},
            ],
            inputs={"src": {"url": "http://example.com/b"}},
            ai_steps=[{"action": "navigate", "url": "https://example.com/c"}],
        )
        self.assertEqual(
            urls, ["https://example.com/a", "http://example.com/b", "https://example.com/c"]
        )
        self.assertNotIn(_REJECTION, stderr)

    def test_schemeless_localhost_navigation_still_works(self) -> None:
        urls, stderr = _run_script(
            [
                {"action": "navigate", "url": "localhost:3000"},
                {"action": "navigate", "url": "$src.url"},
                {"action": "aiStep", "instructions": "next page", "credentialId": "c"},
            ],
            inputs={"src": {"url": "127.0.0.1:8080/x"}},
            ai_steps=[{"action": "navigate", "url": "localhost:3000/next"}],
        )
        self.assertEqual(
            urls,
            [
                "http://localhost:3000",
                "http://127.0.0.1:8080/x",
                "http://localhost:3000/next",
            ],
        )
        self.assertNotIn(_REJECTION, stderr)


if __name__ == "__main__":
    unittest.main()
