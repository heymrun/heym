"""The `date` of a mail trigger's payload is the Date header in UTC, whatever the server zone.

A Date with the "-0000" zone means UTC (RFC 5322 3.3), and Python's own
`email.utils.formatdate()` writes it by default. `parsedate_to_datetime` returns such a
date naive, and converting it read it as the server's local time: with the image's
TZ=Europe/Berlin, 10:00 -0000 became 09:00Z in winter and 08:00Z in summer.
"""

import os
import time
import unittest
from unittest.mock import patch

from app.services.imap_trigger_service import email_payload


def _date(header: str) -> str:
    raw = (
        "From: Alerts <alerts@example.com>\r\nTo: ops@example.com\r\nSubject: disk full\r\n"
        f"Date: {header}\r\n\r\nbody\r\n"
    ).encode()
    return email_payload(raw)["date"]


class EmailPayloadDateTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(os.environ, {"TZ": "Europe/Berlin"})
        patcher.start()
        time.tzset()
        self.addCleanup(time.tzset)
        self.addCleanup(patcher.stop)

    def test_a_minus_0000_date_is_utc(self) -> None:
        for header, expected in (
            ("Mon, 03 Nov 2025 10:00:00 -0000", "2025-11-03T10:00:00+00:00"),
            ("Fri, 01 Aug 2025 10:00:00 -0000", "2025-08-01T10:00:00+00:00"),
        ):
            with self.subTest(header=header):
                self.assertEqual(_date(header), expected)

    def test_a_date_with_an_offset_is_converted_to_utc(self) -> None:
        for header in ("Mon, 03 Nov 2025 10:00:00 +0000", "Mon, 03 Nov 2025 12:00:00 +0200"):
            with self.subTest(header=header):
                self.assertEqual(_date(header), "2025-11-03T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
