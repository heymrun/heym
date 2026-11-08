"""TOTP math, recovery code shape, and the signed tokens that carry a sign-in between steps."""

import base64
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.services import mfa
from app.services.auth import read_access_claims

# RFC 6238 appendix B: SHA-1, the ASCII seed "12345678901234567890".
_RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


class TotpTests(unittest.TestCase):
    def test_rfc_6238_vectors_truncated_to_six_digits(self) -> None:
        # The RFC lists eight digits; a six-digit code is the same value mod 10**6.
        for timestamp, eight_digits in (
            (59, "94287082"),
            (1111111109, "07081804"),
            (1234567890, "89005924"),
            (2000000000, "69279037"),
        ):
            with self.subTest(timestamp=timestamp):
                step = mfa.current_step(timestamp)
                self.assertEqual(mfa.code_at_step(_RFC_SECRET, step), eight_digits[-6:])

    def test_a_code_from_the_neighbouring_step_is_accepted(self) -> None:
        now = 1_700_000_000.0
        step = mfa.current_step(now)
        previous = mfa.code_at_step(_RFC_SECRET, step - 1)
        self.assertEqual(
            mfa.matching_step(_RFC_SECRET, previous, last_step=None, now=now), step - 1
        )

    def test_a_code_two_steps_away_is_refused(self) -> None:
        now = 1_700_000_000.0
        stale = mfa.code_at_step(_RFC_SECRET, mfa.current_step(now) - 2)
        self.assertIsNone(mfa.matching_step(_RFC_SECRET, stale, last_step=None, now=now))

    def test_a_used_step_cannot_be_replayed(self) -> None:
        now = 1_700_000_000.0
        step = mfa.current_step(now)
        code = mfa.code_at_step(_RFC_SECRET, step)
        self.assertIsNone(mfa.matching_step(_RFC_SECRET, code, last_step=step, now=now))

    def test_spaces_in_a_typed_code_are_ignored(self) -> None:
        now = 1_700_000_000.0
        code = mfa.code_at_step(_RFC_SECRET, mfa.current_step(now))
        spaced = f"{code[:3]} {code[3:]}"
        self.assertIsNotNone(mfa.matching_step(_RFC_SECRET, spaced, last_step=None, now=now))

    def test_generated_secrets_are_160_bits_of_base32(self) -> None:
        secret = mfa.generate_secret()
        padded = secret + "=" * (-len(secret) % 8)
        self.assertEqual(len(base64.b32decode(padded)), 20)
        self.assertNotEqual(secret, mfa.generate_secret())

    def test_the_otpauth_uri_names_heym_and_the_account(self) -> None:
        uri = mfa.otpauth_uri("JBSWY3DPEHPK3PXP", "ada@acme.example")
        self.assertTrue(uri.startswith("otpauth://totp/Heym%3Aada%40acme.example?"))
        self.assertIn("secret=JBSWY3DPEHPK3PXP", uri)
        self.assertIn("issuer=Heym", uri)

    def test_the_qr_code_is_an_svg_data_uri(self) -> None:
        self.assertTrue(mfa.qr_data_uri("otpauth://totp/x").startswith("data:image/svg+xml"))


class RecoveryCodeTests(unittest.TestCase):
    def test_ten_distinct_codes_of_sixteen_characters(self) -> None:
        codes = mfa.generate_recovery_codes()
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        for code in codes:
            self.assertEqual(len(mfa.normalize_recovery_code(code)), 16)
            self.assertRegex(code, r"^[A-Z2-9]{4}(-[A-Z2-9]{4}){3}$")

    def test_normalising_ignores_case_and_separators(self) -> None:
        self.assertEqual(mfa.normalize_recovery_code("abcd-efgh ijkl-mnop"), "ABCDEFGHIJKLMNOP")


class SignInRequirementTests(unittest.TestCase):
    def _user(self, *, enrolled: bool) -> SimpleNamespace:
        return SimpleNamespace(
            mfa_enabled_at=object() if enrolled else None,
            mfa_secret="ciphertext" if enrolled else None,
        )

    def test_nothing_is_asked_while_the_env_flag_is_off(self) -> None:
        with patch.object(mfa.settings, "require_mfa", False):
            self.assertIsNone(mfa.password_sign_in_requirement(self._user(enrolled=True)))
            self.assertIsNone(mfa.password_sign_in_requirement(self._user(enrolled=False)))

    def test_enrolled_accounts_verify_and_others_enrol_while_it_is_on(self) -> None:
        with patch.object(mfa.settings, "require_mfa", True):
            self.assertEqual(
                mfa.password_sign_in_requirement(self._user(enrolled=True)), mfa.PURPOSE_VERIFY
            )
            self.assertEqual(
                mfa.password_sign_in_requirement(self._user(enrolled=False)), mfa.PURPOSE_ENROLL
            )


class ChallengeTokenTests(unittest.TestCase):
    def test_a_challenge_round_trips_with_its_purpose_and_client(self) -> None:
        user_id = uuid.uuid4()
        token = mfa.create_challenge_token(user_id, mfa.PURPOSE_VERIFY, client="work")
        claims = mfa.read_challenge_token(token)
        self.assertIsNotNone(claims)
        assert claims is not None
        self.assertEqual(claims.user_id, user_id)
        self.assertEqual(claims.purpose, mfa.PURPOSE_VERIFY)
        self.assertEqual(claims.client, "work")

    def test_a_challenge_is_not_an_access_token(self) -> None:
        token = mfa.create_challenge_token(uuid.uuid4(), mfa.PURPOSE_VERIFY, client=None)
        self.assertIsNone(read_access_claims(token))

    def test_a_setup_token_opens_only_for_its_own_account(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="ada@acme.example")
        offer = mfa.create_setup_offer(user)
        self.assertEqual(mfa.read_setup_secret(offer.setup_token, user.id), offer.secret)
        self.assertIsNone(mfa.read_setup_secret(offer.setup_token, uuid.uuid4()))

    def test_a_setup_token_carries_the_secret_encrypted(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="ada@acme.example")
        offer = mfa.create_setup_offer(user)
        payload = offer.setup_token.split(".")[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        self.assertNotIn(offer.secret, decoded)


if __name__ == "__main__":
    unittest.main()
