"""OIDC mechanics: discovery, PKCE, authorization URL, token exchange, ID token checks."""

import base64
import hashlib
import unittest
from urllib.parse import parse_qs, urlparse

from app.services.oidc_client import (
    OidcError,
    build_authorization_url,
    make_pkce_pair,
    parse_discovery_document,
)

_DISCOVERY = {
    "issuer": "https://idp.example/realms/heym",
    "authorization_endpoint": "https://idp.example/realms/heym/protocol/openid-connect/auth",
    "token_endpoint": "https://idp.example/realms/heym/protocol/openid-connect/token",
    "jwks_uri": "https://idp.example/realms/heym/protocol/openid-connect/certs",
    "userinfo_endpoint": "https://idp.example/realms/heym/protocol/openid-connect/userinfo",
    "id_token_signing_alg_values_supported": ["RS256", "ES256"],
    "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
}


class DiscoveryParsingTests(unittest.TestCase):
    def test_parses_a_complete_document(self) -> None:
        discovery = parse_discovery_document(_DISCOVERY)

        self.assertEqual(discovery.issuer, "https://idp.example/realms/heym")
        self.assertEqual(discovery.token_auth_method, "client_secret_post")
        self.assertEqual(discovery.signing_algorithms, ["RS256", "ES256"])

    def test_missing_required_endpoint_is_rejected(self) -> None:
        broken = {k: v for k, v in _DISCOVERY.items() if k != "jwks_uri"}

        with self.assertRaises(OidcError):
            parse_discovery_document(broken)

    def test_basic_auth_is_used_when_post_is_unsupported(self) -> None:
        doc = dict(_DISCOVERY, token_endpoint_auth_methods_supported=["client_secret_basic"])

        self.assertEqual(parse_discovery_document(doc).token_auth_method, "client_secret_basic")

    def test_absent_auth_methods_default_to_post(self) -> None:
        doc = {k: v for k, v in _DISCOVERY.items() if k != "token_endpoint_auth_methods_supported"}

        self.assertEqual(parse_discovery_document(doc).token_auth_method, "client_secret_post")

    def test_unsupported_signing_algorithms_are_filtered_out(self) -> None:
        """`none` and symmetric algorithms must never survive into verification."""
        doc = dict(
            _DISCOVERY,
            id_token_signing_alg_values_supported=["none", "HS256", "RS256"],
        )

        self.assertEqual(parse_discovery_document(doc).signing_algorithms, ["RS256"])

    def test_no_usable_signing_algorithm_is_rejected(self) -> None:
        doc = dict(_DISCOVERY, id_token_signing_alg_values_supported=["none", "HS256"])

        with self.assertRaises(OidcError):
            parse_discovery_document(doc)


class PkceTests(unittest.TestCase):
    def test_challenge_is_the_url_safe_sha256_of_the_verifier(self) -> None:
        verifier, challenge = make_pkce_pair()

        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        self.assertEqual(challenge, expected)

    def test_verifier_length_is_within_the_rfc_range(self) -> None:
        verifier, _ = make_pkce_pair()

        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)

    def test_pairs_are_not_reused(self) -> None:
        self.assertNotEqual(make_pkce_pair()[0], make_pkce_pair()[0])


class AuthorizationUrlTests(unittest.TestCase):
    def test_url_carries_pkce_state_nonce_and_scopes(self) -> None:
        discovery = parse_discovery_document(_DISCOVERY)

        url = build_authorization_url(
            discovery,
            client_id="heym",
            redirect_uri="http://localhost:4017/api/auth/sso/callback",
            scopes="openid email profile",
            state="state-value",
            nonce="nonce-value",
            code_challenge="challenge-value",
        )

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        self.assertTrue(url.startswith(discovery.authorization_endpoint))
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["client_id"], ["heym"])
        self.assertEqual(params["scope"], ["openid email profile"])
        self.assertEqual(params["state"], ["state-value"])
        self.assertEqual(params["nonce"], ["nonce-value"])
        self.assertEqual(params["code_challenge"], ["challenge-value"])
        self.assertEqual(params["code_challenge_method"], ["S256"])

    def test_the_verifier_never_appears_in_the_url(self) -> None:
        """PKCE is pointless if the verifier travels through the provider."""
        discovery = parse_discovery_document(_DISCOVERY)
        verifier, challenge = make_pkce_pair()

        url = build_authorization_url(
            discovery,
            client_id="heym",
            redirect_uri="http://localhost:4017/api/auth/sso/callback",
            scopes="openid email profile",
            state="state-value",
            nonce="nonce-value",
            code_challenge=challenge,
        )

        self.assertNotIn(verifier, url)
