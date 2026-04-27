# Crawler

The **Crawler** node scrapes web pages using FlareSolverr with optional HTML extraction via CSS selectors. Use it for web scraping and content extraction.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.body` (HTML or extracted content) |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | FlareSolverr credential from [Credentials](../tabs/credentials-tab.md) |
| `crawlerUrl` | expression | URL to scrape (supports expressions) |
| `crawlerWaitSeconds` | number | Seconds to wait before scraping (default: 0) |
| `crawlerMaxTimeout` | number | Max timeout in ms (default: 60000) |
| `crawlerMode` | string | `"basic"` or other modes |
| `crawlerSelectors` | array | CSS selectors for extraction. Each: `{ selector, attribute? }` |

## Example

```json
{
  "type": "crawler",
  "data": {
    "label": "scrapePage",
    "credentialId": "flaresolverr-credential-uuid",
    "crawlerUrl": "$userInput.body.url",
    "crawlerWaitSeconds": 2,
    "crawlerSelectors": [
      { "selector": "h1" },
      { "selector": ".content", "attribute": "innerHTML" }
    ]
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Playwright Node](./playwright-node.md) – Browser automation alternative
- [Credentials Tab](../tabs/credentials-tab.md) – Add FlareSolverr credential
