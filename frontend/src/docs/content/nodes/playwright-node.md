# Playwright

The **Playwright** node automates browser interactions with configurable steps. Use it for web scraping, form filling, and browser-based workflows.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.results`, `$nodeLabel.screenshot`, and optional network/browser data |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `playwrightSteps` | array | Steps: navigate, click, type, aiStep, etc. Each step has action and selector/params |
| `playwrightCode` | string | Custom Playwright code (alternative to steps) |
| `playwrightHeadless` | boolean | Run headless (default: true) |
| `playwrightTimeout` | number | Timeout in ms (default: 30000) |
| `playwrightCaptureNetwork` | boolean | Capture JSON responses, headers, cookies, and browser storage |
| `playwrightAuthEnabled` | boolean | Restore browser auth from cookies/storageState before running steps |
| `playwrightAuthStateExpression` | string | Expression or JSON that resolves to Playwright `storageState` or raw `cookies[]` |
| `playwrightAuthCheckSelector` | string | Selector that must be visible after auth bootstrap |
| `playwrightAuthCheckTimeout` | number | Timeout in ms for the authenticated selector check (default: 5000) |
| `playwrightAuthFallbackSteps` | array | Login-only fallback steps to run when cookie restore does not authenticate the page |

## Step Types

- **navigate** – Go to URL
- **click** – Click element by selector
- **type** – Type text into input (character-by-character)
- **fill** – Fill input value
- **wait** – Wait for a timeout (ms)
- **screenshot** – Capture screenshot (`outputKey` stores base64 in results)
- **getText** – Text content of an element (`selector`, optional `outputKey`)
- **getAttribute** – Attribute value (`selector`, `attribute`, optional `outputKey`)
- **getHTML** – Outer HTML of an element (`selector`, optional `outputKey`)
- **getVisibleTextOnPage** – Full page visible text as `document.body.innerText` (no selector; use `outputKey`; optional step `timeout` in ms waits before capture)
- **hover** – Hover over element
- **selectOption** – Select option in a `<select>`
- **scrollDown** / **scrollUp** – Mouse wheel scroll (optional `amount` in pixels)
- **aiStep** – LLM returns the same kinds of actions as manual steps (see below); nested `aiStep` is not supported

## AI Step

The **aiStep** action uses an LLM to analyze the page HTML (and optionally a screenshot) and generate Playwright actions from natural-language instructions. The API accepts the same action names as manual steps (including `navigate`, `getText`, `getHTML`, `getAttribute`, `getVisibleTextOnPage`, `screenshot`, scrolls, etc.). **Auto heal** only replaces failed selector-based steps with alternatives for click, type, fill, hover, and selectOption.

| Option | Description |
|--------|-------------|
| `instructions` | What the AI should do (e.g. "Click the Login button") |
| `credentialId` | LLM credential (OpenAI, Google, or Custom) |
| `model` | Model to use |
| `saveStepsForFuture` | Cache generated steps for next runs (avoids LLM call) |
| `sendScreenshot` | Send screenshot to LLM for visual elements |
| `aiStepTimeout` | Timeout for LLM call in ms (default 30000) |

### AI Auto Heal

**AI Auto Heal** makes workflows resilient to DOM changes. When a selector fails twice (e.g. after a site redesign), Heym calls the LLM to find an alternative locator—typically `role=button[name='Submit']` or `text=Exact text` instead of CSS selectors.

Enable **Auto heal mode** in the AI step properties. If the saved step fails:

1. Heym captures the current HTML and screenshot
2. Sends the failed step + page context to the LLM
3. LLM returns a robust alternative (role-based locator, text locator, or fallback CSS)
4. Retries with the new selector

This reduces flakiness when sites update their markup or class names.

## Network Capture

Enable `playwrightCaptureNetwork` to collect extra debugging data during the run:

- `networkRequests` – Captured JSON/API responses
- `cookies` – Browser cookies at the end of the run
- `localStorage` – Browser `localStorage` key-value pairs
- `sessionStorage` – Browser `sessionStorage` key-value pairs

This is useful when you need to inspect hidden API calls, auth state, or browser-side data after an automated flow.

## Cookie Bootstrap And Login Fallback

Enable `playwrightAuthEnabled` when you want Playwright to open a page already logged in.

### Auth State Source

Set `playwrightAuthStateExpression` to an expression such as `$global.authState`. The value can be:

- A Playwright `storageState` object: `{"cookies": [...], "origins": [...]}`
- A raw `cookies[]` array
- A JSON string containing either shape

Recommended pattern:

1. Run a Playwright node with network capture or auth bootstrap enabled
2. Store `$playwrightNode.cookies` or a full auth state object in a [Global Variable](../reference/global-variables.md)
3. Reuse that variable in later Playwright nodes via `$global.authState`

### Auth Check

The first main Playwright step must be `navigate`. After that step loads, Heym checks `playwrightAuthCheckSelector`.

- If the selector is visible, the remaining main steps continue normally
- If the selector is missing, Heym runs `playwrightAuthFallbackSteps`
- After fallback steps complete, Heym checks the same selector again
- If the selector is still missing, the node fails with an auth bootstrap error

Fallback steps own navigation after auth failure. They should leave the browser on the authenticated page expected by the rest of the main flow.

## Output Fields

- `$playwrightNode.status` – `"ok"` on success
- `$playwrightNode.results` – Step outputs (getText, getHTML, getVisibleTextOnPage, getAttribute, screenshot keys, etc.)
- `$playwrightNode.screenshot` – Base64 screenshot when a step saves one
- `$playwrightNode.cookies` – Final browser cookies when auth bootstrap or network capture is enabled
- `$playwrightNode.networkRequests` – Captured network responses (when enabled)
- `$playwrightNode.localStorage` – Browser local storage (when enabled)
- `$playwrightNode.sessionStorage` – Browser session storage (when enabled)

## Example

```json
{
  "type": "playwright",
  "data": {
    "label": "browserAutomation",
    "playwrightSteps": [
      { "action": "navigate", "url": "$userInput.body.url" },
      { "action": "type", "selector": "#search", "text": "query" },
      { "action": "click", "selector": "button[type=submit]" }
    ],
    "playwrightHeadless": true
  }
}
```

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Crawler Node](./crawler-node.md) – Simpler web scraping with FlareSolverr
- [Credentials Sharing](../reference/credentials-sharing.md) – LLM credentials for AI steps
