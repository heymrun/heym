"""Google BigQuery REST API client with OAuth2 token management."""

from datetime import datetime, timedelta, timezone

import httpx

from app.services.encryption import encrypt_config

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_BQ_BASE = "https://bigquery.googleapis.com/bigquery/v2"


class BigQueryService:
    """Sync BigQuery REST API v2 client.

    Manages token refresh and query / insertAll operations.
    Uses sync httpx + sync DB session to match the existing executor pattern.
    """

    def __init__(self, credential_id: str, config: dict, db) -> None:
        """Initialise with decrypted credential config and an open sync DB session."""
        self._credential_id = credential_id
        self._config = dict(config)
        self._db = db

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

    def run_query(self, project_id: str, query: str, max_results: int = 1000) -> dict:
        """Run a synchronous BigQuery SQL query and return rows.

        Uses the jobs.query endpoint which blocks until complete (up to 10s timeout).
        Returns {rows, totalRows, schema, success}.
        """
        url = f"{_BQ_BASE}/projects/{project_id}/queries"
        body: dict = {
            "query": query,
            "useLegacySql": False,
            "timeoutMs": 10000,
        }
        if max_results > 0:
            body["maxResults"] = max_results
        resp = httpx.post(url, headers=self._auth_headers(), json=body)
        if not resp.is_success:
            try:
                err = resp.json().get("error", {})
                msg = err.get("message") or resp.text
            except Exception:
                msg = resp.text
            raise ValueError(f"BigQuery API error {resp.status_code}: {msg}")
        data = resp.json()

        schema_fields = data.get("schema", {}).get("fields", [])
        schema = [{"name": f["name"], "type": f["type"]} for f in schema_fields]
        field_names = [f["name"] for f in schema_fields]

        raw_rows = data.get("rows", [])
        rows = []
        for raw_row in raw_rows:
            cells = raw_row.get("f", [])
            row = {
                field_names[i]: (cells[i]["v"] if i < len(cells) else None)
                for i in range(len(field_names))
            }
            rows.append(row)

        return {
            "rows": rows,
            "totalRows": int(data.get("totalRows", len(rows))),
            "schema": schema,
            "success": True,
        }

    def insert_rows(
        self, project_id: str, dataset_id: str, table_id: str, rows: list[dict]
    ) -> dict:
        """Stream-insert rows into a BigQuery table using the tabledata.insertAll API.

        rows: list of dicts mapping column names to values.
        Returns {insertedCount, success}.
        """
        url = f"{_BQ_BASE}/projects/{project_id}/datasets/{dataset_id}/tables/{table_id}/insertAll"
        insert_rows = [{"insertId": str(i), "json": row} for i, row in enumerate(rows)]
        body = {"rows": insert_rows, "skipInvalidRows": False, "ignoreUnknownValues": False}
        resp = httpx.post(url, headers=self._auth_headers(), json=body)
        if not resp.is_success:
            try:
                err = resp.json().get("error", {})
                msg = err.get("message") or resp.text
            except Exception:
                msg = resp.text
            raise ValueError(f"BigQuery API error {resp.status_code}: {msg}")
        data = resp.json()

        insert_errors = data.get("insertErrors", [])
        if insert_errors:
            raise ValueError(f"BigQuery insertAll errors: {insert_errors}")

        return {"insertedCount": len(rows), "success": True}
