"""Google Sheets API client with OAuth2 token management."""

import re
from datetime import datetime, timedelta, timezone

import httpx

from app.services.encryption import encrypt_config

_SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
# Grid limit for open-ended row ranges (Google Sheets max rows per sheet).
_SHEET_MAX_ROWS = 1048576


def _column_letter_zero_based(col_index: int) -> str:
    """Map 0-based column index to A, B, …, Z, AA, … (Sheets-style)."""
    if col_index < 0:
        return str(col_index + 1)
    n = col_index + 1
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


class GoogleSheetsService:
    """Sync Google Sheets API client.

    Manages token refresh and all Sheets v4 API operations.
    Uses sync httpx + sync DB session to match the existing executor pattern.
    """

    def __init__(self, credential_id: str, config: dict, db) -> None:
        """Initialise with decrypted credential config and an open sync DB session."""
        self._credential_id = credential_id
        self._config = dict(config)
        self._db = db

    @staticmethod
    def parse_spreadsheet_id(id_or_url: str) -> str:
        """Return spreadsheet ID from a full URL or bare ID string."""
        m = _SPREADSHEET_ID_RE.search(id_or_url)
        return m.group(1) if m else id_or_url.strip()

    def _is_token_expired(self) -> bool:
        """Return True if the access token expires within 60 seconds."""
        expiry_str = self._config.get("token_expiry", "")
        if not expiry_str:
            return True
        try:
            expiry = datetime.fromisoformat(expiry_str)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) >= expiry - timedelta(seconds=60)
        except ValueError:
            return True

    def _refresh_token(self) -> None:
        """Exchange the refresh token for a new access token and persist to DB."""
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._config["refresh_token"],
                "client_id": self._config["client_id"],
                "client_secret": self._config["client_secret"],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._config["access_token"] = data["access_token"]
        self._config["token_expiry"] = (
            datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])
        ).isoformat()

        from app.db.models import Credential

        cred = self._db.query(Credential).filter(Credential.id == self._credential_id).first()
        if cred:
            cred.encrypted_config = encrypt_config(self._config)
            self._db.commit()

    def _get_valid_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if self._is_token_expired():
            self._refresh_token()
        return self._config["access_token"]

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_valid_token()}"}

    def read_range(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        start_row: int = 1,
        max_rows: int = 0,
        has_header: bool = True,
    ) -> dict:
        """Read rows from a sheet. Returns {rows, total, success}.

        start_row: 1-indexed first DATA row (header is always row 1 when has_header=True).
        max_rows: maximum data rows to return; 0 means return all rows.
        When has_header=True row 1 is used as column names and data begins at start_row.
        When False, column keys are column letters (A, B, …) matching the sheet.
        Each row object includes ``rowIndex`` (1-based sheet row number).
        """
        if has_header:
            # Header is always row 1; data begins at start_row (>= 1, treated as >= 2 after header).
            # Fetch A1:Z{last_data_row} — end is open when max_rows=0.
            data_offset = max(start_row - 1, 1)  # index into raw[] where data begins (skip header)
            if max_rows > 0:
                last_data_row = start_row + max_rows - 1
                range_a1 = f"A1:Z{last_data_row}"
            else:
                range_a1 = "A1:Z"
        else:
            end_row = start_row + max_rows - 1 if max_rows > 0 else ""
            range_a1 = f"A{start_row}:Z{end_row}" if end_row else f"A{start_row}:Z"

        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{sheet_name}!{range_a1}"
        resp = httpx.get(url, headers=self._auth_headers())
        resp.raise_for_status()
        raw: list[list] = resp.json().get("values", [])

        if not raw:
            return {"rows": [], "total": 0, "success": True}

        if has_header:
            headers = [str(h) for h in raw[0]]
            data_raw = (
                raw[data_offset : data_offset + max_rows] if max_rows > 0 else raw[data_offset:]
            )
            rows = []
            for j, row in enumerate(data_raw):
                raw_index = data_offset + j
                row_index_1based = raw_index + 1
                cells = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
                rows.append({**cells, "rowIndex": row_index_1based})
        else:
            rows = []
            for j, row in enumerate(raw):
                row_index_1based = start_row + j
                cells = {
                    _column_letter_zero_based(i): (row[i] if i < len(row) else "")
                    for i in range(len(row))
                }
                rows.append({**cells, "rowIndex": row_index_1based})

        return {"rows": rows, "total": len(rows), "success": True}

    def _sheet_id_for_title(self, spreadsheet_id: str, sheet_name: str) -> int:
        """Return numeric sheetId for a tab title, or raise if missing."""
        info = self.get_sheet_info(spreadsheet_id)
        for s in info["sheets"]:
            if s["title"] == sheet_name:
                return int(s["sheetId"])
        raise ValueError(f"Sheet tab not found: {sheet_name!r}")

    def append_rows(self, spreadsheet_id: str, sheet_name: str, values: list) -> dict:
        """Append rows below the last row with data. Returns {updatedRange, updatedRows, success}."""
        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{sheet_name}!A1:append"
        resp = httpx.post(
            url,
            headers=self._auth_headers(),
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"values": values},
        )
        resp.raise_for_status()
        updates = resp.json().get("updates", {})
        return {
            "updatedRange": updates.get("updatedRange", ""),
            "updatedRows": updates.get("updatedRows", 0),
            "success": True,
        }

    def prepend_rows(self, spreadsheet_id: str, sheet_name: str, values: list) -> dict:
        """Insert rows starting at row 2 (below row 1), shifting existing rows down.

        Uses batchUpdate insertDimension on ROWS at index 1, then values update at A2:…
        Same A–Z column span as update_range. Returns {updatedRange, updatedCells, success}.
        """
        if not values:
            return {"updatedRange": "", "updatedRows": 0, "updatedCells": 0, "success": True}
        sheet_id = self._sheet_id_for_title(spreadsheet_id, sheet_name)
        n = len(values)
        batch_url = f"{_SHEETS_BASE}/{spreadsheet_id}:batchUpdate"
        body = {
            "requests": [
                {
                    "insertDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": 1,
                            "endIndex": 1 + n,
                        },
                        # False: do not inherit header row formatting (e.g. bold) from row 1.
                        "inheritFromBefore": False,
                    }
                }
            ]
        }
        resp = httpx.post(batch_url, headers=self._auth_headers(), json=body)
        resp.raise_for_status()
        out = self.update_range(spreadsheet_id, sheet_name, 2, values)
        out["updatedRows"] = n
        return out

    def update_range(
        self, spreadsheet_id: str, sheet_name: str, row_number: int, values: list
    ) -> dict:
        """Overwrite cells with values starting at the given 1-based sheet row (A–Z columns).

        One PUT to the values API (not spreadsheets.batchUpdate). Returns {updatedRange, updatedCells, success}.
        """
        row_number = max(1, int(row_number))
        row_count = len(values)
        range_a1 = (
            f"A{row_number}:Z{row_number + row_count - 1}"
            if row_count
            else f"A{row_number}:Z{row_number}"
        )
        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{sheet_name}!{range_a1}"
        resp = httpx.put(
            url,
            headers=self._auth_headers(),
            params={"valueInputOption": "USER_ENTERED"},
            json={"range": f"{sheet_name}!{range_a1}", "values": values},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "updatedRange": data.get("updatedRange", ""),
            "updatedCells": data.get("updatedCells", 0),
            "success": True,
        }

    def clear_range(
        self, spreadsheet_id: str, sheet_name: str, *, keep_header: bool = False
    ) -> dict:
        """Clear all values in columns A–Z for the tab (same span as read/update).

        When keep_header is True, row 1 is left unchanged and all rows below through the grid limit are cleared.
        Otherwise entire columns A–Z are cleared (full sheet clear for those columns).
        Returns {clearedRange, success}.
        """
        if keep_header:
            range_a1 = f"A2:Z{_SHEET_MAX_ROWS}"
        else:
            range_a1 = "A:Z"
        url = f"{_SHEETS_BASE}/{spreadsheet_id}/values/{sheet_name}!{range_a1}:clear"
        resp = httpx.post(url, headers=self._auth_headers())
        resp.raise_for_status()
        data = resp.json()
        return {"clearedRange": data.get("clearedRange", ""), "success": True}

    def get_sheet_info(self, spreadsheet_id: str) -> dict:
        """Fetch spreadsheet sheet list. Returns {sheets: [{title, sheetId, index}], success}."""
        url = f"{_SHEETS_BASE}/{spreadsheet_id}"
        resp = httpx.get(
            url,
            headers=self._auth_headers(),
            params={"fields": "sheets.properties"},
        )
        resp.raise_for_status()
        sheets = [
            {
                "title": s["properties"]["title"],
                "sheetId": s["properties"]["sheetId"],
                "index": s["properties"]["index"],
            }
            for s in resp.json().get("sheets", [])
        ]
        return {"sheets": sheets, "success": True}
