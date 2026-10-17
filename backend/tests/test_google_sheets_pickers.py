"""Google Sheets writes that survive quotes and line breaks, and the tab and column pickers."""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import HTTPException

from app.db.models import CredentialType
from app.services.node_execution.nodes.google_sheets_node import _resolve_values


class _Executor:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def evaluate_message_template(self, template: str, _inputs: dict, _node_id: str) -> str:
        for key, value in self.values.items():
            template = template.replace(key, value)
        return template


class ResolveValuesTests(unittest.TestCase):
    def test_each_cell_is_resolved_on_its_own(self) -> None:
        executor = _Executor(
            {"$mail.subject": 'Re: "Q3" invoice', "$mail.text": "Hi,\nsee attached"}
        )
        template = json.dumps([["$mail.subject", "$mail.text", 42]])

        rows = _resolve_values(executor, template, {}, "n1")

        self.assertEqual(rows, [['Re: "Q3" invoice', "Hi,\nsee attached", 42]])

    def test_a_single_expression_for_the_rows_still_works(self) -> None:
        executor = _Executor({"$prep.rows": '[["a", "b"]]'})

        self.assertEqual(_resolve_values(executor, "$prep.rows", {}, "n1"), [["a", "b"]])

    def test_values_stored_as_a_list_are_accepted(self) -> None:
        executor = _Executor({"$x": "1"})

        self.assertEqual(_resolve_values(executor, [["$x", None]], {}, "n1"), [["1", None]])


def _credential(kind: CredentialType = CredentialType.google_sheets) -> SimpleNamespace:
    return SimpleNamespace(type=kind, encrypted_config="enc")


class PickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_tabs_lists_the_title_and_tabs(self) -> None:
        from app.api.google_sheets import spreadsheet_tabs

        body = {"properties": {"title": "Leads"}, "sheets": [{"properties": {"title": "2026"}}]}
        with (
            patch(
                "app.api.google_sheets.get_accessible_credential",
                AsyncMock(return_value=_credential()),
            ),
            patch("app.api.google_sheets.decrypt_config", return_value={}),
            patch("app.api.google_sheets._read_tabs", return_value=body),
        ):
            result = await spreadsheet_tabs(
                uuid.uuid4(),
                spreadsheet="https://docs.google.com/spreadsheets/d/abc123/edit",
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=AsyncMock(),
            )

        self.assertEqual(
            (result.spreadsheet_id, result.title, result.tabs), ("abc123", "Leads", ["2026"])
        )

    async def test_columns_fill_empty_headers_with_their_letter(self) -> None:
        from app.api.google_sheets import sheet_columns

        with (
            patch(
                "app.api.google_sheets.get_accessible_credential",
                AsyncMock(return_value=_credential()),
            ),
            patch("app.api.google_sheets.decrypt_config", return_value={}),
            patch("app.api.google_sheets._read_header", return_value=["Name", "", "Email"]),
        ):
            result = await sheet_columns(
                uuid.uuid4(),
                spreadsheet="abc123",
                tab="Leads",
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=AsyncMock(),
            )

        self.assertEqual(result.columns, ["Name", "B", "Email"])

    async def test_another_credential_type_is_not_found(self) -> None:
        from app.api.google_sheets import spreadsheet_tabs

        with patch(
            "app.api.google_sheets.get_accessible_credential",
            AsyncMock(return_value=_credential(CredentialType.slack_bot)),
        ):
            with self.assertRaises(HTTPException) as caught:
                await spreadsheet_tabs(
                    uuid.uuid4(),
                    spreadsheet="abc",
                    current_user=SimpleNamespace(id=uuid.uuid4()),
                    db=AsyncMock(),
                )
        self.assertEqual(caught.exception.status_code, 404)

    async def test_a_spreadsheet_google_refuses_reads_as_not_found(self) -> None:
        from app.api.google_sheets import spreadsheet_tabs

        refused = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock(status_code=403)
        )
        with (
            patch(
                "app.api.google_sheets.get_accessible_credential",
                AsyncMock(return_value=_credential()),
            ),
            patch("app.api.google_sheets.decrypt_config", return_value={}),
            patch("app.api.google_sheets._read_tabs", side_effect=refused),
        ):
            with self.assertRaises(HTTPException) as caught:
                await spreadsheet_tabs(
                    uuid.uuid4(),
                    spreadsheet="abc",
                    current_user=SimpleNamespace(id=uuid.uuid4()),
                    db=AsyncMock(),
                )
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
