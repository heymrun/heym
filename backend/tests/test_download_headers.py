"""Downloads named after a folder or a data table must not fail on the name's characters."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import unquote

from app.api import data_tables, folders
from app.api.download_headers import attachment_disposition

NON_LATIN1_NAMES = ["Müşteri Raporları", "Отчёты", "报表", "Q3 📊"]


def _filename_from(disposition: str) -> str:
    if "filename*=utf-8''" in disposition:
        return unquote(disposition.split("filename*=utf-8''", 1)[1])
    return disposition.split('filename="', 1)[1].rstrip('"')


def _result(*, one: object = None, many: list | None = None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = one
    result.scalars.return_value.all.return_value = many or []
    return result


class AttachmentDispositionTests(unittest.TestCase):
    def test_a_plain_name_keeps_the_quoted_form(self) -> None:
        self.assertEqual(attachment_disposition("report.csv"), 'attachment; filename="report.csv"')

    def test_names_outside_latin1_round_trip_through_filename_star(self) -> None:
        for name in NON_LATIN1_NAMES:
            with self.subTest(name=name):
                value = attachment_disposition(f"{name}.zip")
                value.encode("latin-1")
                self.assertTrue(value.startswith("attachment; filename*=utf-8''"))
                self.assertEqual(_filename_from(value), f"{name}.zip")

    def test_a_quote_in_the_name_cannot_end_the_value_early(self) -> None:
        value = attachment_disposition('Q3 "final".csv')
        self.assertEqual(_filename_from(value), 'Q3 "final".csv')
        self.assertNotIn('"final"', value)


class ExportRouteHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_folder_named_outside_latin1_exports(self) -> None:
        for name in NON_LATIN1_NAMES:
            with self.subTest(name=name):
                folder = SimpleNamespace(id=uuid.uuid4(), name=name)
                db = AsyncMock()
                db.execute.side_effect = [
                    _result(one=folder),
                    _result(many=[]),
                    _result(many=[]),
                ]
                user = SimpleNamespace(id=uuid.uuid4())

                response = await folders.export_folder_as_zip(folder.id, db, user)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    _filename_from(response.headers["content-disposition"]), f"{name}.zip"
                )

    async def test_a_data_table_named_outside_latin1_exports(self) -> None:
        for name in NON_LATIN1_NAMES:
            with self.subTest(name=name):
                table = SimpleNamespace(
                    id=uuid.uuid4(),
                    name=name,
                    columns=[{"id": "c1", "name": "city", "type": "string", "order": 0}],
                )
                db = AsyncMock()
                db.execute.return_value = _result(many=[SimpleNamespace(data={"city": "İzmir"})])
                user = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com")

                with (
                    patch.object(
                        data_tables,
                        "_get_data_table_with_access",
                        AsyncMock(return_value=table),
                    ),
                    patch.object(data_tables, "audit"),
                ):
                    response = await data_tables.export_csv(table.id, user, db)

                self.assertEqual(response.status_code, 200)
                expected = f"{name}.csv".replace(" ", "_")
                self.assertEqual(_filename_from(response.headers["content-disposition"]), expected)


if __name__ == "__main__":
    unittest.main()
