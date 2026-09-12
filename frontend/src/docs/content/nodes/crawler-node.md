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

## Egress Safety

- The FlareSolverr URL stored in the credential must use `http://` or `https://` and may not resolve to a link-local or cloud-metadata address. The refused set is `169.254.0.0/16`, `fe80::/10`, the Alibaba Cloud and AWS IPv6 metadata addresses, and the IPv6 transition forms that can carry one of them. It is a list of known endpoints, not a guarantee about every provider.
- Loopback and private addresses are allowed on purpose, so the documented `http://localhost:8191` setup and compose service names such as `http://flaresolverr:8191` keep working. The consequence is that this field can also be pointed at any other service the backend can reach on those addresses, and the response comes back in the node output. Credential sharing does not contain this: any signed-in user can create their own FlareSolverr credential, so withholding an existing one changes nothing. The controls that do apply are trusting the people who can author workflows, and network rules that limit what the backend can reach.
- Heym pins the resolved address before connecting, so a DNS answer cannot move the request onto a metadata address after the check. Environment proxies are disabled while the guard is active, and redirects are not followed.
- The page FlareSolverr then fetches for you is a separate hop that FlareSolverr resolves itself. Heym does not inspect it, so restricting where the FlareSolverr container may connect belongs to your network policy.
- Trusted self-hosted deployments can lift the metadata rule with `HEYM_HTTP_ALLOW_PRIVATE_URLS=true`. Keep the default on hosted or multi-tenant deployments.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Playwright Node](./playwright-node.md) – Browser automation alternative
- [Credentials Tab](../tabs/credentials-tab.md) – Add FlareSolverr credential
