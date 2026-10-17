"""Regression tests for Jira Data Center Personal Access Token (Bearer) auth.

A PAT is sent as ``Authorization: Bearer`` and must only ever reach the credential
base URL origin, must never be exposed through ``public_fields``, and must not
survive an auth-mode switch. Basic stays the default so credentials saved before
``auth_mode`` existed keep working unchanged.
"""

import unittest
from unittest.mock import MagicMock

import httpx
from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    get_public_credential_fields,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.db.models import CredentialType
from app.services.jira_service import JiraService

_DC_URL = "https://jira.corp.example.com"
_PAT = "pat-secret-value-123456"


def _response(url: str, payload: object | None = None) -> httpx.Response:
    return httpx.Response(200, json=payload or {"name": "ada"}, request=httpx.Request("GET", url))


def _pat_config(**overrides: str) -> dict[str, str]:
    config = {
        "auth_mode": "pat",
        "api_token": _PAT,
        "base_url": _DC_URL,
        "deployment": "data_center",
    }
    config.update(overrides)
    return config


class JiraPatRequestTests(unittest.TestCase):
    def test_pat_is_sent_as_bearer_without_basic_auth(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(f"{_DC_URL}/rest/api/2/myself")

        JiraService(_pat_config(), client=client).get_myself()

        kwargs = client.request.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {_PAT}")
        self.assertNotIn("auth", kwargs)

    def test_pat_mode_does_not_require_email(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(f"{_DC_URL}/rest/api/2/myself")

        JiraService(_pat_config(email=""), client=client).get_myself()

        client.request.assert_called_once()

    def test_caller_headers_cannot_replace_the_bearer_header(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(f"{_DC_URL}/rest/api/2/myself")

        JiraService(_pat_config(), client=client)._request(
            "GET", "/myself", headers={"Authorization": "Bearer attacker"}
        )

        headers = client.request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], f"Bearer {_PAT}")

    def test_pat_is_only_sent_to_the_base_url_origin(self) -> None:
        client = MagicMock()
        service = JiraService(_pat_config(), client=client)

        with self.assertRaises(ValueError):
            service.download_attachment("https://attacker.example.com/steal")

        client.request.assert_not_called()

    def test_same_origin_attachment_download_carries_the_bearer_header(self) -> None:
        client = MagicMock()
        url = f"{_DC_URL}/secure/attachment/10001/file.txt"
        client.request.return_value = httpx.Response(
            200, content=b"payload", request=httpx.Request("GET", url)
        )

        content = JiraService(_pat_config(), client=client).download_attachment(url)

        self.assertEqual(content, b"payload")
        kwargs = client.request.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {_PAT}")
        self.assertNotIn("auth", kwargs)

    def test_missing_auth_mode_keeps_basic_auth(self) -> None:
        client = MagicMock()
        client.request.return_value = _response(f"{_DC_URL}/rest/api/2/myself")
        config = {
            "email": "ada@example.com",
            "api_token": "pw",
            "base_url": _DC_URL,
            "deployment": "data_center",
        }

        JiraService(config, client=client).get_myself()

        kwargs = client.request.call_args.kwargs
        self.assertEqual(kwargs["auth"], ("ada@example.com", "pw"))
        self.assertNotIn("Authorization", kwargs["headers"])

    def test_pat_on_cloud_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            JiraService(_pat_config(deployment="cloud"), client=MagicMock())


class JiraPatCredentialConfigTests(unittest.TestCase):
    def test_pat_credential_validates_without_email(self) -> None:
        validate_credential_config(CredentialType.jira, _pat_config())

    def test_pat_requires_a_token(self) -> None:
        with self.assertRaises(HTTPException):
            validate_credential_config(CredentialType.jira, _pat_config(api_token=""))

    def test_pat_is_rejected_for_cloud(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.jira, _pat_config(deployment="cloud"))
        self.assertIn("Data Center", str(ctx.exception.detail))

    def test_unknown_auth_mode_is_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            validate_credential_config(CredentialType.jira, _pat_config(auth_mode="oauth"))

    def test_basic_still_requires_email(self) -> None:
        with self.assertRaises(HTTPException):
            validate_credential_config(
                CredentialType.jira,
                {"api_token": "pw", "base_url": _DC_URL, "deployment": "data_center"},
            )

    def test_public_fields_expose_auth_mode_but_never_the_token(self) -> None:
        fields = get_public_credential_fields(CredentialType.jira, _pat_config())

        self.assertEqual(fields["auth_mode"], "pat")
        self.assertNotIn(_PAT, repr(fields))

    def test_public_fields_default_to_basic(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.jira,
            {"email": "a@b.c", "api_token": "pw", "base_url": _DC_URL},
        )

        self.assertEqual(fields["auth_mode"], "basic")

    def test_masked_preview_works_in_pat_mode(self) -> None:
        masked = get_masked_value(CredentialType.jira, _pat_config())

        self.assertTrue(masked)
        self.assertNotEqual(masked, _PAT)


class JiraPatModeSwitchTests(unittest.TestCase):
    _basic = {
        "email": "ada@example.com",
        "api_token": "old-password",
        "base_url": _DC_URL,
        "deployment": "data_center",
    }

    def test_switching_to_pat_drops_the_stored_password_and_email(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.jira, self._basic, {"auth_mode": "pat"}
        )

        self.assertEqual(merged["auth_mode"], "pat")
        self.assertNotIn("api_token", merged)
        self.assertNotIn("email", merged)
        with self.assertRaises(HTTPException):
            validate_credential_config(CredentialType.jira, merged)

    def test_switching_to_pat_with_a_new_token_keeps_only_the_new_secret(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.jira, self._basic, {"auth_mode": "pat", "api_token": _PAT}
        )

        self.assertEqual(merged["api_token"], _PAT)
        self.assertNotIn("email", merged)
        validate_credential_config(CredentialType.jira, merged)

    def test_switching_back_to_basic_drops_the_stored_pat(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.jira, _pat_config(), {"auth_mode": "basic", "email": "ada@example.com"}
        )

        self.assertEqual(merged["auth_mode"], "basic")
        self.assertNotIn("api_token", merged)

    def test_editing_other_fields_keeps_the_stored_token(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.jira, _pat_config(), {"base_url": "https://jira2.example.com"}
        )

        self.assertEqual(merged["api_token"], _PAT)
        self.assertEqual(merged["base_url"], "https://jira2.example.com")

    def test_legacy_credential_without_auth_mode_keeps_its_secret_on_basic_update(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.jira, self._basic, {"auth_mode": "basic", "base_url": _DC_URL}
        )

        self.assertEqual(merged["api_token"], "old-password")
        self.assertEqual(merged["email"], "ada@example.com")


if __name__ == "__main__":
    unittest.main()
