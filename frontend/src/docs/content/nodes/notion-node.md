# Notion

The **Notion** node searches and manages pages, data sources, and blocks through the Notion API.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Credential | Notion internal integration token |
| API version | `2026-03-11` |

Notion database-style collections use **data source IDs** in current API versions. Share every page
or data source that the workflow needs with the integration before running the node.

## Operations

| Operation | Required fields | Main output |
|-----------|-----------------|-------------|
| Search | Optional query/filter/sort | `.results`, `.count`, `.next_cursor` |
| Get Page | Page ID | `.page` |
| Create Page | Data Source ID or Parent Page ID, Properties | `.page`, `.id`, `.url` |
| Update Page | Page ID, Properties | `.page` |
| Move Page to Trash | Page ID | `.page` |
| Restore Page | Page ID | `.page` |
| Query Data Source | Data Source ID | `.results`, `.count`, `.next_cursor` |
| Get Block Children | Block or Page ID | `.results`, `.count`, `.next_cursor` |
| Append Blocks | Block or Page ID, Children | `.results`, `.count` |

All operations also return `.success` and `.operation`.

## JSON fields

The Properties, Children, Filter, Sort, Sorts, Icon, and Cover fields accept Notion API JSON.
Expressions inside JSON strings are resolved before the request:

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

## Pagination

Search, Query Data Source, and Get Block Children accept a page size from 1 to 100 and an optional
start cursor. Set page size to `0` to follow cursors automatically and merge all results, up to the
node's 10,000-result safety limit.

## Credential setup

1. Create an internal integration in Notion.
2. Copy its internal integration token.
3. Create a **Notion** credential in Heym and test the connection.
4. In Notion, share each required page or data source with the integration.

Leaving the token field blank while editing preserves the stored token.

## Related

- [Credentials](../reference/credentials.md)
- [Third-Party Integrations](../reference/integrations.md)
- [Node Types](../reference/node-types.md)
