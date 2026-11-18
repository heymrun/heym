"""Exchange Server sign-in: settings, server discovery, the SSRF check and safe errors."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import dns.exception
from exchangelib import errors as ews

from app.services.exchange_server import connection
from app.services.exchange_server.connection import (
    check_connection,
    discover_server,
    ews_errors,
    ews_settings,
    is_ews,
    raise_failed,
    service_endpoint,
    validation_problem,
)
from app.services.outlook_service import OutlookApiError
from app.services.ssrf_guard import SsrfBlockedError

CONFIG = {
    "auth_mode": "ews",
    "ews_email": " Ada@Heym.run ",
    "ews_username": "HEYM\\ada",
    "ews_password": "secret-pass",
    "ews_server": "mail.heym.run",
}


def _srv(target: str, port: int = 443, priority: int = 0, weight: int = 0) -> SimpleNamespace:
    return SimpleNamespace(target=f"{target}.", port=port, priority=priority, weight=weight)


class SettingsTests(unittest.TestCase):
    def test_only_auth_mode_ews_counts_as_exchange_server(self) -> None:
        self.assertTrue(is_ews(CONFIG))
        for config in ({}, {"auth_mode": "oauth"}, {"auth_mode": "EWS "}):
            self.assertFalse(is_ews(config), config)

    def test_settings_are_trimmed_and_the_address_lowercased(self) -> None:
        settings = ews_settings(CONFIG)
        self.assertEqual(settings.email, "ada@heym.run")
        self.assertEqual(settings.username, "HEYM\\ada")
        self.assertEqual(settings.server, "mail.heym.run")

    def test_a_complete_sign_in_has_no_problem_and_the_server_is_optional(self) -> None:
        self.assertIsNone(validation_problem(CONFIG))
        self.assertIsNone(validation_problem({**CONFIG, "ews_server": ""}))
        self.assertIsNone(
            validation_problem({**CONFIG, "ews_server": "https://mail.heym.run/EWS/Exchange.asmx"})
        )

    def test_a_blank_user_name_signs_in_with_the_email_address(self) -> None:
        config = {**CONFIG, "ews_username": ""}
        self.assertEqual(ews_settings(config).username, "ada@heym.run")
        self.assertIsNone(validation_problem(config))

    def test_missing_fields_are_named(self) -> None:
        cases = {
            "ews_email": "email address",
            "ews_password": "password",
        }
        for key, words in cases.items():
            with self.subTest(key=key):
                self.assertIn(words, validation_problem({**CONFIG, key: ""}) or "")

    def test_a_server_that_could_leave_https_or_ews_is_refused(self) -> None:
        for server in (
            "http://mail.heym.run",
            "https://mail.heym.run/owa",
            "https://user:pw@mail.heym.run",
            "https://mail.heym.run?x=1",
            "mail.heym.run/../x",
            "mail heym",
            "outlook.office365.com",
            "https://outlook.office.com/EWS/Exchange.asmx",
        ):
            with self.subTest(server=server):
                self.assertIsNotNone(validation_problem({**CONFIG, "ews_server": server}))


class EndpointTests(unittest.TestCase):
    def test_a_host_or_ews_address_becomes_the_ews_endpoint_after_the_ssrf_check(self) -> None:
        for server, expected in (
            ("mail.heym.run", "https://mail.heym.run/EWS/Exchange.asmx"),
            ("mail.heym.run:8443", "https://mail.heym.run:8443/EWS/Exchange.asmx"),
            (
                "https://mail.heym.run/ews/exchange.asmx",
                "https://mail.heym.run/EWS/Exchange.asmx",
            ),
        ):
            with self.subTest(server=server), patch.object(connection, "guard_http_url") as guard:
                self.assertEqual(
                    service_endpoint(ews_settings({**CONFIG, "ews_server": server})), expected
                )
                guard.assert_called_once_with(expected, "Exchange server")

    def test_a_blank_server_is_found_through_the_autodiscover_srv_record(self) -> None:
        answers = [_srv("backup.heym.run", priority=10), _srv("mail.heym.run", priority=0)]
        with (
            patch.object(connection.dns.resolver, "resolve", return_value=answers) as resolve,
            patch.object(connection, "guard_http_url"),
        ):
            url = service_endpoint(ews_settings({**CONFIG, "ews_server": ""}))
        self.assertEqual(url, "https://mail.heym.run/EWS/Exchange.asmx")
        self.assertEqual(resolve.call_args.args[:2], ("_autodiscover._tcp.heym.run", "SRV"))

    def test_a_non_default_srv_port_is_kept(self) -> None:
        with patch.object(
            connection.dns.resolver, "resolve", return_value=[_srv("ex.heym.run", 444)]
        ):
            self.assertEqual(discover_server("a@heym.run"), "ex.heym.run:444")

    def test_no_srv_record_asks_for_the_server(self) -> None:
        with (
            patch.object(connection.dns.resolver, "resolve", side_effect=dns.exception.Timeout()),
            self.assertRaises(ValueError) as caught,
        ):
            discover_server("a@heym.run")
        self.assertIn("enter the server address", str(caught.exception))

    def test_a_private_server_is_refused_by_the_ssrf_guard(self) -> None:
        with (
            patch.object(connection, "guard_http_url", side_effect=SsrfBlockedError("blocked")),
            self.assertRaises(OutlookApiError) as caught,
            ews_errors(),
        ):
            connection.ews_account(CONFIG)
        self.assertEqual(caught.exception.status_code, 400)

    def test_the_account_signs_in_without_autodiscover_or_retries(self) -> None:
        with (
            patch.object(connection, "guard_http_url"),
            patch.object(connection, "Account") as account,
            patch.object(connection, "Configuration") as configuration,
        ):
            connection.ews_account(CONFIG)
        settings = configuration.call_args.kwargs
        self.assertEqual(settings["service_endpoint"], "https://mail.heym.run/EWS/Exchange.asmx")
        self.assertEqual(type(settings["retry_policy"]).__name__, "FailFast")
        self.assertEqual(account.call_args.kwargs["primary_smtp_address"], "ada@heym.run")
        self.assertFalse(account.call_args.kwargs["autodiscover"])


class ErrorTests(unittest.TestCase):
    def test_exchangelib_failures_map_to_statuses_without_server_text(self) -> None:
        cases = [
            (ews.UnauthorizedError("401 for ada secret-pass"), 401),
            (ews.ErrorAccessDenied("denied ada@heym.run"), 403),
            (ews.ErrorItemNotFound("item AAMk"), 404),
            (ews.ErrorNonExistentMailbox("x@heym.run"), 400),
            (ews.ErrorServerBusy("busy", back_off=1), 429),
            (ews.TransportError("mail.heym.run refused"), 502),
            (ews.ErrorInternalServerError("stack trace secret"), 502),
        ]
        for error, status in cases:
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(OutlookApiError) as caught, ews_errors():
                    raise error
                self.assertEqual(caught.exception.status_code, status)
                for leaked in ("secret", "ada@", "AAMk", "stack"):
                    self.assertNotIn(leaked, str(caught.exception))

    def test_ntlm_and_ews_bodies_never_reach_debug_logs(self) -> None:
        import logging

        for name in ("exchangelib", "spnego", "requests_ntlm"):
            self.assertGreaterEqual(
                logging.getLogger(name).getEffectiveLevel(), logging.WARNING, name
            )

    def test_a_refused_sign_in_points_at_the_domain_format(self) -> None:
        with self.assertRaises(OutlookApiError) as caught, ews_errors():
            raise ews.UnauthorizedError("no")
        self.assertIn("DOMAIN\\user", str(caught.exception))
        self.assertIn("email address", str(caught.exception))

    def test_failed_items_come_back_as_exceptions_and_are_raised(self) -> None:
        self.assertEqual(raise_failed("ok"), "ok")
        with self.assertRaises(ews.ErrorItemNotFound):
            raise_failed(ews.ErrorItemNotFound("gone"))


class CheckConnectionTests(unittest.TestCase):
    def test_the_check_opens_the_inbox_or_the_calendar(self) -> None:
        account = MagicMock(primary_smtp_address="ada@heym.run")
        account.protocol.service_endpoint = "https://mail.heym.run/EWS/Exchange.asmx"
        with patch.object(connection, "ews_account", return_value=account):
            message = check_connection(CONFIG)
            check_connection(CONFIG, calendar=True)
        self.assertEqual(message, "Connected to ada@heym.run on mail.heym.run")
        account.inbox.refresh.assert_called_once()
        account.calendar.refresh.assert_called_once()

    def test_a_refused_sign_in_is_reported(self) -> None:
        with (
            patch.object(connection, "ews_account", side_effect=ews.UnauthorizedError("no")),
            self.assertRaises(OutlookApiError) as caught,
        ):
            check_connection(CONFIG)
        self.assertEqual(caught.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
