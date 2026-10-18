# Heym Work

**Heym Work** is a second interface for business teams, built on top of Heym. People describe a job in their own words, answer a few questions, and get a workflow that Heym has built and tested. They work from pages built for them, answer reviews, and see every run with a name on it. Heym runs every job in the background.

Heym Work runs as its own container next to your Heym, with a separate license from the Heym team. Learn more and request a trial at [heym.run/enterprise](https://heym.run/enterprise). Watch the [Heym Work film](https://youtu.be/5Z2gGo6bcpU) for a two-minute tour.

## What Business Teams Get

| Area | What it does |
|------|--------------|
| **Chat** | Describe a job by typing or by voice. Heym asks what it needs, builds the workflow, tests it, and marks it Verified. |
| **Flows** | Editors build a flow from choices instead of a canvas: what starts it, an optional AI draft, and actions in Slack, Google Sheets and email. Answers from Slack continue the run, and approvals also wait in Activity. See [Flows](#flows). |
| **Pages** | Pinned pages of widgets: numbers, charts, tables with status chips, file drops and approvals. A table row can open its own detail page. |
| **Approvals** | Reviews from [Human-in-the-Loop](./human-in-the-loop.md) steps wait in Activity and on pages, with Approve, Request changes and Reject. |
| **Activity** | Every run, with the person who started it and the instance that ran it. |
| **Roles** | Owner, Editor and Viewer. People sign in with the [single sign-on](./sso.md) Heym already uses. |
| **Industry and team editions** | Legal, education, finance, logistics, energy and e-commerce editions, plus IT, sales, marketing and HR editions for company teams, open with pages, sample data and workflows for that work. |

## Flows

**Flows** is in Heym Work's menu for Editors and Owners. A flow is made from choices rather than nodes, and Heym Work saves it as an ordinary Heym workflow through Heym's API, as the person who built it. Heym's access rules, Edit History and trigger sync apply as they do in the editor, and every run shows in Activity like any other.

| Part | Choices |
|------|---------|
| **What starts it** | On demand, on a schedule, on a Slack message, when a Google Sheets tab changes (rows added, changed or deleted), or when an email reaches an inbox. Sheet and email triggers check every 1, 5, 15 or 60 minutes. |
| **AI draft** (optional) | A model and instructions turn what started the flow into text for the steps after it. A flow that does not start from a sheet or an email can first read recent Slack messages from a channel or a thread. |
| **What happens next** | Actions in order, in any of the three tools, whatever started the flow. **Slack:** channel message, direct message, form, message with buttons, approval, thread reply, message update and final outcome. **Google Sheets:** add a row, or update the row that changed. **Email:** send an email. |

- **Answers continue the run.** An approval, buttons or a form pause the run until someone answers in Slack. An approval also waits in Activity, and a decision in either place takes the buttons off the Slack message. Later Slack steps stay in the first message's thread.
- **One Connections card.** Each flow shows the Slack workspace, the Google Sheets account and the inboxes it reads from and sends with. They are Heym credentials: **Slack Bot** (a bot token, `xoxb-…`), **Google Sheets**, **IMAP** and **SMTP**, and a missing one can be added from the flow itself.
- **One Slack app for every flow.** In the Slack app, set the Interactivity Request URL to `https://<your Heym>/api/slack/interactions/<credential id>` and the Event Subscriptions Request URL to `https://<your Heym>/api/slack/events/<credential id>`. Heym Work shows both for the chosen connection. Every flow on that credential shares them.
- **Slack triggers choose what they hear:** messages in channels and DMs, direct messages to the bot, mentions of the bot, or messages in one channel. The bot's own posts never start a flow.
- **Requirements.** Flows need Heym 0.0.131 or later.

The steps a flow builds are the same nodes you can use on the canvas: [Slack](../nodes/slack-node.md), [Slack Trigger](../nodes/slack-trigger-node.md), [Google Sheets](../nodes/google-sheets-node.md), [Google Sheets Trigger](../nodes/google-sheets-trigger-node.md), [IMAP Trigger](../nodes/imap-trigger-node.md), [Send Email](../nodes/send-email-node.md) and [Cron](../nodes/cron-node.md).

## Connecting Heym Work

Watch the [install video](https://youtu.be/zXGfg1HPSLk) for the whole setup, from the first command to Home.

The connection is set up in **Settings → Heym Work**. The tab appears only for instance administrators, the accounts listed in `HEYM_ADMIN_EMAILS`.

| Field | What it does |
|-------|--------------|
| **Heym Work address** | Where Heym Work runs, for example `https://work.example.com`. Sign-in returns there. Press **Save**. |
| **Integration key** | **Generate key** creates the key Heym Work uses for every request to Heym. It is shown once, with a copy button. Heym stores only its hash. |
| **Enable Heym Work** | Turns the connection on. It needs the address and a key first. |
| Status | **Last seen**, **Work version** and **License**, as Heym Work last reported them. |

Then open Heym Work's address and finish its setup:

1. **License**: enter the license key from the Heym team.
2. **Heym**: enter Heym's address and the integration key.
3. **Owner**: sign in with an account listed as a Heym Work Owner.

Home opens, ready for the team.

### Rotating the Key

**Rotate key** replaces the integration key. Heym Work stops working until the new key is entered there, and everyone signed in to Heym Work is signed out. Use it when the key may have leaked or when someone who saw it leaves.

### Disabling the Connection

Switch off **Enable Heym Work** to stop the connection. Heym Work then asks for Heym's key again. Heym keeps running every workflow, schedule and webhook either way.

## Security Model

- **Every change goes through Heym.** Heym Work reads what it shows from Heym's database, and sends every action to Heym over the key-protected channel, where Heym applies its own access rules. Heym Work keeps its own data in a separate `heym_work` schema.
- **The key is hashed at rest.** Heym compares a hash of the presented key and never stores the key itself.
- **Sign-in stays with Heym.** People sign in through Heym, with your identity provider when [SSO](./sso.md) is on.
- **Changes are audited.** Saving the connection and rotating the key write `work_integration.update` and `work_integration.key_rotate` lines to the [audit log](./audit.md).

## Licensing

Heym Work needs its own license key, issued by the Heym team. Each day Heym Work sends heym.run its license ID, an installation ID, the number of active users in the last 30 days, the total number of members, the number of runs in the last 24 hours, and the Heym and Heym Work versions. Workflow content, inputs, outputs and credentials stay on your servers.

If the daily sync fails for 30 days, a 14-day grace period starts, and after it the Heym Work interface asks an Owner for a key. A trial runs through its last day and reopens when the Heym team extends it, with one trial per installation. Heym itself keeps running throughout. Networks without internet access use an offline license from enterprise@heym.run.

## Videos

All Heym Work videos are in the [Heym Work playlist](https://www.youtube.com/playlist?list=PLBLCDjFQgoPQ).

## Related

- [Enterprise](./enterprise.md): commercial licensing and support
- [Single Sign-On](./sso.md): the sign-in Heym Work uses
- [Human-in-the-Loop](./human-in-the-loop.md): the reviews Heym Work shows
- [Audit Logging](./audit.md): the lines connection changes write
- [Settings](./user-settings.md): where the Heym Work tab lives
