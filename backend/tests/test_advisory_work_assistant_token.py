"""A token Heym's chat mints for a call to Heym Work.

It is Work-bound and short-lived, is never minted for an inactive user, authenticates only
together with the Work key, and stops working once the user is deactivated or signed out
everywhere.
"""

import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.deps import resolve_token_claims
from app.services.account_status import meets_mfa_policy, session_still_valid
from app.services.auth import SIGN_IN_ASSISTANT, decode_token, read_access_claims
from app.services.work_integration import key_version, mint_assistant_token

_BOUND = "app.api.deps.work_token_is_bound"
_KEY_HASH = "a" * 64


def _user(active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), is_active=active)


class _Request:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


class MintTests(unittest.TestCase):
    def test_claims_are_work_bound_assistant(self) -> None:
        user = _user()
        token = mint_assistant_token(user, _KEY_HASH)
        assert token is not None
        claims = read_access_claims(token)
        assert claims is not None
        self.assertEqual(claims.user_id, user.id)
        self.assertEqual(claims.client, "work")
        self.assertEqual(claims.key_version, key_version(_KEY_HASH))
        self.assertEqual(claims.method, SIGN_IN_ASSISTANT)

    def test_short_and_long_lifetimes(self) -> None:
        now = time.time()
        short_token = mint_assistant_token(_user(), _KEY_HASH)
        long_token = mint_assistant_token(_user(), _KEY_HASH, long_running=True)
        assert short_token is not None and long_token is not None
        short = decode_token(short_token)["exp"] - now
        long = decode_token(long_token)["exp"] - now
        self.assertGreater(short, 4 * 60)
        self.assertLessEqual(short, 5 * 60 + 2)
        self.assertGreater(long, 34 * 60)
        self.assertLessEqual(long, 35 * 60 + 2)

    def test_nothing_for_an_inactive_user(self) -> None:
        self.assertIsNone(mint_assistant_token(_user(active=False), _KEY_HASH))

    def test_nothing_without_a_key(self) -> None:
        self.assertIsNone(mint_assistant_token(_user(), ""))


class AcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_refused_without_the_work_key(self) -> None:
        token = mint_assistant_token(_user(), _KEY_HASH)
        assert token is not None
        with patch(_BOUND, AsyncMock(return_value=False)) as bound:
            self.assertIsNone(await resolve_token_claims(_Request({}), token))
        bound.assert_awaited_once_with(None, key_version(_KEY_HASH))

    async def test_accepted_with_the_work_key(self) -> None:
        token = mint_assistant_token(_user(), _KEY_HASH)
        assert token is not None
        with patch(_BOUND, AsyncMock(return_value=True)):
            claims = await resolve_token_claims(_Request({"X-Heym-Work-Key": "hwi_x"}), token)
        self.assertIsNotNone(claims)

    def test_passes_the_mfa_policy(self) -> None:
        with patch("app.services.account_status.settings", SimpleNamespace(require_mfa=True)):
            self.assertTrue(
                meets_mfa_policy(SIGN_IN_ASSISTANT, has_password=True, has_sso_identity=False)
            )

    def test_refused_after_deactivation(self) -> None:
        token = mint_assistant_token(_user(), _KEY_HASH)
        assert token is not None
        claims = read_access_claims(token)
        assert claims is not None
        self.assertFalse(
            session_still_valid(
                claims,
                is_active=False,
                sessions_revoked_at=None,
                has_password=True,
                has_sso_identity=False,
            )
        )

    def test_refused_after_sign_out_everywhere(self) -> None:
        token = mint_assistant_token(_user(), _KEY_HASH)
        assert token is not None
        claims = read_access_claims(token)
        assert claims is not None
        later = datetime.now(timezone.utc) + timedelta(seconds=5)
        self.assertFalse(
            session_still_valid(
                claims,
                is_active=True,
                sessions_revoked_at=later,
                has_password=True,
                has_sso_identity=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
