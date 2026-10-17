# Slack

The **Slack** node posts to Slack and can wait for a person's answer there. With a **Slack Webhook** credential it sends one message to the webhook's channel. With a **Slack Bot** credential (a bot token, `xoxb-…`) it runs every operation below: channel messages, direct messages, thread replies, message updates, outcome cards, reactions, reading messages, and approvals, buttons and forms that pause the run until someone answers.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | Where the message landed (`channel`, `ts`, `threadTs`), or the answer for approvals, buttons and forms |

## Operations (Slack Bot credential)

| Operation | What it does | Waits |
|-----------|--------------|-------|
| Send channel message | Posts to a channel, or to a person's DMs when given their id or email | No |
| Send DM | Opens a direct message with a person (user id or email) and posts there | No |
| Reply in thread | Replies under a message; optionally also shows the reply in the channel | No |
| Update message | Replaces the text of a message an earlier step posted | No |
| Post final outcome | Posts a colored outcome card (success, failure, warning, info) | No |
| Request approval | Posts **Approve**, **Request changes** and **Reject** buttons | Yes |
| Send message with buttons | Posts up to five buttons; the one pressed continues the run | Yes |
| Send form | Posts a button that opens a Slack form with up to ten fields | Yes |
| Add reaction | Adds an emoji reaction to a message | No |
| Delete message | Deletes a message the bot posted | No |
| Read messages | Reads a channel's latest messages, or a thread's replies | No |
| Find person | Looks a person up by id or email | No |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `credentialId` | UUID | A Slack Webhook or Slack Bot credential from [Credentials](../tabs/credentials-tab.md) |
| `slackOperation` | string | One of the operations above (Slack Bot only, default `sendMessage`) |
| `slackChannel` | expression | `#name`, a channel id (`C…`), or a person (user id `U…` or email) to post in their DMs |
| `slackUser` | expression | The person for **Send DM** and **Find person** |
| `message` | expression | Message text in Slack formatting. Supports [expressions](../reference/expression-dsl.md). |
| `slackThreadTs` | expression | The thread to post in, such as `$announce.threadTs` |
| `slackMessageTs` | expression | The message to update, react to or delete, such as `$announce.ts` |
| `slackButtons` | list | Up to five `{label, value, style}` buttons |
| `slackFormTitle`, `slackSubmitLabel`, `slackFormFields` | text, list | The form's title, submit button and fields (`text`, `multiline`, `number`, `email`, `date`, `select`) |
| `slackAllowedUsers` | expression | Who may answer an approval, buttons or a form: user ids or emails, comma separated. Empty lets anyone in the channel answer. |
| `slackOutcomeStatus`, `slackOutcomeTitle` | text | The outcome card's color and headline. The status can follow an approval: `$approval.approval`. |

## Output

Posting operations output `channel`, `ts`, `threadTs` and `text`, so a later Slack step can reply in the same thread or update the message.

**Read messages** outputs `transcript`: the messages oldest first, one `[time] name: text` per line, ready for an [LLM](./llm-node.md) to summarize. It also outputs the raw `messages` list and `count`.

Messages are posted in Slack's own formatting. Markdown that a model writes, such as `**bold**`, `## Heading`, `[text](url)` or `- item`, is converted before posting, so an LLM's answer can go into a message as it is.

Approvals, buttons and forms pause the run. The same request appears in the Heym inbox and in Heym Work's Activity, so it can be decided there as well as in Slack. When it is answered, the step outputs the posting fields plus:

| Field | Description |
|-------|-------------|
| `answeredBy.id`, `answeredBy.name` | The Slack person who answered (empty when decided in Heym) |
| `answeredIn` | `slack` or `heym` |
| `approval` | `approved`, `changes_requested` or `rejected` (approvals) |
| `comment` | What the reviewer asked to change (approvals) |
| `choice.label`, `choice.value` | The button pressed (buttons) |
| `values.<field>` | Each form field by its output key (forms) |

Branch on the answer with a [Condition](./condition-node.md) or [Switch](./switch-node.md) node, for example `$approval.approval == "approved"`.

## Setup

**Slack Webhook:** create an Incoming Webhook in your Slack workspace and add it as a Slack Webhook credential.

**Slack Bot:**

1. In the credential dialog, choose **Slack Bot (Token)** and select **Copy app manifest**.
2. At [api.slack.com/apps](https://api.slack.com/apps), create an app **from a manifest** and paste it. The manifest asks for every scope the operations need.
3. Install the app to your workspace, then paste the **Bot User OAuth Token** and the **Signing Secret** into the credential and save it.
4. Open the credential again and copy its **Interactivity Request URL** into the Slack app under **Interactivity & Shortcuts**. Approvals, buttons and forms send their answers there.
5. Invite the bot to private channels it should post in (`/invite @Heym`).

The same Slack Bot credential also verifies [Slack Trigger](./slack-trigger-node.md) events. A flow that listens with it ignores the bot's own posts and edits, so replying in the channel it listens to does not start it again.

## Example: approval with an outcome in the same thread

```json
{"type": "slack", "data": {"label": "approval", "credentialId": "slack-credential-uuid", "slackOperation": "requestApproval", "slackChannel": "#finance-approvals", "message": "Refund of $userInput.body.amount for $userInput.body.customer"}}
```

```json
{"type": "slack", "data": {"label": "outcome", "credentialId": "slack-credential-uuid", "slackOperation": "postOutcome", "slackChannel": "$approval.channel", "slackThreadTs": "$approval.threadTs", "slackOutcomeStatus": "$approval.approval", "slackOutcomeTitle": "Refund $approval.approval", "message": "Decided by $approval.answeredBy.name"}}
```

Use with [Error Handler](./error-handler-node.md) for failure notifications:
```json
"message": "Error in $errorHandler.errorNode: $errorHandler.error"
```

## Egress Safety

- The webhook URL stored in a Slack Webhook credential must use `http://` or `https://` and resolve only to public addresses. Loopback, private, link-local, multicast, and cloud-metadata destinations are blocked.
- Heym validates the resolved addresses and pins the connection target before sending, so a DNS answer cannot move the request onto an internal address after the check. Environment proxies are disabled while the guard is active, and redirects are not followed.
- Deployments that post to an internal webhook receiver can set `HEYM_HTTP_ALLOW_PRIVATE_URLS=true` on a trusted self-hosted instance. Keep the default on hosted or multi-tenant deployments.
- Slack Bot calls go only to `https://slack.com/api`. Answers from Slack are accepted only with a valid signature from the credential's signing secret.

**Upgrade note for v0.0.109:** this check is new for Slack. A credential whose webhook URL points at loopback or a private address is refused unless the setting above is enabled.

## Related

- [Node Types](../reference/node-types.md) – Overview of all node types
- [Slack Trigger](./slack-trigger-node.md) – Start a workflow from a Slack message
- [Human-in-the-Loop](../reference/human-in-the-loop.md) – Reviews and the inbox
- [Error Handler](./error-handler-node.md) – Send Slack on workflow failure
- [Credentials Tab](../tabs/credentials-tab.md) – Add Slack credentials
