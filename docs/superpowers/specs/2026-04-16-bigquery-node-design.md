# BigQuery Node Design

**Date:** 2026-04-16
**Status:** Approved

## Summary

Add a BigQuery integration node to Heym supporting two operations — `query` (run SQL and return rows) and `insertRows` (stream-insert rows into a table). Authentication uses OAuth2 via a new `bigquery` credential type, following the same pattern as the existing Google Sheets node.

---

## Architecture & Data Flow

### Credential & Auth Flow

A new `CredentialType.bigquery` is added to the DB enum (Alembic migration required). The OAuth2 flow mirrors Google Sheets:

1. User creates a BigQuery credential → enters `client_id` + `client_secret`
2. Frontend redirects to `/oauth/bigquery/authorize` → Google consent screen  
   Scope: `https://www.googleapis.com/auth/bigquery`
3. Google redirects to `/oauth/bigquery/callback` → backend exchanges code for `access_token` + `refresh_token`, encrypts and stores in DB
4. Credential masked display shows `"connected"` once a refresh token is present

### BigQueryService

New `backend/app/services/bigquery_service.py` modelled after `GoogleSheetsService`:
- Constructor takes `credential_id`, decrypted `config` dict, sync `db` session
- Auto-refreshes access token when within 60 seconds of expiry
- Persists refreshed tokens via `encrypt_config`
- Uses BigQuery REST API v2: `https://bigquery.googleapis.com/bigquery/v2`

### Operations

| Operation | BQ API call | Node fields | Output |
|---|---|---|---|
| `query` | `POST projects/{project}/queries` | `bqProjectId`, `bqQuery`, `bqMaxResults` | `{rows, totalRows, schema, success}` |
| `insertRows` | `POST projects/{project}/datasets/{dataset}/tables/{table}/insertAll` | `bqProjectId`, `bqDatasetId`, `bqTableId`, `bqRowsInputMode`, `bqRows` or `bqMappings` | `{insertedCount, success}` |

#### insertRows input modes

- **raw** — user provides a JSON array of row objects directly in `bqRows`
- **selective** — user defines `bqMappings` as key→value pairs (same `MappingField[]` pattern as Set and Google Sheets nodes); the executor assembles the row object from evaluated mappings

---

## Backend Components

### New files

- `backend/app/services/bigquery_service.py` — `BigQueryService` class with `run_query()` and `insert_rows()` methods
- `backend/app/api/bigquery_oauth.py` — `/oauth/bigquery/authorize` and `/oauth/bigquery/callback` routes (mirrors `google_sheets_oauth.py` with BigQuery scope)
- `backend/tests/test_bigquery_node.py` — unit tests (see Testing section)

### Modified files

- `backend/app/db/models.py` — add `bigquery = "bigquery"` to `CredentialType` enum
- `backend/alembic/versions/` — new migration adding `bigquery` to the `credential_type` Postgres enum
- `backend/app/api/credentials.py` — add `bigquery` to `get_masked_value()` and `validate_credential_config()`
- `backend/app/main.py` — register the new `bigquery_oauth` router
- `backend/app/services/workflow_executor.py` — add `elif node_type == "bigquery"` branch
- `backend/app/services/workflow_dsl_prompt.py` — document BigQuery node for the AI assistant

---

## Frontend Components

### heymrun frontend (modified files)

- `frontend/src/types/workflow.ts` — add `"bigquery"` to `NodeType` union
- `frontend/src/types/node.ts` — add `bigquery` entry to `NODE_DEFINITIONS`:
  ```ts
  bigquery: {
    type: "bigquery",
    label: "BigQuery",
    description: "Run SQL queries and insert rows into Google BigQuery",
    color: "node-google-sheets",   // reuse Google blue color token
    icon: "Database",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "bigquery",
      credentialId: "",
      bqOperation: undefined,
      bqProjectId: "",
      bqQuery: "",
      bqMaxResults: 1000,
      bqDatasetId: "",
      bqTableId: "",
      bqRowsInputMode: "raw",
      bqRows: "[]",
      bqMappings: [{ key: "field", value: "$input.text" }],
    },
  }
  ```
- Node panel component — credential picker (type: `bigquery`), operation selector, conditional fields per operation:
  - **query:** project ID, SQL textarea, max results
  - **insertRows:** project ID, dataset ID, table ID, input mode toggle, rows JSON textarea OR mapping rows

### heymweb landing page (separate repo, modified files)

- `src/components/sections/LogoCarousel.tsx` — add BigQuery logo to "Integrates With" carousel
- `src/components/sections/NodesSection.tsx` — add BigQuery to the node grid
- `src/components/sections/FeaturesSection.tsx` — mention BigQuery in integrations copy
- `src/app/page.tsx` — update `sr-only` SEO paragraphs to include BigQuery

---

## Testing

`backend/tests/test_bigquery_node.py` covers:

1. Successful `query` — mocked HTTP response returns rows; assert `output.rows` populated and `success: True`
2. `insertRows` in raw mode — JSON array passed directly; assert `insertedCount` and `success: True`
3. `insertRows` in selective mode — mappings evaluated then assembled into a row object; assert correct payload sent
4. Missing credential → raises `ValueError("BigQuery node requires a credential")`
5. Missing operation → raises `ValueError("BigQuery node requires an operation")`
6. Token refresh path — expired token triggers refresh; new token persisted to DB (mocked)

---

## Workflow DSL Update

The `WORKFLOW_DSL_SYSTEM_PROMPT` in `workflow_dsl_prompt.py` will document the BigQuery node with:
- Supported operations (`query`, `insertRows`)
- Required fields per operation
- Expression syntax examples (e.g. `bqQuery: "SELECT * FROM \`project.dataset.table\` LIMIT $input.limit"`)
- Note on `bqRowsInputMode` for insertRows

---

## Documentation (heym-documentation skill)

Medium feature — requires doc updates:
- New BigQuery node reference page
- Update integrations overview to list BigQuery

---

## Out of Scope

- Table creation / deletion
- Dataset management
- Service account JSON auth (may be added later as a second credential type)
- Streaming queries / async job polling (synchronous queries only at launch; BQ synchronous query API handles jobs up to 10s automatically)
