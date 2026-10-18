"""The Codex device sign-in state keeps OpenAI's device handle sealed and bound to one user.

Whoever holds ``device_auth_id`` and the user code can collect the ChatGPT tokens once the code
is approved, so the handle must never reach the browser in the clear, and a state minted for one
user must not poll for another.
"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api import codex_oauth
from app.services.codex_oauth_service import CodexDeviceCode


def _device_code(expires_at: str = "2999-01-01T00:00:00+00:00") -> CodexDeviceCode:
    return CodexDeviceCode(
        device_auth_id="deviceauth_0123456789abcdef",
        user_code="ABCD-1234",
        interval=5,
        expires_at=expires_at,
    )


class TestCodexDeviceStateAdvisory(unittest.IsolatedAsyncioTestCase):
    async def test_start_response_does_not_expose_device_handle(self) -> None:
        service = MagicMock()
        service.device_verification_url = "https://auth.openai.com/codex/device"
        service.request_device_code.return_value = _device_code()
        user = MagicMock()
        user.id = "user-1"
        with patch.object(codex_oauth, "CodexOAuthService", return_value=service):
            started = await codex_oauth.device_start(current_user=user)
        self.assertNotIn("deviceauth_0123456789abcdef", started.model_dump_json())

    def test_state_round_trips_for_its_owner(self) -> None:
        state = codex_oauth._seal_device_state("user-1", _device_code())
        self.assertEqual(
            codex_oauth._open_device_state(state, "user-1"),
            ("deviceauth_0123456789abcdef", "ABCD-1234"),
        )

    def test_state_refused_for_another_user(self) -> None:
        state = codex_oauth._seal_device_state("user-1", _device_code())
        with self.assertRaises(HTTPException) as ctx:
            codex_oauth._open_device_state(state, "user-2")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_expired_state_refused(self) -> None:
        state = codex_oauth._seal_device_state(
            "user-1", _device_code(expires_at="2000-01-01T00:00:00+00:00")
        )
        with self.assertRaises(HTTPException) as ctx:
            codex_oauth._open_device_state(state, "user-1")
        self.assertIn("expired", str(ctx.exception.detail))

    def test_redirect_flow_state_cannot_poll(self) -> None:
        redirect_state = codex_oauth._seal_state("user-1", "verifier-1")
        with self.assertRaises(HTTPException):
            codex_oauth._open_device_state(redirect_state, "user-1")

    def test_device_state_cannot_complete_redirect_flow(self) -> None:
        device_state = codex_oauth._seal_device_state("user-1", _device_code())
        with self.assertRaises(HTTPException):
            codex_oauth._open_state(device_state, "user-1")

    async def test_poll_with_forged_state_never_reaches_openai(self) -> None:
        service = MagicMock()
        user = MagicMock()
        user.id = "user-1"
        with (
            patch.object(codex_oauth, "CodexOAuthService", return_value=service),
            self.assertRaises(HTTPException),
        ):
            await codex_oauth.device_poll(
                codex_oauth.DevicePollRequest(state="deviceauth_0123456789abcdef"),
                current_user=user,
            )
        service.poll_device_authorization.assert_not_called()


if __name__ == "__main__":
    unittest.main()
