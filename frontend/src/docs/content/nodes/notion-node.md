# Notion

The **Notion** node manages databases, data sources, pages, and blocks through the Notion API.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | Internal integration token or Notion OAuth |
| API version | `2026-03-11` |

Notion database-style collections use **data source IDs** in current API versions. Share every page
or data source that the workflow needs with the integration before running the node.
Resource fields accept either a raw Notion ID or a full Notion URL. URLs are normalized to their
embedded resource ID before the API request.

## Operations

| Operation | Required fields | Main output |
|-----------|-----------------|-------------|
| Search | Optional query/filter/sort | `.results`, `.count`, `.next_cursor` |
| Get Page | Page ID | `.page` |
| Create Page | Data Source ID or Parent Page ID, Properties | `.page`, `.id`, `.url` |
| Update Page | Page ID, one of Properties/Icon/Cover | `.page` |
| Move Page to Trash | Page ID | `.page` |
| Restore Page | Page ID | `.page` |
| Create Database | Database request with `parent` | `.database`, `.id`, `.url` |
| Retrieve Database | Database ID | `.database` |
| Update Database | Database ID, non-empty database request | `.database`, `.id`, `.url` |
| Create Data Source | Data source request with `parent` and non-empty `properties` | `.data_source`, `.id`, `.url` |
| Retrieve Data Source | Data Source | `.data_source` |
| Update Data Source | Data Source ID, non-empty data source request | `.data_source`, `.id`, `.url` |
| Query Data Source | Data Source ID | `.results`, `.count`, `.next_cursor` |
| Get Block Children | Block or Page ID | `.results`, `.count`, `.next_cursor` |
| Update Block | Block ID, block update object | `.block` |
| Delete Block | Block ID | `.block` |
| Append Blocks | Block or Page ID, Children | `.results`, `.count` |

All operations also return `.success` and `.operation`.

## JSON fields

The Database Request, Data Source Request, Properties, Children, Filter, Sort, Sorts, Icon, and Cover fields accept
Notion API JSON. Expressions inside JSON strings are resolved before the request. A field can also
be one standalone expression that resolves directly to the required object or array, such as
`$input.database`, `$input.properties`, or `$input.children`.

```json
{
  "Name": {
    "title": [
      {
        "text": {
          "content": "$input.title"
        }
      }
    ]
  }
}
```

For page or block content, Children is an array of Notion block objects:

```json
[
  {
    "object": "block",
    "type": "paragraph",
    "paragraph": {
      "rich_text": [
        {
          "type": "text",
          "text": {
            "content": "$input.description"
          }
        }
      ]
    }
  }
]
```

## Databases and data sources

In the current Notion API, a **database** is a container and a **data source** holds the property
schema and queryable rows. Retrieve Database returns the database's `data_sources` list; use one of
those IDs with Retrieve Data Source or Query Data Source.

Create Database accepts the complete request object from Notion's Create a database endpoint. It
must contain `parent` and may contain `title`, `description`, `is_inline`,
`initial_data_source`, `icon`, and `cover`. For example:

```json
{
  "parent": {
    "type": "page_id",
    "page_id": "$input.parentPageId"
  },
  "title": [
    {
      "type": "text",
      "text": {
        "content": "Tasks"
      }
    }
  ],
  "initial_data_source": {
    "properties": {
      "Name": {
        "title": {}
      }
    }
  }
}
```

Update Database accepts the update endpoint's request object, including `parent`, `title`,
`description`, `is_inline`, `icon`, `cover`, `in_trash`, and `is_locked`. Database ID fields accept
a raw ID, full Notion URL, or expression.

Use **Retrieve Data Source** to fetch the data source's `properties` schema before building a
Create Page properties object. **Create Data Source** requires a parent database object and a
non-empty `properties` schema. **Update Data Source** accepts a non-empty request object supported
by the corresponding Notion endpoint.

For example, create a data source inside an existing database:

```json
{
  "parent": {
    "type": "database_id",
    "database_id": "$input.databaseId"
  },
  "properties": {
    "Name": {
      "title": {}
    },
    "Status": {
      "status": {}
    }
  }
}
```

The Data Source and Parent Page selectors support server-side search with a short debounce and
cursor-based **Load more** pagination. Use **Refresh** after sharing a new resource in Notion.
Switch to **Use expression** to enter an expression, raw ID, or URL.

Search filters from older tutorials that use
`{"property":"object","value":"database"}` are translated to the current `data_source` value.
New workflows should use `data_source` or `page` directly.

Append Blocks supports **Start**, **End**, and **After Block** positions. Create Page and Append
Blocks automatically split more than 100 top-level children into ordered requests to satisfy
Notion's per-request limit.

Rate-limited requests (`429` or `529`) retry up to three times. Heym honors Notion's
`Retry-After` header, caps each wait at 10 seconds, and adds randomized jitter. Notion requests
share a process-wide HTTP connection pool across pages and workflow nodes.

## Notion API limits

- A single rich-text `text.content` value can contain at most 2,000 characters. Split longer text
  into multiple rich-text objects.
- Notion limits top-level block children to 100 per request. Heym batches larger Children arrays,
  but each individual block must still satisfy Notion's payload limits.
- The API accepts at most two nested levels of block children in one request. Create deeper
  structures with follow-up Append Blocks operations.
- Request payloads are limited to 1,000 block elements and 500 KB overall.

## Pagination

Search, Query Data Source, and Get Block Children accept a page size from 1 to 100 and an optional
start cursor. Set page size to `0` to follow cursors automatically and merge all results, up to the
node's 10,000-result safety limit.

## Credential setup

Choose either setup in the credential dialog (**Internal token** or **OAuth**):

- **Internal token:** Create an internal integration, copy its token into Heym, then share each
  required page or data source with the integration. Use **Test Connection** to verify access.
- **OAuth:** Create a public Notion integration and register
  `{FRONTEND_URL}/api/credentials/notion/oauth/callback` in Notion. In the Heym credential dialog,
  choose **OAuth**, enter the integration's Client ID and Client Secret, then click **Connect** to
  authorize a workspace. The secret is stored encrypted with the credential and is not placed in
  OAuth state or environment configuration. After authorization, the credential shows the
  connected workspace name (`connected (Workspace Name)`). Pending OAuth credentials show
  `Not connected`.

Leaving the internal token field blank while editing preserves the stored token.

For custom [HTTP](../nodes/http-node.md) requests, `$credentials.YourNotionCredential` resolves to
the same bearer token the Notion node uses (internal token or OAuth access token).

## API version notes

Heym pins Notion requests to API version `2026-03-11`. This version uses:

- `data_source_id` parents and `/data_sources` endpoints instead of legacy database-query paths
- `in_trash` instead of `archived` for page trash/restore operations
- `position` objects (`start`, `end`, `after_block`) for Append Block Children

When migrating older Notion automation examples:

- Replace database parent/query references with data source IDs from **Retrieve Database** or the
  editor data-source picker
- Replace `archived: true` with `in_trash: true`
- Replace append `after` parameters with the node's **Append Position** field

Search filters that still use object value `database` are normalized to `data_source` automatically.

## Related

- [Credentials](../reference/credentials.md)
- [Third-Party Integrations](../reference/integrations.md)
- [Node Types](../reference/node-types.md)
