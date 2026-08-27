"""Audit trail emitted through the winston logger."""

import ast
import logging
import pathlib
import re
import unittest
import uuid
from unittest.mock import MagicMock

from app.services import audit_log
from app.services.audit_log import OUTCOME_DENIED, OUTCOME_FAILURE, audit

ACTION_PATTERN = re.compile(r"^[a-z_]+\.[a-z_]+$")

# The areas this change was asked to cover. A resource losing every call site
# should fail here rather than silently stop being audited.
COVERED_RESOURCES = {
    "auth",
    "workflow",
    "credential",
    "variable",
    "vector_store",
    "alert",
    "data_table",
    "board",
    "drive",
    "team",
    "folder",
}


def _audit_actions_in_api() -> set[str]:
    """Collect the `action=` literal of every audit() call under app/api."""
    api_dir = pathlib.Path(__file__).resolve().parent.parent / "app" / "api"
    found: set[str] = set()
    for path in api_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "audit"):
                continue
            for keyword in node.keywords:
                if keyword.arg == "action" and isinstance(keyword.value, ast.Constant):
                    found.add(keyword.value.value)
    return found


def _fake_user(email: str = "burak@example.com") -> MagicMock:
    user = MagicMock()
    user.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    user.email = email
    return user


def _audit_kwargs_in_api() -> set[str]:
    """Collect every keyword argument name used at an audit() call site."""
    api_dir = pathlib.Path(__file__).resolve().parent.parent / "app" / "api"
    found: set[str] = set()
    for path in api_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Name) and node.func.id == "audit"):
                continue
            found.update(kw.arg for kw in node.keywords if kw.arg)
    return found


class AuditLineFormatTests(unittest.TestCase):
    def _emit(self, **kwargs) -> str:
        with self.assertLogs("winston.audit", level="INFO") as captured:
            audit(**kwargs)
        self.assertEqual(len(captured.records), 1)
        return captured.records[0].getMessage()

    def test_actor_identity_is_always_present(self) -> None:
        line = self._emit(action="workflow.delete", actor=_fake_user())

        self.assertIn("actor_id=11111111-1111-1111-1111-111111111111", line)
        self.assertIn("actor_email=burak@example.com", line)

    def test_action_and_default_outcome(self) -> None:
        line = self._emit(action="credential.create", actor=_fake_user())

        self.assertIn("action=credential.create", line)
        self.assertIn("outcome=success", line)

    def test_failure_and_denied_outcomes_are_recorded(self) -> None:
        failed = self._emit(
            action="auth.login", outcome=OUTCOME_FAILURE, actor_email="nobody@example.com"
        )
        denied = self._emit(action="credential.delete", outcome=OUTCOME_DENIED, actor=_fake_user())

        self.assertIn("outcome=failure", failed)
        self.assertIn("actor_email=nobody@example.com", failed)
        self.assertIn("outcome=denied", denied)

    def test_anonymous_actor_omits_identity_rather_than_inventing_one(self) -> None:
        line = self._emit(action="auth.logout")

        self.assertNotIn("actor_id=", line)
        self.assertNotIn("actor_email=", line)

    def test_target_is_rendered_as_type_colon_id(self) -> None:
        target = uuid.UUID("22222222-2222-2222-2222-222222222222")
        line = self._emit(
            action="workflow.delete",
            actor=_fake_user(),
            target_type="workflow",
            target_id=target,
            target_name="Nightly sync",
        )

        self.assertIn(f"target=workflow:{target}", line)
        self.assertIn('target_name="Nightly sync"', line)

    def test_record_is_a_single_line(self) -> None:
        line = self._emit(
            action="board.card_create",
            actor=_fake_user(),
            card_title="line one\nline two",
        )

        self.assertNotIn("\n", line)

    def test_booleans_render_as_words_not_python_repr(self) -> None:
        line = self._emit(action="workflow.update", actor=_fake_user(), owned=True)

        self.assertIn("owned=true", line)

    def test_none_details_are_dropped(self) -> None:
        line = self._emit(action="alert.update", actor=_fake_user(), fields=None)

        self.assertNotIn("fields=", line)

    def test_logger_name_separates_audit_from_access_log(self) -> None:
        with self.assertLogs("winston.audit", level="INFO") as captured:
            audit(action="team.create", actor=_fake_user())

        self.assertEqual(captured.records[0].name, "winston.audit")


class AuditRedactionTests(unittest.TestCase):
    """The denylist is a safety net; a secret must never be passed in the first place."""

    def _emit(self, **kwargs) -> str:
        with self.assertLogs("winston.audit", level="INFO") as captured:
            audit(**kwargs)
        return captured.records[0].getMessage()

    def test_secret_shaped_keys_never_reach_the_log(self) -> None:
        secret = "sk-live-do-not-log-this"
        for key in (
            "password",
            "api_key",
            "apiKey",
            "access_token",
            "refresh_token",
            "client_secret",
            "credential_data",
            "value",
            "Authorization",
            "cookie",
            "private_key",
            "passphrase",
        ):
            with self.subTest(key=key):
                line = self._emit(action="credential.create", **{key: secret})

                self.assertNotIn(secret, line)
                self.assertIn("***", line)

    def test_long_values_are_truncated(self) -> None:
        line = self._emit(action="drive.upload", target_name="x" * 5000)

        self.assertIn("...(truncated)", line)
        self.assertLess(len(line), 1000)

    def test_safe_details_are_kept_verbatim(self) -> None:
        line = self._emit(action="data_table.import_csv", imported=42, rejected=0)

        self.assertIn("imported=42", line)
        self.assertIn("rejected=0", line)


class AuditNeverBreaksTheRequestTests(unittest.TestCase):
    def test_a_detail_that_cannot_be_stringified_does_not_raise(self) -> None:
        class Hostile:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        with self.assertLogs("winston.audit", level="WARNING") as captured:
            audit(action="workflow.update", detail=Hostile())

        self.assertIn("audit emit failed", captured.records[0].getMessage())

    def test_a_broken_actor_does_not_raise(self) -> None:
        actor = MagicMock()
        type(actor).id = property(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

        with self.assertLogs("winston.audit", level="WARNING"):
            audit(action="workflow.update", actor=actor)


class NoClientIpTests(unittest.TestCase):
    """Client IPs are deliberately not audited.

    Behind a load balancer the value is either the proxy's address or a spoofable
    forwarded header, so it identifies the user without identifying the request.
    These assertions exist so it cannot quietly come back.
    """

    def test_no_ip_field_is_emitted(self) -> None:
        with self.assertLogs("winston.audit", level="INFO") as captured:
            audit(
                action="auth.login",
                actor=_fake_user(),
                target_type="workflow",
                target_id=uuid.uuid4(),
            )

        self.assertNotIn("ip=", captured.records[0].getMessage())

    def test_an_ip_passed_as_a_detail_is_still_recorded_by_name(self) -> None:
        """The helper does not scrub a caller's own field; call sites must not add one."""
        with self.assertLogs("winston.audit", level="INFO") as captured:
            audit(action="auth.login", client_ip="203.0.113.7")

        self.assertIn("client_ip=203.0.113.7", captured.records[0].getMessage())

    def test_no_call_site_passes_an_ip(self) -> None:
        forbidden = {"ip", "client_ip", "remote_addr", "source_ip", "forwarded_for"}
        offenders = sorted(_audit_kwargs_in_api() & forbidden)

        self.assertEqual(offenders, [])


class ActionTaxonomyTests(unittest.TestCase):
    """Every emitted action name must be `<resource>.<verb>` in snake_case."""

    def test_call_sites_use_the_documented_shape(self) -> None:
        found = _audit_actions_in_api()

        self.assertTrue(found, "no audit call sites found")
        for action in sorted(found):
            with self.subTest(action=action):
                self.assertRegex(action, ACTION_PATTERN)

    def test_every_covered_area_has_at_least_one_action(self) -> None:
        prefixes = {action.split(".", 1)[0] for action in _audit_actions_in_api()}

        self.assertEqual(COVERED_RESOURCES - prefixes, set())


class LoggerWiringTests(unittest.TestCase):
    def test_audit_logger_is_a_child_of_winston(self) -> None:
        """It shares winston's stdout handler but greps apart from the access log."""
        # app.main creates the "winston" logger at import; create it here so the
        # hierarchy is the same one production sees regardless of import order.
        logging.getLogger("winston")

        self.assertEqual(audit_log.logger.name, "winston.audit")
        self.assertEqual(logging.getLogger("winston.audit").parent.name, "winston")

    def test_records_propagate_to_the_root_handler(self) -> None:
        """basicConfig installs the stdout handler on root; propagation carries us there."""
        self.assertTrue(audit_log.logger.propagate)
        self.assertEqual(audit_log.logger.handlers, [])


if __name__ == "__main__":
    unittest.main()
