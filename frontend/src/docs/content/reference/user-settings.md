# Settings

The Settings dialog lets you manage your profile, set persistent AI instructions, update your account password, configure chat voice, set your default AI credential and model, and review observability status. Open it by clicking the **gear icon / your name** in the top-right corner of the header.

## Opening the Dialog

Click the **gear (Settings) badge** in the top-right of the header. The dialog opens with these tabs: **Profile**, **Security**, **Voice**, **AI Defaults**, and **Observability**. Instance administrators also see an **SSO** tab.

## Profile Tab

### Name

Your display name shown across the app. This field is required and cannot be left empty.

### User Rules

User Rules are custom instructions automatically injected into every AI request—both in the workflow builder and the dashboard chat. In the **workflow builder** ([AI Assistant](./ai-assistant.md)), they are appended to the system prompt used to generate workflow JSON. In the **dashboard chat**, they are applied as system-level context. You write them once and they apply globally without repeating them in each prompt.

**Common uses:**

- Language or tone: `Always respond in English. Keep responses concise.`
- Coding style: `Use async/await patterns. Prefer TypeScript interfaces over types.`
- Workflow conventions: `Include error handling in all workflows. Use descriptive node labels.`
- Response format: `Use bullet points. Avoid lengthy explanations.`

**Where they apply:**

| Context | Description |
|---------|-------------|
| **Workflow builder** | [AI Assistant](./ai-assistant.md) requests for generating or modifying workflows |
| **Dashboard chat** | All [Chat tab](../tabs/chat-tab.md) conversations |

User Rules are injected at the system level—they run before every prompt automatically, without any extra configuration per workflow or conversation.

### Saving Profile Changes

Click **Save Changes** to apply. Changes take effect immediately for all new AI requests.

## Security Tab

### Change Password

Use the Security tab to update your account password.

**Requirements:**

| Rule | Requirement |
|------|-------------|
| Minimum length | 8 characters |
| Uppercase | At least one uppercase letter (A–Z) |
| Lowercase | At least one lowercase letter (a–z) |
| Digit | At least one number (0–9) |

The password must also differ from your current password. These rules are enforced on both the frontend and the backend.

**Steps:**

1. Enter your **Current Password**
2. Enter your **New Password** (must meet all requirements above)
3. Re-enter in **Confirm New Password**
4. Click **Update Password**

If the current password is incorrect, an inline error message is shown. On success, a confirmation message appears and the form resets automatically.

## Voice Tab

The Voice tab configures spoken voice for the [Chat tab](../tabs/chat-tab.md): pick an **ElevenLabs credential** (or add one inline), choose a **Voice** from your ElevenLabs account, and **Save Voice Settings**. This enables per-message read-aloud and interactive voice mode. See [Chat Voice (TTS & STT)](./chat-voice.md) for the full flow.

## AI Defaults Tab

The AI Defaults tab has two sections.

### Preferred credential & model

Pick a **preferred LLM credential** and a **model** from it. This becomes the starting default for every AI feature in the app — chat, the [AI Assistant](./ai-assistant.md) (builder, analyzer, and workflow creation), board mapper, AI dashboard widgets, [docs chat](../tabs/chat-tab.md), the data-table AI schema helper, the expression builder, and evals — whenever that surface has no saved selection of its own.

The selection rule each surface follows is:

1. **Saved selection** — a choice you already made on that surface (for example a chat conversation's last model) always wins.
2. **Preferred** — used when there is no saved selection.
3. **First available credential** — the fallback when you have set no preference.

You can still change the credential and model per surface at any time; the preference only fills the initial default. Leave the credential as **No preference** to keep the previous first-credential behavior. If your preferred credential is later deleted or unshared, the tab shows a notice and surfaces silently fall back to the first available credential.

### Coding package usage

For each **Codex** credential (including shared ones) the tab shows remaining rate-limit usage as a horizontal bar per active window — for example a **5 hours** window and/or a **Weekly** window, depending on your plan. Each bar shows the percentage of quota left and a reset countdown. A **Refresh** button re-fetches on demand (results are cached briefly on the server).

For each **OpenCode** credential the tab shows the OpenCode Go subscription windows — **5 hours**, **Weekly** and **Monthly** — as the same style of bar, read from the gateway's authenticated usage endpoint with that credential's API key. A window that has hit its cap is shown as **"limit reached"** in amber. If the key is invalid or the workspace has no Go subscription, the card says why instead of showing bars.

## Observability Tab

The Observability tab shows the read-only status of [OpenTelemetry Tracing](./opentelemetry.md) for this instance: whether tracing is enabled, the OTLP endpoint, service name, sampler ratio, and which spans are emitted. Tracing is configured through `HEYM_OTEL_*` environment variables on the backend, so this tab does not edit anything. When tracing is disabled, the tab lists the environment variables needed to turn it on. Secrets such as OTLP auth headers are never shown here. See [Environment Variables](https://github.com/heymrun/heym/blob/main/ENVIRONMENT-VARIABLES.md) for the full configuration reference.

## SSO Tab

Visible only to instance administrators — the accounts listed in `HEYM_ADMIN_EMAILS`. This tab connects Heym to an external OpenID Connect provider so people sign in with the accounts they already have. Enter an issuer URL and client credentials, copy the read-only redirect URI into your provider, and run **Test connection** before enabling it. Password sign-in can be switched off from here once the test passes. See [Single Sign-On](./sso.md) for the full setup.

## Instances Tab

Visible only to instance administrators — the accounts listed in `HEYM_ADMIN_EMAILS`. This tab lists the Heym instances connected to this database and sets how background runs are split between them. Each row shows the instance's editable name, its role, whether it is live, its measured latency to the database, an on/off switch, and its weight. Weights are shares of the instances that can currently take work, not percentages of 100: with `41 / 26 / 33` and the third instance off, the first two really receive 61% and 39%. The panel prints that effective split under the table, and only refuses to save when no enabled instance has a weight at all.

**Give new instances a share automatically** is on by default: an instance that joins would otherwise sit at weight 0 and receive nothing, so the leader gives it an equal share once and scales the existing weights down keeping their ratios. It never touches an instance whose weight you set yourself.

The panel also reports how many of the last 24 hours' runs could only execute on the main instance. When that share is high, the weights below it cannot move that work. See [Load Distribution](./cluster.md) for what stays on main and how to choose the numbers.

## What Is Not in This Dialog

| Feature | Where to Find It |
|---------|-----------------|
| **API key management (MCP)** | [MCP Tab](../tabs/mcp-tab.md) – view, copy, and regenerate your MCP server API key |
| **Theme (dark / light)** | Sun/Moon toggle button in the header (next to the user badge) |
| **Email change** | Not currently supported |

## Related

- [AI Assistant](./ai-assistant.md) – Workflow builder chat that uses User Rules
- [Chat Tab](../tabs/chat-tab.md) – Dashboard chat that uses User Rules
- [Chat Voice (TTS & STT)](./chat-voice.md) – ElevenLabs voice configured in the Voice tab
- [MCP Tab](../tabs/mcp-tab.md) – MCP server API key and workflow tool exposure
- [Credentials Tab](../tabs/credentials-tab.md) – API keys for AI nodes and integrations
- [Security](./security.md) – Session management, rate limiting, credential encryption
- [Single Sign-On](./sso.md) – Connect an external OpenID Connect provider
- [OpenTelemetry Tracing](./opentelemetry.md) – Distributed tracing for workflow and node executions
