# Settings

The Settings dialog lets you manage your profile, set persistent AI instructions, update your account password, configure chat voice, set your default AI credential and model, and review observability status. Open it by clicking **your avatar and name** in the top-right corner of the header.

## Opening the Dialog

Click **your avatar and name** in the top-right of the header. The dialog opens with these tabs: **Profile**, **Security**, **Voice**, **AI Defaults**, and **Observability**. Instance administrators also see the **SSO**, **Heym Work** and **Instances** tabs.

## Profile Tab

### Profile Picture

Heym shows your [Gravatar](https://gravatar.com) picture for your account email in the header, next to your messages in [Chat](../tabs/chat-tab.md) and **Chat with Heym**, on [Board](../tabs/board-tab.md) comments, and next to your name in share dialogs and team member lists. To change it, update the picture on Gravatar; Heym picks up the new one within a few hours. Without a Gravatar picture, Heym shows the first letter of your name.

The picture is fetched by the Heym server and cached there, so your browser never contacts Gravatar. If the server cannot reach Gravatar, everyone keeps seeing initials.

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

#### User Rules as memory

User Rules are also your memory across sessions. When you ask Chat to remember something ("remember that our CRM is HubSpot"), or you state a lasting preference or make a decision later conversations need, Chat adds one line to your User Rules. The next conversation starts with it, whether it runs in Heym, in Heym Work, or in an MCP client connected to your [default MCP server](../tabs/mcp-tab.md#memory-tools-get_user_memory-and-set_user_memory).

- Chat does not save after every message, and it tells you in one sentence what it saved.
- To change or remove something, ask Chat to forget or rewrite it, or edit the text here.
- API keys, tokens, passwords and other credentials are never saved. Heym refuses them; keep them in [Credentials](../tabs/credentials-tab.md).
- The limit is 4000 characters.
- This dialog reads the latest text each time it opens, so saving it keeps what Chat added.

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

If the current password is incorrect, an inline error message is shown. On success, a confirmation message appears and the form resets automatically. Changing the password also signs out every other session: other browsers and devices, Heym Work, and connected MCP clients. This browser stays signed in.

### Two-factor authentication

Shown only when the instance turns on two-factor sign-in (`HEYM_REQUIRE_MFA=true`) and your account has a password. Accounts that sign in through [SSO](./sso.md) do not see it: their identity provider owns the second factor.

You set up the authenticator at sign-in, the first time a password sign-in asks for it. This section shows since when it is on and how many recovery codes are left, and offers two actions:

| Action | What it asks for | What happens |
|--------|------------------|--------------|
| **Move to a new phone** | Your password and a code from the current authenticator (or a recovery code) | A new QR code is shown. Scan it, enter a code from the new app, and the old authenticator stops working. New recovery codes are shown once. |
| **New recovery codes** | A code from your authenticator | Ten new codes are shown once, and the old ones stop working at once. |

Two-factor sign-in cannot be turned off from here while the instance requires it. If you lose your phone and your recovery codes, an administrator can reset it from the **Users** tab; you then set up a new authenticator at your next sign-in.

### Sessions

**Sign out other sessions** ends every session except the one you are using: other browsers and devices, Heym Work, and MCP clients connected through OAuth. Use it after signing in on a shared computer or losing a device. Your MCP API key and execution tokens are keys rather than sessions, so they keep working; rotate them from the [MCP Tab](../tabs/mcp-tab.md) and the workflow's execution tokens if they may have leaked.

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

## Users Tab

Visible only to instance administrators, the accounts listed in `HEYM_ADMIN_EMAILS`. It lists every account with its sign-in methods (password, SSO), whether two-factor sign-in is set up, whether it is an administrator, and when it last signed in. Search by name or email, and filter by **Active** or **Deactivated**.

| Action | Effect |
|--------|--------|
| **Deactivate** | Blocks every sign-in (password, SSO, Heym Work, the MCP consent page). Ends every session, revokes refresh and MCP OAuth tokens, and stops the account's MCP API keys and execution tokens from working. Pauses the automatic triggers of every workflow the account owns. |
| **Reactivate** | Allows sign-in again. MCP API keys and execution tokens work again. Resumes only the triggers the deactivation paused; a workflow an administrator paused separately stays paused. |
| **Sign out** | Ends every session of the account without blocking its next sign-in. |
| **Reset 2FA** | Removes the authenticator and recovery codes, for someone who lost both. They set up a new one at their next password sign-in. |

You cannot deactivate yourself. When password sign-in is disabled for SSO, Heym also refuses to deactivate the last administrator who can still sign in with a password, so the instance keeps a way back in. Every action is audited (`user.deactivate`, `user.reactivate`, `user.sessions_revoke`, `user.mfa_reset`).

## SSO Tab

Visible only to instance administrators — the accounts listed in `HEYM_ADMIN_EMAILS`. This tab connects Heym to an external OpenID Connect provider so people sign in with the accounts they already have. Enter an issuer URL and client credentials, copy the read-only redirect URI into your provider, and run **Test connection** before enabling it. Password sign-in can be switched off from here once the test passes. See [Single Sign-On](./sso.md) for the full setup.

## Heym Work Tab

Instance administrators connect [Heym Work](./heym-work.md), the interface for business teams, here: its address, an integration key shown once, and the **Enable Heym Work** switch. The tab also shows when Heym Work last checked in, its version and its license status. See [Connecting Heym Work](./heym-work.md#connecting-heym-work).

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
