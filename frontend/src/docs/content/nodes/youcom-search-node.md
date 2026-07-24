# You.com Search

The **You.com Search** node performs web searches using the You.com Search API. It can be a workflow starting point (no incoming edge) or receive input from upstream nodes.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 or 1 |
| Outputs | 1 |
| Output | `$nodeLabel.results`, `$nodeLabel.query`, `$nodeLabel.count`, `$nodeLabel.status` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `query` | string | Search query (supports template variables) |
| `count` | number | Number of results (1-20, default: 10) |
| `safesearch` | string | Safe search level: `off`, `moderate`, `strict` (default: `moderate`) |

## Configuration

The node uses environment variable `YDC_API_KEY` for authenticated search. Without an API key, it falls back to the keyless tier (100 free searches/day per IP).

To add an API key:
1. Set `YDC_API_KEY` environment variable in your Heym deployment
2. Restart the Heym backend service

## Response Format

```json
{
  "results": [
    {
      "title": "Page title",
      "url": "https://example.com/page",
      "snippet": "Page description or excerpt"
    }
  ],
  "query": "original search query",
  "count": 5,
  "has_api_key": true,
  "total_results": 15,
  "status": "success"
}
```

## Error Handling

On errors, the node returns:

```json
{
  "results": [],
  "query": "search query",
  "count": 0,
  "status": "error",
  "error": "Error message",
  "suggestion": "Helpful suggestion"
}
```

## Accessing Results

- `$searchNode.results` – Array of search results
- `$searchNode.results[0].title` – First result title
- `$searchNode.results[0].url` – First result URL
- `$searchNode.results[0].snippet` – First result snippet
- `$searchNode.count` – Number of results returned
- `$searchNode.status` – Success/error status

## Example

```json
{
  "id": "search-1",
  "type": "youcomSearch",
  "data": {
    "label": "webSearch",
    "query": "AI workflow automation",
    "count": 5,
    "safesearch": "moderate"
  }
}
```

## Use Cases

- **Research workflows**: Gather information from the web
- **Content generation**: Find sources and references
- **Monitoring**: Search for specific terms or topics
- **Data enrichment**: Add web context to existing data

## Rate Limits

- **Keyless tier**: 100 searches/day per IP
- **API key**: Higher quotas based on your You.com plan
- **Rate limiting**: Automatic retry suggestions on 429 errors

## Security

The node includes SSRF protection and validates all URLs before making requests. Search queries are URL-encoded automatically.