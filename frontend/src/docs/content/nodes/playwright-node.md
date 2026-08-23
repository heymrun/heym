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
| `playwrightMode` | string | `"steps"` (default) or `"code"` (Run Code). Choose in the Properties Panel Mode dropdown |
| `playwrightSteps` | array | Steps: navigate, click, type, aiStep, etc. Each step has action and selector/params. `disabled: true` keeps a step in the list but skips it at runtime |
| `playwrightCode` | string | Custom Playwright Python used when Mode is Run Code. Runs in the hardened sandbox and is **disabled by default** — see the security note below |
| `playwrightHeadless` | boolean | Run headless (default: true) |
| `playwrightStealth` | boolean | Opt-in Steps-mode setting that reduces common Playwright automation signals (default: false). Properties Panel label: Reduce automation flags |
| `playwrightTimeout` | number | Timeout in ms (default: 30000) |
| `playwrightCaptureNetwork` | boolean | Capture JSON responses, headers, cookies, and browser storage |
| `playwrightAuthEnabled` | boolean | Restore browser auth from cookies/storageState before running steps |
| `playwrightAuthStateExpression` | string | Expression or JSON that resolves to Playwright `storageState` or raw `cookies[]` |
| `playwrightAuthCheckSelector` | string | Selector that must be visible after auth bootstrap |
| `playwrightAuthCheckTimeout` | number | Timeout in ms for the authenticated selector check (default: 5000) |
| `playwrightAuthFallbackSteps` | array | Login-only fallback steps to run when cookie restore does not authenticate the page |

## Step Types

- **navigate** – Go to URL
- **refresh** – Reload the current page (optional step `timeout` in ms for the reload navigation)
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

## Turning a Step Off

Every step has a power toggle in its header. A step switched off shows its title struck through and dimmed, stays in the list with all its fields, and is skipped when the node runs — useful for isolating a failing selector without deleting work. The stored step carries `disabled: true`; steps without the flag run normally.

Disabled steps are invisible to the rest of the node: they do not satisfy the "first step must be `navigate`" rule of auth bootstrap, a disabled `aiStep` makes no LLM call, and disabled entries in `playwrightAuthFallbackSteps` are skipped too. Switching every step off fails the run with a message asking you to enable one.

## AI Step

The **aiStep** action uses an LLM to analyze the page HTML (and optionally a screenshot) and generate Playwright actions from natural-language instructions. The API accepts the same action names as manual steps (including `navigate`, `refresh`, `getText`, `getHTML`, `getAttribute`, `getVisibleTextOnPage`, `screenshot`, scrolls, etc.). **Auto heal** only replaces failed selector-based steps with alternatives for click, type, fill, hover, and selectOption.

| Option | Description |
|--------|-------------|
| `instructions` | What the AI should do (e.g. "Click the Login button") |
| `credentialId` | LLM credential (OpenAI, Google, or Custom) |
| `model` | Searchable list of models from the selected LLM credential |
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

## Reduce automation flags

Enable **Reduce automation flags** (`playwrightStealth: true`) when a site treats Playwright's bundled Chromium as a bot because of standard automation signals (`HeadlessChrome` in the user agent, `navigator.webdriver`, missing `window.chrome`).

This option applies only in **Steps** mode. It:

- Drops Chromium's `--enable-automation` flag and sets `--disable-blink-features=AutomationControlled`
- Sends a standard Chrome user agent (no `HeadlessChrome`)
- Restores common browser surfaces that Playwright leaves empty (`window.chrome`, plugins)
- Leaves the host GPU renderer unchanged when a GPU is available (local macOS/Windows). Linux/Docker has no GPU; Chromium’s software renderer string is reported as a typical Mali (ARM) or Mesa (x86) GPU instead of SwiftShader.

It does not hide that the session is driven over Chrome DevTools Protocol, and it is not a way to bypass site security, CAPTCHAs, or access controls. Use it for workflows you are authorized to run — internal tools, your own sites, and permitted browser automation.

Run Code mode is unchanged — custom scripts launch Chromium themselves.

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

## Run Code mode

In the Properties Panel, set **Mode** to **Run Code** to edit `playwrightCode` instead of visual steps. Auth bootstrap applies only to Steps mode.

Example (sandbox / Docker — Chromium needs `--no-sandbox`):

```python
from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=headless, args=["--no-sandbox"])
    page = browser.new_page()
    page.set_default_timeout(timeout_ms)
    page.goto("https://example.com")
    title = page.title()
    browser.close()
    print(json.dumps({"status": "ok", "results": {"title": title}}))
```

The wrapper provides `inputs`, `headless`, `timeout_ms`, and `capture_network`. You can embed `$nodeLabel.field` expressions in the code; print JSON with `status` and `results`.

## Custom code security

The `playwrightCode` field runs arbitrary Python. Because that is equivalent to code execution, it is **disabled by default** and, when enabled, is sandboxed:

- **Disabled by default.** Executing a node that has `playwrightCode` set fails with a clear error unless an operator sets `HEYM_PLAYWRIGHT_CUSTOM_CODE_ENABLED=true`. The check runs at execution time, so it also covers previously saved workflows and scheduled / sub-workflow runs.
- **Isolated when enabled.** Custom code does not run in the backend process. It runs in a hardened, throwaway sibling container with no Docker socket, no backend bind mounts, no backend secrets in its environment, dropped capabilities, `no-new-privileges`, and CPU / memory / PID limits. If Docker is unavailable the run fails closed. `HEYM_PLAYWRIGHT_SANDBOX=subprocess` opts back into the in-process path for trusted or local-dev use only (not a security boundary). Native `./run.sh` defaults to `subprocess` when no `HEYM_PLAYWRIGHT_SANDBOX_IMAGE` is set. `./deploy.sh` (Compose) and the GHCR single image resolve the sibling runner via `HEYM_PLAYWRIGHT_SANDBOX_IMAGE` (falling back to `HEYM_CODEX_DOCKER_IMAGE`) and use the matching venv path (`/app/.venv` vs `/app/backend/.venv`).
- **Chromium note.** The sandbox container runs as root by default, and Chromium refuses to run as root without `--no-sandbox`. Custom code that launches Chromium should pass it, for example `browser = p.chromium.launch(headless=True, args=["--no-sandbox"])`.

Step-based Playwright nodes (`playwrightSteps`) are fully generated by Heym (no arbitrary code), are unaffected by all of the above, and are always available — prefer them.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Crawler Node](./crawler-node.md) – Simpler web scraping with FlareSolverr
- [Credentials Sharing](../reference/credentials-sharing.md) – LLM credentials for AI steps
