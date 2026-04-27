# BigQuery

The **BigQuery** node runs SQL queries and inserts rows into Google BigQuery datasets via the BigQuery REST API v2. Use it to query large analytical datasets or stream rows into tables from workflow data.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | BigQuery (OAuth2) |
| Output | `$nodeLabel.rows`, `$nodeLabel.total`, `$nodeLabel.schema`, `$nodeLabel.insertedCount`, `$nodeLabel.errors` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | BigQuery credential from [Credentials](../tabs/credentials-tab.md) |
| `bqOperation` | string | Operation: `query` or `insertRows` |
| `bqProjectId` | expression | Google Cloud project ID (e.g. `my-gcp-project`) |
| `bqQuery` | expression | SQL query string. Required for `query`. |
| `bqMaxResults` | string | Max rows returned by `query` (default `1000`). |
| `bqDatasetId` | expression | Dataset ID (e.g. `my_dataset`). Required for `insertRows`. |
| `bqTableId` | expression | Table ID (e.g. `my_table`). Required for `insertRows`. |
| `bqRowsInputMode` | `raw` \| `selective` | For `insertRows`: **Raw** = full JSON array; **Selective** = single row as key-value field pairs. |
| `bqRows` | expression | JSON array of row objects for raw mode (e.g. `[{"col": "$input.value"}]`). |
| `bqMappings` | array | Key-value pairs for selective mode. Each key is a column name; each value is an expression. |

## Credential Setup

BigQuery uses an **OAuth2 "Bring Your Own App"** model. You provide your own Google Cloud OAuth2 credentials.

**Backend configuration:** Set **`FRONTEND_URL`** on the Heym backend to the public URL of the app (the address users type in the browser), e.g. `https://your-heym-domain`. The OAuth redirect URI is always `{FRONTEND_URL}/api/credentials/bigquery/oauth/callback`.

1. Go to [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services** → **Enable APIs** → enable **BigQuery API**.
2. Go to **Credentials** → **Create Credentials** → **OAuth client ID** → select **Web application**.
3. Under **Authorized redirect URIs**, add exactly: `{your FRONTEND_URL}/api/credentials/bigquery/oauth/callback`.
4. Copy the **Client ID** and **Client Secret**.
5. In Heym Dashboard → **Credentials** → **New** → select **BigQuery (OAuth2)**.
6. Enter the Client ID, Client Secret, and a name, then click **Connect** to complete the OAuth2 consent in a browser popup.

Tokens refresh automatically in the background — no manual token management required.

## Operations

| Operation | Required Fields | Description |
|-----------|-----------------|-------------|
| `query` | bqProjectId, bqQuery | Run a SQL query and return rows |
| `insertRows` | bqProjectId, bqDatasetId, bqTableId, bqRows or bqMappings | Insert one or more rows via the streaming insertAll API |

## Output Reference

| Operation | Output field | Type | Description |
|-----------|-------------|------|-------------|
| `query` | `.rows` | array | Array of row objects (column name → value) |
| `query` | `.total` | number | Number of rows returned |
| `query` | `.schema` | array | Table schema fields |
| `insertRows` | `.insertedCount` | number | Number of rows successfully inserted |
| `insertRows` | `.errors` | array | Insertion errors per row (empty on full success) |

## Example – Run a Query

```json
{
  "type": "bigquery",
  "data": {
    "label": "getUsers",
    "credentialId": "bigquery-credential-uuid",
    "bqOperation": "query",
    "bqProjectId": "my-gcp-project",
    "bqQuery": "SELECT id, name, email FROM `my_dataset.users` WHERE active = TRUE LIMIT 100",
    "bqMaxResults": "100"
  }
}
```

Access output: `$getUsers.rows` (array of row objects), `$getUsers.rows[0].email`, `$getUsers.total`.

## Example – Insert a Row

```json
{
  "type": "bigquery",
  "data": {
    "label": "logEvent",
    "credentialId": "bigquery-credential-uuid",
    "bqOperation": "insertRows",
    "bqProjectId": "my-gcp-project",
    "bqDatasetId": "analytics",
    "bqTableId": "events",
    "bqRowsInputMode": "selective",
    "bqMappings": [
      { "key": "event_name", "value": "$input.eventName" },
      { "key": "user_id", "value": "$input.userId" },
      { "key": "timestamp", "value": "$input.timestamp" }
    ]
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Credentials Tab](../tabs/credentials-tab.md) – Add BigQuery OAuth2 credential
- [Google Sheets](./google-sheets-node.md) – Similar OAuth2 pattern for spreadsheet data
- [Third-Party Integrations](../reference/integrations.md) – Integration credential setup
