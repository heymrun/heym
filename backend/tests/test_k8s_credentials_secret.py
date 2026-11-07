"""Turning a labelled Kubernetes Secret into a credential, or a reason it can't be one."""

from __future__ import annotations

import base64
import json
import unittest

from app.services.k8s_credentials.secret import parse_secret


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def _secret(data: dict[str, str] | None = None, **annotations: str) -> dict:
    merged = {"name": "llm-gateway", "type": "custom", "owner": "Admin@Example.com"}
    merged.update(annotations)
    return {
        "metadata": {
            "name": "heym-cred-llm",
            "namespace": "heym",
            "labels": {"heym.run/credential": "true"},
            "annotations": {f"heym.run/{k}": v for k, v in merged.items() if v is not None},
        },
        "data": {
            k: _b64(v) for k, v in (data or {"base_url": "http://gw/v1", "api_key": "sk-1"}).items()
        },
    }


class ParseSecretTests(unittest.TestCase):
    def test_flat_keys_become_the_config(self) -> None:
        item = parse_secret(_secret())

        self.assertIsNone(item.problem)
        self.assertEqual(item.config, {"base_url": "http://gw/v1", "api_key": "sk-1"})
        self.assertEqual((item.name, item.type), ("llm-gateway", "custom"))
        self.assertEqual(item.pointer, "k8s:heym/heym-cred-llm")

    def test_owner_and_share_emails_are_lowercased(self) -> None:
        item = parse_secret(_secret(**{"share-users": "Alice@Example.com, bob@example.com"}))

        self.assertEqual(item.owner_email, "admin@example.com")
        self.assertEqual(item.share_users, ("alice@example.com", "bob@example.com"))

    def test_share_teams_are_split_and_trimmed(self) -> None:
        item = parse_secret(_secret(**{"share-teams": " automation ,ops,"}))

        self.assertEqual(item.share_teams, ("automation", "ops"))

    def test_config_json_holds_a_nested_config(self) -> None:
        nested = {
            "rabbitmq_host": "mq",
            "rabbitmq_port": 5672,
            "rabbitmq_username": "heym",
            "rabbitmq_password": "pw",
        }
        item = parse_secret(_secret({"config.json": json.dumps(nested)}, type="rabbitmq"))

        self.assertIsNone(item.problem)
        self.assertEqual(item.config, nested)

    def test_config_json_must_be_the_only_key(self) -> None:
        item = parse_secret(_secret({"config.json": "{}", "api_key": "x"}))

        self.assertIn("only data key", item.problem or "")

    def test_config_json_must_be_an_object(self) -> None:
        self.assertIn("JSON object", parse_secret(_secret({"config.json": "[1]"})).problem or "")
        self.assertIn("not valid JSON", parse_secret(_secret({"config.json": "{"})).problem or "")

    def test_missing_annotations_are_named(self) -> None:
        item = parse_secret(_secret(owner=None, type=None))  # type: ignore[arg-type]

        self.assertEqual(item.problem, "missing annotation heym.run/type, heym.run/owner")

    def test_unknown_type_is_refused(self) -> None:
        self.assertIn("not a credential type", parse_secret(_secret(type="nope")).problem or "")

    def test_types_that_write_tokens_back_are_refused(self) -> None:
        for credential_type in (
            "codex",
            "google_sheets",
            "google_drive",
            "google_meet",
            "bigquery",
        ):
            with self.subTest(credential_type):
                item = parse_secret(_secret(type=credential_type))
                self.assertIn("can't be read-only", item.problem or "")

    def test_linear_is_refused_only_in_oauth_mode(self) -> None:
        oauth = parse_secret(_secret({"auth_mode": "oauth", "access_token": "t"}, type="linear"))
        token = parse_secret(_secret({"api_token": "lin_api_x"}, type="linear"))

        self.assertIn("OAuth mode", oauth.problem or "")
        self.assertNotIn("OAuth mode", token.problem or "")

    def test_the_create_endpoints_validation_applies(self) -> None:
        item = parse_secret(_secret({"base_url": "x"}, type="openai"))

        self.assertEqual(item.problem, "OpenAI credential requires api_key")

    def test_binary_data_is_refused(self) -> None:
        secret = _secret()
        secret["data"] = {"api_key": base64.b64encode(b"\xff\xfe").decode()}

        self.assertIn("not UTF-8 text", parse_secret(secret).problem or "")

    def test_an_invalid_secret_keeps_no_value(self) -> None:
        item = parse_secret(_secret(type="nope"))

        self.assertEqual(item.config, {})


if __name__ == "__main__":
    unittest.main()
