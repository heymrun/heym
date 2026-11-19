"""Google BigQuery REST API client with OAuth2 token management."""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from app.services.encryption import encrypt_config

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_BQ_BASE = "https://bigquery.googleapis.com/bigquery/v2"
_QUERY_TIMEOUT_MS = 10000
# jobs.getQueryResults waits up to _QUERY_TIMEOUT_MS per call; this bounds the whole wait.
_MAX_RESULT_POLLS = 60


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

    @staticmethod
    def _checked(resp: httpx.Response) -> dict:
        """The JSON body of a successful BigQuery answer; an API error otherwise."""
        if not resp.is_success:
            try:
                err = resp.json().get("error", {})
                msg = err.get("message") or resp.text
            except Exception:
                msg = resp.text
            raise ValueError(f"BigQuery API error {resp.status_code}: {msg}")
        return resp.json()

    def _query_results(
        self, project_id: str, job: dict, max_results: int, page_token: str | None
    ) -> dict:
        """One jobs.getQueryResults call for the query job, waiting up to the timeout."""
        job_id = str(job.get("jobId") or "")
        if not job_id:
            raise ValueError("BigQuery did not return a job reference for the query")
        params: dict = {"timeoutMs": _QUERY_TIMEOUT_MS}
        if job.get("location"):
            params["location"] = job["location"]
        if max_results > 0:
            params["maxResults"] = max_results
        if page_token:
            params["pageToken"] = page_token
        url = f"{_BQ_BASE}/projects/{project_id}/queries/{quote(job_id, safe='')}"
        return self._checked(httpx.get(url, headers=self._auth_headers(), params=params))

    def run_query(self, project_id: str, query: str, max_results: int = 1000) -> dict:
        """Run a synchronous BigQuery SQL query and return rows.

        Uses the jobs.query endpoint which blocks until complete (up to 10s timeout).
        Returns {rows, totalRows, schema, success}.
        """
        url = f"{_BQ_BASE}/projects/{project_id}/queries"
        body: dict = {
            "query": query,
            "useLegacySql": False,
            "timeoutMs": _QUERY_TIMEOUT_MS,
        }
        if max_results > 0:
            body["maxResults"] = max_results
        data = self._checked(httpx.post(url, headers=self._auth_headers(), json=body))

        # A query still running after timeoutMs answers jobComplete: false with no rows;
        # its rows come from jobs.getQueryResults, page by page.
        job = data.get("jobReference") or {}
        polls = 0
        while data.get("jobComplete") is False:
            polls += 1
            if polls > _MAX_RESULT_POLLS:
                raise ValueError("BigQuery query did not finish in time; try a smaller query")
            data = self._query_results(project_id, job, max_results, None)

        schema_fields = data.get("schema", {}).get("fields", [])
        schema = [{"name": f["name"], "type": f["type"]} for f in schema_fields]
        field_names = [f["name"] for f in schema_fields]

        raw_rows = list(data.get("rows", []))
        page_token = data.get("pageToken")
        while page_token and (max_results == 0 or len(raw_rows) < max_results):
            remaining = max_results - len(raw_rows) if max_results else 0
            page = self._query_results(project_id, job, remaining, page_token)
            raw_rows.extend(page.get("rows", []))
            page_token = page.get("pageToken")
        if max_results:
            raw_rows = raw_rows[:max_results]

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
        # BigQuery drops a row whose insertId it saw in about the last minute, and still
        # answers success; ids numbered per call ("0", "1") collide between runs.
        insert_rows = [{"insertId": str(uuid.uuid4()), "json": row} for row in rows]
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
