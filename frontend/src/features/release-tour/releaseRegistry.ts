import type { ReleaseEntry } from "@/features/release-tour/releaseTour.types";

/**
 * Source of truth for release notes and the tour that announces them.
 *
 * Adding a feature: append a section, list its id in `sectionOrder`, give it
 * `tour` metadata with a unique `tourVisual` key, and register a matching
 * visual component in `tourVisuals.ts`. Keep `tourEnabled: false` while the
 * release is still in progress, then flip it on in the release commit.
 *
 * No revision to bump: the stored id is derived from the slide ids, so changing
 * `sectionOrder` re-marks the release unseen and the tour reopens on its own.
 *
 * The registry keeps only the five most recently published sections. When a sixth
 * arrives, drop the oldest one along with its visual component and its registration
 * in `tourVisuals.ts`, and trim any release entry left without sections.
 */
export const RELEASE_REGISTRY: ReleaseEntry[] = [
  {
    releaseId: "2026.22",
    publishedAt: new Date("2026-10-26T12:00:00Z"),
    headline: "Limit how many runs of a workflow execute at once",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["concurrency-limit"],
    },
    sections: [
      {
        id: "concurrency-limit",
        title: "Run a workflow one at a time, or N at a time",
        publishedAt: new Date("2026-10-26T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Turn on **Concurrency limit** in the workflow's **Properties** panel and enter how many production runs may execute at once. Webhook, cron, MCP, Portal and trigger runs above the limit wait in a first-in, first-out queue. Editor test runs always start right away.",
          },
          {
            type: "prose",
            markdown:
              "A webhook call that has to wait gets **202 Accepted** at once, with an `execution_id`, a status URL and its place in the queue. Poll the status URL with the same credentials until the result arrives. MCP clients get the same answer and poll with **heym_execution_status**. Optional **Max queue size** and **Max wait** fields bound the queue.",
          },
        ],
        tour: {
          description:
            "Cap concurrent runs per workflow. Extra runs wait in order, and callers get an execution id to collect the result.",
          useCases: [
            "Process webhooks one at a time so two runs never update the same record",
            "Keep a rate-limited API from seeing more than two calls at once",
            "Let an MCP client queue work and pick up the result later",
          ],
          tourVisual: "concurrency-limit",
          docTarget: {
            categoryId: "reference",
            slug: "webhooks",
            title: "Webhooks",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.21",
    publishedAt: new Date("2026-10-22T12:00:00Z"),
    headline: "Change one node with AI, and sign in to Codex with a short code",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["node-ai-edit", "codex-device-sign-in"],
    },
    sections: [
      {
        id: "node-ai-edit",
        title: "Change or fix one node with AI",
        publishedAt: new Date("2026-10-22T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Hover a node on the canvas and click **AI** above it. The AI Assistant opens on that node and offers **Change this node as ...**, **Fix error in this node ...** and **Other**. The assistant changes only that node: the other nodes, the connections and the layout stay as they are.",
          },
          {
            type: "prose",
            markdown:
              "The panel shows which node it is changing. Once the node has run, it reads **Modifying Node: (Has Node Output)** and shows the last status and error, and the assistant uses that output, so a fix starts from what went wrong. Close the node focus to edit the whole workflow again.",
          },
        ],
        tour: {
          description:
            "Click AI above a node to change or fix that node only. The rest of the workflow stays as it is.",
          useCases: [
            "Fix the node that failed in the last run without touching the others",
            "Change what a condition or an HTTP request checks in one sentence",
            "Ask about one node in Ask mode",
          ],
          tourVisual: "node-ai-edit",
          docTarget: {
            categoryId: "reference",
            slug: "ai-assistant",
            title: "AI Assistant",
          },
        },
      },
      {
        id: "codex-device-sign-in",
        title: "Sign in to ChatGPT for Codex with a short code",
        publishedAt: new Date("2026-10-18T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The **OpenAI Codex** credential now signs in to ChatGPT with a short code. Click **Sign in with ChatGPT**, enter the code Heym shows (it is already copied) on OpenAI's page, and approve. Heym finishes on its own and closes the OpenAI window. There is no `localhost:1455` address to copy back anymore.",
          },
          {
            type: "prose",
            markdown:
              "Device code sign-in has to be allowed in ChatGPT under **Settings → Security**, and a workspace admin has to allow it for workspace accounts. Where it is off, **paste a redirect URL instead** keeps the previous flow.",
          },
        ],
        tour: {
          description:
            "Connect a ChatGPT subscription to the Codex node with a short code. Nothing to paste back.",
          useCases: [
            "Run Codex on a ChatGPT Plus or Pro plan instead of API credits",
            "Reconnect a Codex credential without leaving the dialog",
            "Sign in from a phone or another computer by entering the code there",
          ],
          tourVisual: "codex-device-sign-in",
          docTarget: {
            categoryId: "nodes",
            slug: "codex-node",
            title: "Codex",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.20",
    publishedAt: new Date("2026-10-17T12:00:00Z"),
    headline: "Slack approvals, buttons and forms that pause a run",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["slack-bot", "google-triggers"],
    },
    sections: [
      {
        id: "slack-bot",
        title: "Slack with a bot token: approvals, buttons, forms and threads",
        publishedAt: new Date("2026-10-17T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "A new **Slack Bot (Token)** credential turns the **Slack** node into a full Slack step: channel messages and DMs, thread replies, message updates, colored outcome cards, reactions, reading messages and looking people up. Each post returns its `channel`, `ts` and `threadTs`, so later steps stay in one thread.",
          },
          {
            type: "prose",
            markdown:
              "**Request approval**, **Send message with buttons** and **Send form** pause the run until someone answers in Slack. The same request waits in the inbox, so it can be decided in Heym too, and the step continues with `approval`, `choice` or the form's `values`. **Copy app manifest** in the credential dialog sets up the Slack app with every scope.",
          },
          {
            type: "prose",
            markdown:
              "One Slack app now serves every **Slack Trigger** on its credential: point Event Subscriptions at the credential's events URL, and each workflow starts only on what it listens to, such as direct messages to the bot, mentions, or one channel.",
          },
        ],
        tour: {
          description:
            "Post to Slack with a bot token, and let a click on Approve or a submitted form continue the run.",
          useCases: [
            "Ask a finance channel to approve a refund before it is paid",
            "Collect incident details through a Slack form, then file them",
            "Close the loop with an outcome card in the same thread",
          ],
          tourVisual: "slack-bot",
          docTarget: {
            categoryId: "nodes",
            slug: "slack-node",
            title: "Slack",
          },
        },
      },
      {
        id: "google-triggers",
        title: "Start a run when a Drive file or a sheet row changes",
        publishedAt: new Date("2026-10-17T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Two new trigger nodes. **Google Drive Trigger** starts a run when a file is created, updated, or deleted in a folder you choose. **Google Sheets Trigger** starts a run when a row is added, updated, or deleted, and tells the run which columns changed.",
          },
          {
            type: "prose",
            markdown:
              "Each change starts exactly one run, even on a multi-instance install. Heym keeps file metadata and keyed fingerprints of cells, never cell values. Set a key column such as `Email` so inserted or sorted rows are matched correctly.",
          },
        ],
        tour: {
          description:
            "Start a run when a file lands in a Drive folder or a row changes in a sheet, once per change.",
          useCases: [
            "Summarize every contract dropped into a shared folder",
            "Score each new lead as soon as its row appears",
            "Notify an owner when a status column changes",
          ],
          tourVisual: "google-triggers",
          docTarget: {
            categoryId: "nodes",
            slug: "google-sheets-trigger-node",
            title: "Google Sheets Trigger",
          },
        },
      },
    ],
  },
];
