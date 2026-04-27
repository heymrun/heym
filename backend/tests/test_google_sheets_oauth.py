"""Unit tests for Google Sheets OAuth2 helper functions."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

from jose import jwt
from starlette.datastructures import Headers

_TEST_SECRET = "test-secret-key-for-tests-only"
_ALGORITHM = "HS256"


def _make_valid_state(
    user_id: str | None = None,
    credential_id: str | None = None,
    client_id: str = "test-client-id",
    client_secret: str = "test-secret",
    redirect_uri: str = "http://testserver/api/credentials/google-sheets/oauth/callback",
) -> str:
    return jwt.encode(
        {
            "user_id": user_id or str(uuid.uuid4()),
            "credential_id": credential_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "type": "gs_oauth_state",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        _TEST_SECRET,
        algorithm=_ALGORITHM,
    )


def _make_expired_state() -> str:
    return jwt.encode(
        {
            "user_id": str(uuid.uuid4()),
            "credential_id": None,
            "client_id": "c",
            "client_secret": "s",
            "redirect_uri": "http://testserver/callback",
            "type": "gs_oauth_state",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
        },
        _TEST_SECRET,
        algorithm=_ALGORITHM,
    )


class TestBuildAuthUrl(unittest.TestCase):
    def test_auth_url_contains_required_params(self) -> None:
        from app.api.google_sheets_oauth import build_auth_url

        url = build_auth_url(
            client_id="my-client-id",
            redirect_uri="http://testserver/callback",
            state="some-state",
        )
        self.assertIn("accounts.google.com", url)
        self.assertIn("my-client-id", url)
        self.assertIn("spreadsheets", url)
        self.assertIn("offline", url)
        self.assertIn("some-state", url)


class TestCreateOAuthState(unittest.TestCase):
    def test_state_is_valid_jwt_with_correct_fields(self) -> None:
        from app.api.google_sheets_oauth import create_oauth_state

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            state = create_oauth_state(
                user_id=str(uuid.uuid4()),
                credential_id=None,
                client_id="cid",
                client_secret="csecret",
                redirect_uri="http://testserver/callback",
            )

        decoded = jwt.decode(state, _TEST_SECRET, algorithms=[_ALGORITHM])
        self.assertEqual(decoded["type"], "gs_oauth_state")
        self.assertEqual(decoded["client_id"], "cid")
        self.assertEqual(decoded["client_secret"], "csecret")


class TestHandleCallbackState(unittest.TestCase):
    def test_invalid_state_returns_none(self) -> None:
        from app.api.google_sheets_oauth import handle_callback_state

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            result = handle_callback_state("not-a-valid-jwt")

        self.assertIsNone(result)

    def test_expired_state_returns_none(self) -> None:
        from app.api.google_sheets_oauth import handle_callback_state

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            result = handle_callback_state(_make_expired_state())

        self.assertIsNone(result)

    def test_valid_state_returns_payload(self) -> None:
        from app.api.google_sheets_oauth import handle_callback_state

        user_id = str(uuid.uuid4())
        valid_state = _make_valid_state(user_id=user_id, client_id="cid", client_secret="cs")

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            result = handle_callback_state(valid_state)

        self.assertIsNotNone(result)
        self.assertEqual(result["user_id"], user_id)
        self.assertEqual(result["client_id"], "cid")

    def test_wrong_type_field_returns_none(self) -> None:
        from app.api.google_sheets_oauth import handle_callback_state

        bad_state = jwt.encode(
            {
                "user_id": str(uuid.uuid4()),
                "type": "wrong_type",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
            _TEST_SECRET,
            algorithm=_ALGORITHM,
        )
        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            result = handle_callback_state(bad_state)

        self.assertIsNone(result)


class TestPopupHtml(unittest.TestCase):
    def test_success_html_contains_credential_id(self) -> None:
        from app.api.google_sheets_oauth import _popup_html

        html = _popup_html(True, credential_id="cred-123")
        self.assertIn("google-oauth-success", html)
        self.assertIn("credentialId", html)
        self.assertIn("cred-123", html)

    def test_error_html_contains_message(self) -> None:
        from app.api.google_sheets_oauth import _popup_html

        html = _popup_html(False, message="Something went wrong")
        self.assertIn("google-oauth-error", html)
        self.assertIn("Something went wrong", html)

    def test_error_html_escapes_single_quotes(self) -> None:
        from app.api.google_sheets_oauth import _popup_html

        html = _popup_html(False, message="it's broken")
        self.assertNotIn("it's broken", html)
        self.assertIn("\\'", html)


def _make_db_result(credential) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = credential
    return result


class TestResolvePublicOrigin(unittest.TestCase):
    """resolve_public_origin uses FRONTEND_URL only, not spoofable request headers."""

    def test_frontend_url_used_not_origin_header(self) -> None:
        from starlette.requests import Request

        from app.services.public_url import resolve_public_origin

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "path": "/api/credentials/google-sheets/oauth/authorize",
            "raw_path": b"/api/credentials/google-sheets/oauth/authorize",
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": Headers({"origin": "https://attacker.example"}).raw,
            "client": ("127.0.0.1", 4444),
            "server": ("backend", 10105),
        }
        request = Request(scope)
        with patch("app.services.public_url.settings") as s:
            s.frontend_url = "https://heym.example.com"
            out = resolve_public_origin(request)
        self.assertEqual(out, "https://heym.example.com")


class TestAuthorizeEndpoint(unittest.IsolatedAsyncioTestCase):
    """Tests for the /authorize endpoint that now looks up credentials from DB."""

    def _make_credential(self, client_id: str = "cid", client_secret: str = "csecret"):
        from app.db.models import Credential, CredentialType
        from app.services.encryption import encrypt_config

        cred = Mock(spec=Credential)
        cred.id = uuid.uuid4()
        cred.owner_id = uuid.uuid4()
        cred.type = CredentialType.google_sheets
        cred.encrypted_config = encrypt_config(
            {"client_id": client_id, "client_secret": client_secret}
        )
        return cred

    async def test_returns_auth_url_for_valid_credential(self) -> None:
        from app.api.google_sheets_oauth import AuthorizeRequest, authorize

        cred = self._make_credential()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_db_result(cred))

        user = Mock()
        user.id = cred.owner_id

        request = Mock()
        request.base_url = "http://testserver/"
        request.headers = Headers({})

        body = AuthorizeRequest(credential_id=str(cred.id))

        with patch("app.api.google_sheets_oauth.settings") as mock_settings:
            mock_settings.secret_key = _TEST_SECRET
            mock_settings.jwt_algorithm = _ALGORITHM
            mock_settings.frontend_url = ""
            result = await authorize(body=body, request=request, current_user=user, db=db)

        self.assertIn("auth_url", result)
        self.assertIn("accounts.google.com", result["auth_url"])
        self.assertIn("cid", result["auth_url"])

    async def test_returns_404_when_credential_not_found(self) -> None:
        from fastapi import HTTPException

        from app.api.google_sheets_oauth import AuthorizeRequest, authorize

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_db_result(None))

        user = Mock()
        user.id = uuid.uuid4()

        request = Mock()
        request.base_url = "http://testserver/"
        request.headers = Headers({})

        body = AuthorizeRequest(credential_id=str(uuid.uuid4()))

        with self.assertRaises(HTTPException) as ctx:
            await authorize(body=body, request=request, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_returns_400_when_client_id_missing(self) -> None:
        from fastapi import HTTPException

        from app.api.google_sheets_oauth import AuthorizeRequest, authorize
        from app.db.models import Credential, CredentialType
        from app.services.encryption import encrypt_config

        cred = Mock(spec=Credential)
        cred.id = uuid.uuid4()
        cred.owner_id = uuid.uuid4()
        cred.type = CredentialType.google_sheets
        cred.encrypted_config = encrypt_config({"client_id": "", "client_secret": "s"})

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_db_result(cred))

        user = Mock()
        user.id = cred.owner_id

        request = Mock()
        request.base_url = "http://testserver/"
        request.headers = Headers({})

        body = AuthorizeRequest(credential_id=str(cred.id))

        with self.assertRaises(HTTPException) as ctx:
            await authorize(body=body, request=request, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, 400)


class TestValidateGoogleSheetsCredential(unittest.TestCase):
    """Tests for google_sheets branch in validate_credential_config."""

    def test_valid_config_passes(self) -> None:
        from app.api.credentials import validate_credential_config
        from app.db.models import CredentialType

        validate_credential_config(
            CredentialType.google_sheets,
            {"client_id": "my-client-id", "client_secret": "my-secret"},
        )

    def test_missing_client_id_raises_400(self) -> None:
        from fastapi import HTTPException

        from app.api.credentials import validate_credential_config
        from app.db.models import CredentialType

        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.google_sheets,
                {"client_id": "", "client_secret": "s"},
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("client_id", ctx.exception.detail)

    def test_missing_client_secret_raises_400(self) -> None:
        from fastapi import HTTPException

        from app.api.credentials import validate_credential_config
        from app.db.models import CredentialType

        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.google_sheets,
                {"client_id": "cid"},
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("client_secret", ctx.exception.detail)
