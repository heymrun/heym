# User Settings

The User Settings dialog lets you manage your profile, set persistent AI instructions, and update your account password. Open it by clicking your **name** in the top-right corner of the header.

## Opening the Dialog

Click your **name/avatar badge** in the top-right of the header. The dialog opens with two tabs: **Profile** and **Security**.

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

## What Is Not in This Dialog

| Feature | Where to Find It |
|---------|-----------------|
| **API key management (MCP)** | [MCP Tab](../tabs/mcp-tab.md) – view, copy, and regenerate your MCP server API key |
| **Theme (dark / light)** | Sun/Moon toggle button in the header (next to the user badge) |
| **Email change** | Not currently supported |

## Related

- [AI Assistant](./ai-assistant.md) – Workflow builder chat that uses User Rules
- [Chat Tab](../tabs/chat-tab.md) – Dashboard chat that uses User Rules
- [MCP Tab](../tabs/mcp-tab.md) – MCP server API key and workflow tool exposure
- [Credentials Tab](../tabs/credentials-tab.md) – API keys for AI nodes and integrations
- [Security](./security.md) – Session management, rate limiting, credential encryption
