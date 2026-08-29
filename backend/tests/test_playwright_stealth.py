"""Reduce-automation-flags codegen must stay opt-in and injection-safe."""

import unittest
from unittest.mock import patch

from app.services.playwright_code_generator import (
    CHROMIUM_DISABLE_WEBRTC_STUN_ARG,
    _stealth_chromium_launch_kwargs,
    generate_playwright_code,
)

_STEPS = [{"action": "wait", "timeout": 1}]
_INJECTION = '(__import__("builtins").print("PWNED_MARKER"), True)[1]'


class PlaywrightStealthCodegenTests(unittest.TestCase):
    def test_stealth_off_keeps_plain_launch(self) -> None:
        code = generate_playwright_code(_STEPS, stealth=False)
        compile(code, "<generated>", "exec")
        self.assertIn(CHROMIUM_DISABLE_WEBRTC_STUN_ARG, code)
        self.assertIn("add_init_script", code)
        self.assertIn("RTCPeerConnection", code)
        self.assertNotIn("AutomationControlled", code)
        self.assertNotIn("_stealth_user_agent", code)

    def test_stealth_on_injects_evasions(self) -> None:
        code = generate_playwright_code(_STEPS, stealth=True)
        compile(code, "<generated>", "exec")
        self.assertIn("disable-blink-features=AutomationControlled", code)
        self.assertIn("--exclude-switches=enable-automation", code)
        self.assertIn(CHROMIUM_DISABLE_WEBRTC_STUN_ARG, code)
        self.assertIn("RTCPeerConnection", code)
        self.assertIn('system == "Linux"', code)
        self.assertIn("--no-sandbox", code)
        self.assertIn("--enable-gpu", code)
        self.assertIn("add_init_script", code)
        self.assertIn("webdriver", code)
        self.assertIn("Navigator.prototype", code)
        self.assertIn("HeadlessChrome", code)
        self.assertIn("Object.create(PluginArray.prototype)", code)
        self.assertIn("enabledPlugin", code)
        self.assertIn("defineProperty(Notification", code)
        self.assertIn("Google Chrome", code)
        self.assertNotIn("Intel(R) UHD Graphics 630", code)
        self.assertIn("Mali-G78", code)
        self.assertIn("0x9246", code)
        self.assertIn("swiftshader", code)
        self.assertIn("setUserAgentOverride", code)
        self.assertIn("platformVersion", code)
        self.assertIn("_stealth_user_agent", code)
        self.assertIn("_apply_stealth_user_agent_override", code)
        self.assertNotIn("browser = p.chromium.launch(headless=headless)", code)

    def test_stealth_truthy_string_is_coerced_without_code_injection(self) -> None:
        code = generate_playwright_code(_STEPS, stealth=_INJECTION)
        compile(code, "<generated>", "exec")
        self.assertNotIn("PWNED_MARKER", code)
        self.assertNotIn("__import__", code)
        self.assertNotIn("AutomationControlled", code)


class PlaywrightStealthLaunchKwargsTests(unittest.TestCase):
    @patch("platform.system", return_value="Linux")
    def test_linux_stays_headless_without_gpu(self, _system: object) -> None:
        kwargs = _stealth_chromium_launch_kwargs(True)
        self.assertTrue(kwargs["headless"])
        self.assertEqual(
            kwargs["args"],
            [
                "--disable-blink-features=AutomationControlled",
                "--exclude-switches=enable-automation",
                CHROMIUM_DISABLE_WEBRTC_STUN_ARG,
                "--no-sandbox",
            ],
        )
        self.assertEqual(kwargs["ignore_default_args"], ["--enable-automation"])
        self.assertNotIn("--enable-gpu", kwargs["args"])
        self.assertNotIn("--use-angle=metal", kwargs["args"])
        self.assertNotIn("--headless=new", kwargs["args"])

    @patch("platform.system", return_value="Darwin")
    def test_darwin_uses_host_metal_gpu(self, _system: object) -> None:
        kwargs = _stealth_chromium_launch_kwargs(True)
        self.assertFalse(kwargs["headless"])
        self.assertIn("--enable-gpu", kwargs["args"])
        self.assertIn("--use-angle=metal", kwargs["args"])
        self.assertIn("--headless=new", kwargs["args"])
        self.assertIn(CHROMIUM_DISABLE_WEBRTC_STUN_ARG, kwargs["args"])
        self.assertIn("--disable-gpu", kwargs["ignore_default_args"])
        self.assertNotIn("--no-sandbox", kwargs["args"])
