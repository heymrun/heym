# ClickHouse

The **ClickHouse** node runs CRUD, count, and raw SQL operations against an external [ClickHouse](https://clickhouse.com/) database over its HTTP interface. Use it to write events into a ClickHouse table from a workflow, read or aggregate analytics data, or run arbitrary SQL — without hand-writing HTTP requests.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | ClickHouse |
| Output | `$nodeLabel.rows`, `$nodeLabel.count`, `$nodeLabel.row`, `$nodeLabel.success` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | ClickHouse credential from [Credentials](../tabs/credentials-tab.md) |
| `clickhouseOperation` | string | Operation: `query`, `find`, `getAll`, `count`, `getById`, `insert`, `update`, `remove`, or `upsert` |
| `clickhouseTable` | expression | Simple table name. Required for every operation except `query`. |
| `clickhouseQuery` | expression | Raw SQL for `query`. `SELECT`/`SHOW`/`DESCRIBE` return rows; other statements run as commands. |
| `clickhouseFilter` | expression | JSON object of equality filters, e.g. `{"status":"active"}`. Used by `find`, `count`, `update`, and `remove`. Values are parameterized. |
| `clickhouseLimit` | string | Maximum rows for `find` / `getAll` (`0` = unlimited, no LIMIT clause). Default `100`. |
| `clickhouseSort` | expression | Optional `column` or `column ASC\|DESC` for `find` |
| `clickhouseRowId` | expression | Value matched against the table's `id` column for `getById` |
| `clickhouseInputMode` | string | For `insert`/`upsert`: `raw` JSON array mode or `selective` key/value field mode |
| `clickhouseData` | expression | JSON array of row objects for `insert`/`upsert`, or JSON object of column values for `update` |
| `clickhouseMappings` | array | `{key, value}` pairs used when `clickhouseInputMode` is `selective` |

## Credential Setup

Create a **ClickHouse** credential in the [Credentials tab](../tabs/credentials-tab.md) with:

1. **Host** — the HTTP host without scheme, for example `your-instance.clickhouse.cloud`
2. **Port** — the HTTP interface port (`8443` for HTTPS, `8123` for HTTP)
3. **Username** / **Password** — defaults to `default` with an empty password
4. **Database** — defaults to `default`
5. **Secure** — enable for HTTPS (ClickHouse Cloud)

The node connects over the official `clickhouse-connect` HTTP client. Use **Test connection** in the credential dialog to verify reachability before saving.

## Operations

| Operation | Required Fields | Description |
|-----------|-----------------|-------------|
| `query` | `clickhouseQuery` | Run raw SQL. `SELECT` returns `{rows, count}`; other statements return `{result}`. |
| `find` | `clickhouseTable` | Read rows with optional equality filters, sort, and limit |
| `getAll` | `clickhouseTable` | Read rows up to the limit with no filter |
| `count` | `clickhouseTable` | Count rows, optionally filtered |
| `getById` | `clickhouseTable`, `clickhouseRowId` | Read a single row by its `id` column |
| `insert` | `clickhouseTable`, `clickhouseData` or mappings | Insert one or more rows |
| `update` | `clickhouseTable`, `clickhouseData`, `clickhouseFilter` | Update matching rows via `ALTER TABLE ... UPDATE` |
| `remove` | `clickhouseTable`, `clickhouseFilter` | Delete matching rows via `DELETE FROM` |
| `upsert` | `clickhouseTable`, `clickhouseData` or mappings | Insert rows (assumes a `ReplacingMergeTree` table) |

## Filter Syntax

`clickhouseFilter` is a flat JSON object of column equality checks. Values are sent as bound query parameters, so they are safe against injection.

```json
{ "status": "active", "tenant_id": 42 }
```

This compiles to `WHERE status = {…:String} AND tenant_id = {…:Int64}`. Only equality is supported in the filter builder — for ranges, joins, or aggregations, use the `query` operation with raw SQL.

## Input Modes (insert / upsert)

- **JSON array** (`raw`): provide a JSON array of row objects in `clickhouseData`. Keys that are missing from a given row are inserted as `NULL`. The column set is the union of keys across all rows.
- **Key-value** (`selective`): after you select a credential and table, the editor discovers the table columns and creates one value field per column. One row is inserted per execution; each value supports expressions.

## Mutations and ClickHouse Semantics

ClickHouse is an OLAP database, so row-level writes behave differently from an OLTP store:

- **`update`** issues `ALTER TABLE … UPDATE` and **`remove`** issues `DELETE FROM`. Both are **asynchronous mutations** — they are applied eventually and are comparatively costly. Prefer batched writes over frequent single-row mutations.
- **`upsert`** performs an `INSERT`. To get merge-on-key behavior, back the table with a `ReplacingMergeTree` engine.
- **`getById`** assumes the table has an `id` column.
- `update` and `remove` require a non-empty `clickhouseFilter` to avoid full-table mutations.

## Output Reference

| Output field | Type | Description |
|-------------|------|-------------|
| `.rows` | array | Returned row objects (`query` SELECT, `find`, `getAll`) |
| `.count` | number | Row count (`find`, `getAll`, `count`, `insert`/`upsert`) |
| `.row` | object | Single row or `null` (`getById`) |
| `.result` | string | Command summary for non-SELECT `query` |
| `.success` | boolean | Whether the operation succeeded |

## Example – Insert an Event

```json
{
  "type": "clickhouse",
  "data": {
    "label": "logEvent",
    "credentialId": "clickhouse-credential-uuid",
    "clickhouseOperation": "insert",
    "clickhouseTable": "events",
    "clickhouseInputMode": "raw",
    "clickhouseData": "[{\"id\": \"$input.id\", \"event\": \"signup\", \"ts\": \"$input.ts\"}]"
  }
}
```

## Example – Count Active Users

```json
{
  "type": "clickhouse",
  "data": {
    "label": "activeCount",
    "credentialId": "clickhouse-credential-uuid",
    "clickhouseOperation": "count",
    "clickhouseTable": "users",
    "clickhouseFilter": "{\"status\":\"active\"}"
  }
}
```

Access output: `$activeCount.count`.

## Example – Daily Report Query

```json
{
  "type": "clickhouse",
  "data": {
    "label": "dailyReport",
    "credentialId": "clickhouse-credential-uuid",
    "clickhouseOperation": "query",
    "clickhouseQuery": "SELECT event, count() AS total FROM events WHERE ts >= today() GROUP BY event ORDER BY total DESC"
  }
}
```

Access output: `$dailyReport.rows`, `$dailyReport.count`.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Credentials Tab](../tabs/credentials-tab.md) – Add ClickHouse credentials
- [Third-Party Integrations](../reference/integrations.md) – Integration credential setup
