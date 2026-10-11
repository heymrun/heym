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
  {
    releaseId: "2026.18",
    publishedAt: new Date("2026-10-03T12:00:00Z"),
    headline: "Switch a node back on from inside a workflow",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["enable-node"],
    },
    sections: [
      {
        id: "enable-node",
        title: "Enable Node: switch a node back on from inside a workflow",
        publishedAt: new Date("2026-10-03T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The new **Enable Node** is the counterpart of **Disable Node**. Pick a node by label and it turns that node back on and saves the change, so a **Cron** trigger you switched off fires again at its next scheduled time. If the node sits downstream and has not run yet, it also runs in the current execution.",
          },
          {
            type: "prose",
            markdown:
              "A switched-off trigger never starts a run by itself, so put the Enable Node behind another entry point, such as an **Input** trigger. The **Wait** node also takes longer pauses now: up to 15 minutes instead of one.",
          },
        ],
        tour: {
          description:
            "Turn a disabled node back on from inside a workflow, for example a Cron trigger that was switched off.",
          useCases: [
            "Start a disabled Cron trigger on demand from a webhook",
            "Pair it with Disable Node to switch a node off and on as conditions change",
            "Pause a workflow for up to 15 minutes with the Wait node",
          ],
          tourVisual: "enable-node",
          docTarget: {
            categoryId: "nodes",
            slug: "enable-node",
            title: "Enable Node",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.17",
    publishedAt: new Date("2026-09-28T18:00:00Z"),
    headline: "Review pending human approvals from the dashboard",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["dashboard-hitl"],
    },
    sections: [
      {
        id: "dashboard-hitl",
        title: "Clear pending reviews from a dashboard widget",
        publishedAt: new Date("2026-09-28T18:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Add a **HITL** widget and the header shows how many reviews are waiting, as `1/n pending`. Move left and right through each one; the arrows stop at the ends. The workflow name opens that run on the canvas. **Approve**, **Request changes**, and **Reject** resolve the draft. The history icon beside the widget title opens that run in the history dialog on the same page. The queue is yours: a shared dashboard does not reveal someone else's drafts.",
          },
        ],
        tour: {
          description:
            "A dashboard carousel of your pending human reviews, with the count in the header.",
          useCases: [
            "See how many reviews are waiting before you open the first one",
            "Approve, request changes, or reject a draft without leaving the dashboard",
            "Open that run in the history dialog from the icon beside the widget title",
          ],
          tourVisual: "dashboard-hitl",
          docTarget: {
            categoryId: "tabs",
            slug: "dashboard-tab",
            title: "Dashboard",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.16",
    publishedAt: new Date("2026-09-27T00:00:00Z"),
    headline: "The AI Assistant sets up your data tables",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["assistant-data-tables"],
    },
    sections: [
      {
        id: "assistant-data-tables",
        title: "The AI Assistant picks or creates your data tables",
        publishedAt: new Date("2026-09-28T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "When a workflow stores records, the **AI Assistant** now knows your **DataTables**. Name one and it uses it. Otherwise it asks which table to use: the question card lists the tables that fit, each with its description and column types, plus **Create a new table** with the columns the workflow needs. Press **Submit answers** and the card creates the table, then the assistant wires it into the **DataTable** node with its exact column names.",
          },
          {
            type: "prose",
            markdown:
              "It works in the canvas assistant, YOLO mode included, in **Chat**, in **Chat with Heym** on the docs, and over MCP through `heym_chat`. The assistant sees table names and columns, never rows, and never changes an existing table's columns: that stays in the **DataTable** tab.",
          },
        ],
        tour: {
          description:
            "The AI Assistant asks which data table a workflow should use, or creates one with the right columns.",
          useCases: [
            "Ask to save every lead in a table and get the table and the workflow together",
            "Pick one of your tables from a card that shows its columns and types",
            "Create and wire tables from Chat or an MCP client, not just the canvas",
          ],
          tourVisual: "assistant-data-tables",
          docTarget: {
            categoryId: "reference",
            slug: "ai-assistant",
            title: "AI Assistant",
          },
        },
      },
    ],
  },
];
