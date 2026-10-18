"""Google OAuth state rides in the authorization URL, so it must not carry the client secret.

The URL reaches browser history, proxy logs and Referer headers. The callback reads the
secret from the credential instead; states minted before this change still carry it and
keep working until they expire.
"""

import importlib
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from urllib.parse import parse_qs, urlparse

import jwt
from starlette.datastructures import Headers

from app.config import settings
from app.services.encryption import decrypt_config, encrypt_config

MODULES = ("google_sheets_oauth", "google_drive_oauth", "bigquery_oauth")
SECRET = "client-secret-that-must-stay-out-of-urls"


def _module(name: str) -> ModuleType:
    return importlib.import_module(f"app.api.{name}")


def _credential() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        encrypted_config=encrypt_config({"client_id": "cid", "client_secret": SECRET}),
    )


def _db(credential: SimpleNamespace | None) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=credential))
    )
    return db


def _token_response() -> MagicMock:
    tokens = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
    return MagicMock(raise_for_status=MagicMock(), json=MagicMock(return_value=tokens))


def _legacy_state(module: ModuleType, credential_id: uuid.UUID) -> str:
    return jwt.encode(
        {
            "user_id": str(uuid.uuid4()),
            "credential_id": str(credential_id),
            "client_id": "cid",
            "client_secret": "secret-from-an-old-state",
            "redirect_uri": "https://heym.run/callback",
            "type": module._STATE_TYPE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )


class GoogleOAuthStateNoSecretTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_authorization_url_carries_no_client_secret(self) -> None:
        for name in MODULES:
            with self.subTest(module=name):
                module = _module(name)
                credential = _credential()
                request = Mock(base_url="http://testserver/", headers=Headers({}))

                result = await module.authorize(
                    body=module.AuthorizeRequest(credential_id=str(credential.id)),
                    request=request,
                    current_user=SimpleNamespace(id=credential.owner_id),
                    db=_db(credential),
                )

                state = parse_qs(urlparse(result["auth_url"]).query)["state"][0]
                payload = jwt.decode(state, options={"verify_signature": False})
                self.assertNotIn("client_secret", payload)
                self.assertNotIn(SECRET, str(payload))
                self.assertEqual(payload["credential_id"], str(credential.id))

    async def test_a_new_state_exchanges_the_code_with_the_stored_secret(self) -> None:
        for name in MODULES:
            with self.subTest(module=name):
                module = _module(name)
                credential = _credential()
                state = module.create_oauth_state(
                    user_id=str(credential.owner_id),
                    credential_id=str(credential.id),
                    client_id="cid",
                    redirect_uri="https://heym.run/callback",
                )
                db = _db(credential)

                with patch.object(module.httpx, "post", return_value=_token_response()) as post:
                    response = await module.callback(code="code", state=state, db=db)

                self.assertEqual(post.call_args.kwargs["data"]["client_secret"], SECRET)
                stored = decrypt_config(credential.encrypted_config)
                self.assertEqual(stored["client_secret"], SECRET)
                self.assertEqual(stored["access_token"], "at")
                self.assertIn(str(credential.id), response.body.decode())
                db.add.assert_not_called()

    async def test_a_state_minted_before_the_change_still_works(self) -> None:
        for name in MODULES:
            with self.subTest(module=name):
                module = _module(name)
                credential = _credential()
                db = _db(credential)

                with patch.object(module.httpx, "post", return_value=_token_response()) as post:
                    await module.callback(
                        code="code", state=_legacy_state(module, credential.id), db=db
                    )

                self.assertEqual(
                    post.call_args.kwargs["data"]["client_secret"], "secret-from-an-old-state"
                )
                db.commit.assert_awaited_once()

    async def test_a_deleted_credential_fails_without_creating_one(self) -> None:
        for name in MODULES:
            with self.subTest(module=name):
                module = _module(name)
                state = module.create_oauth_state(
                    user_id=str(uuid.uuid4()),
                    credential_id=str(uuid.uuid4()),
                    client_id="cid",
                    redirect_uri="https://heym.run/callback",
                )
                db = _db(None)

                with patch.object(module.httpx, "post") as post:
                    response = await module.callback(code="code", state=state, db=db)

                self.assertIn("Credential not found", response.body.decode())
                post.assert_not_called()
                db.add.assert_not_called()
                db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
