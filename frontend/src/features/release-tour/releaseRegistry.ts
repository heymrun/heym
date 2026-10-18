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
    releaseId: "2026.21",
    publishedAt: new Date("2026-10-18T12:00:00Z"),
    headline: "Sign in to ChatGPT for Codex with a short code",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["codex-device-sign-in"],
    },
    sections: [
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
  {
    releaseId: "2026.19",
    publishedAt: new Date("2026-10-10T18:00:00Z"),
    headline: "Heym Work for business teams, and skill zips in Chat",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["heym-work", "skill-zip"],
    },
    sections: [
      {
        id: "heym-work",
        title: "Heym Work, the business layer on top of Heym",
        publishedAt: new Date("2026-10-11T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "**Heym Work** is a second interface for business teams. People describe a job in their own words, answer a few questions, and get a workflow that Heym has built and tested. They work from pages built for them, answer reviews, and see every run with a name on it, while Heym runs each job in the background.",
          },
          {
            type: "prose",
            markdown:
              "Heym admins connect it in **Settings, Heym Work**: enter Heym Work's address, generate a key, and enable the connection. People sign in with the single sign-on Heym already uses. Heym Work is licensed separately; see heym.run/enterprise.",
          },
        ],
        tour: {
          description:
            "Business teams describe a job, answer a few questions and get a tested workflow, with Heym running it.",
          useCases: [
            "Give a legal, finance or operations team its own place to automate work",
            "Connect it from Settings, Heym Work with an address and a key",
            "Keep single sign-on, roles and approvals for every team",
          ],
          tourVisual: "heym-work",
          docTarget: {
            categoryId: "reference",
            slug: "heym-work",
            title: "Heym Work",
          },
          externalLink: {
            url: "/enterprise",
            title: "Learn more on heym.run",
          },
        },
      },
      {
        id: "skill-zip",
        title: "Drop a skill zip in Chat",
        publishedAt: new Date("2026-10-10T18:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Chat accepts a **zip**. When the archive contains a **SKILL.md**, and any Python files beside it, Chat can put that skill on an agent. A zip without a skill file stays in the conversation as context.",
          },
          {
            type: "prose",
            markdown:
              "Ask Chat to change a skill it already saved. It updates the named files and leaves the rest, including Python it did not rewrite, where it is. With a workflow selected, the skill lands there. Otherwise Chat starts a workflow with one agent that carries the skill.",
          },
        ],
        tour: {
          description: "Attach a skill zip in Chat and Heym puts it on an agent.",
          useCases: [
            "Drop a skill folder zipped with SKILL.md and a Python file",
            "Ask Chat to rewrite the skill text without losing the Python",
            "Start a new workflow whose agent carries the skill",
          ],
          tourVisual: "skill-zip",
        },
      },
    ],
  },
];
