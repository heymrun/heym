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
    releaseId: "2026.25",
    publishedAt: new Date("2026-11-05T12:00:00Z"),
    headline: "Assign, prioritize and schedule board cards from Heym, Heym Work, Chat and MCP",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription: "Kanban boards become team task boards, managed the same way everywhere.",
      tourEnabled: false,
      sectionOrder: ["board-task-fields"],
    },
    sections: [{
      id: "board-task-fields",
      title: "Assign, prioritize and schedule board cards",
      publishedAt: new Date("2026-11-05T12:00:00Z"),
      blocks: [{
        type: "prose",
        markdown: "Open a card on the **Board** tab to give it an assignee, a priority, a due date, labels such as a client or project, and links to the workflows or runs it is about. The card shows them at a glance, and overdue work turns red. The order you drag cards into is kept, in Heym and in Heym Work. A board can also stop moving cards on its own: turn off **Advance cards automatically** in its settings for a plain team task board. Chat and any MCP client through `heym_chat` can now create and change boards, columns and cards, assign and move tasks, and list what is overdue or waiting for a review. Moving a card never approves a review.",
      }],
      tour: {
        description: "Give cards an owner, a priority and a due date, and manage them from Heym, Heym Work, Chat or MCP.",
        useCases: ["See who works on which contract and what is overdue", "Ask Chat to move a task to Review and assign it to a colleague", "Keep a plain task board whose cards stay where people put them"],
        tourVisual: "board-task-fields",
        docTarget: { categoryId: "tabs", slug: "board-tab", title: "Board" },
      },
    }],
  },
  {
    releaseId: "2026.24",
    publishedAt: new Date("2026-10-30T12:00:00Z"),
    headline: "Open large files in a sandbox, plan schedules and map database relationships",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription: "File analysis in a sandbox, Gantt schedules and entity relationships, in Heym and Heym Work.",
      tourEnabled: true,
      sectionOrder: ["file-analysis", "planning-widgets"],
    },
    sections: [{
      id: "file-analysis",
      title: "Open large files in an isolated sandbox",
      publishedAt: new Date("2026-10-31T12:00:00Z"),
      blocks: [{
        type: "prose",
        markdown: "Attach a PDF, spreadsheet, DOCX, CSV or JSON file in Chat, or name one in Drive. The file is stored in Drive and Chat opens it in an isolated Python sandbox with no network: it inspects the pages, sheets and columns first, then reads only the part your question needs, so a large file never fills the conversation. Follow-up questions reuse what was already read. Workflows that start with a File Upload trigger get the same ability: an Agent node that receives the uploaded file opens it the same way, with nothing to switch on, and a Code node reads it through **Files** with pandas, openpyxl, pdfplumber and python-docx.",
      }],
      tour: {
        description: "Ask about a large PDF or spreadsheet without pasting it. Chat inspects it in a sandbox and reads only what it needs.",
        useCases: ["Total a column on one sheet and add a value from the last page", "Summarize the risks in a 200-page contract", "Build a workflow that extracts the same fields from every uploaded invoice"],
        tourVisual: "file-analysis",
        docTarget: { categoryId: "reference", slug: "file-analysis", title: "File Analysis" },
      },
    }, {
      id: "planning-widgets",
      title: "Gantt schedules and database relationship diagrams",
      publishedAt: new Date("2026-10-30T12:00:00Z"),
      blocks: [{
        type: "prose",
        markdown: "Add a **Gantt** widget for tasks with start and end dates, completion percentages and dependencies. Choose **Entity relationships (DB)** to show tables, their fields, primary and foreign keys, and the relationships between them. Both types are available in Add widget and the Chart Output node. Heym Work can propose either view and draw a preview using the page’s own plan before you build it.",
      }],
      tour: {
        description: "See project schedules and database relationships on your dashboards and Work pages.",
        useCases: ["Track a delivery plan with task progress and dependencies", "Document a database with primary and foreign keys", "Preview a proposed timeline or schema in Heym Work"],
        tourVisual: "planning-widgets",
        docTarget: { categoryId: "nodes", slug: "chart-output-node", title: "Chart Output" },
      },
    }],
  },
  {
    releaseId: "2026.23",
    publishedAt: new Date("2026-10-27T12:00:00Z"),
    headline: "Reach the Heym Agent from other agents over A2A",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["a2a-agent"],
    },
    sections: [
      {
        id: "a2a-agent",
        title: "The Heym Agent, over MCP and A2A",
        publishedAt: new Date("2026-10-27T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The **MCP** tab is now **MCP / A2A**, and the Heym Chat tool is the **Heym Agent**: the same engine as the Chat tab, which MCP clients call as `heym_chat`. Tick **Enable A2A** on the global server or on any named server, and other agents can send it tasks over the Agent2Agent protocol (A2A 1.0). The card shows the Agent Card URL and the JSON-RPC endpoint to copy.",
          },
          {
            type: "prose",
            markdown:
              "A task streams what the agent is doing, step by step, and ends with the reply and links to every workflow or eval suite it saved. A clarifying question pauses the task as **input required**; a credential the agent needs opens on Heym's own page and pauses it as **auth required**, so no secret passes through the other agent. Every task is a conversation in the Chat tab, and MCP clients now see the agent's real steps as progress too.",
          },
        ],
        tour: {
          description:
            "Tick Enable A2A and other agents can delegate work to the Heym Agent, with the same abilities as Chat.",
          useCases: [
            "Let a company assistant built on another platform build and run Heym workflows",
            "Hand an agent's research results to Heym to turn into a scheduled workflow",
            "Follow a long build from another agent with streamed progress",
          ],
          tourVisual: "a2a-agent",
          docTarget: {
            categoryId: "reference",
            slug: "a2a",
            title: "A2A",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.22",
    publishedAt: new Date("2026-10-26T12:00:00Z"),
    headline:
      "Work on one canvas together, limit how many runs execute at once, and check agents against their real runs, from Evals or from Chat",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["agent-suite"],
    },
    sections: [
      {
        id: "agent-suite",
        title: "Agent suites: check an agent against its real runs",
        publishedAt: new Date("2026-10-26T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "In **Evals**, choose **New Suite** and then **Agent suite**, and pick a workflow's agent node. The suite reads the agent's last runs from Traces and shows its latency, USD cost, tokens and tool calls, with every tool, MCP tool, sub-agent, sub-workflow and skill it called and how often.",
          },
          {
            type: "prose",
            markdown:
              "Mark each one **Must call** or **Must not call**, and keep the upper bounds for latency, cost, tokens and tool calls that start 20% above the baseline. **Results** runs the workflow as many times as you choose, with the last run's inputs or inputs an AI model writes, scores every run against the checks and links each failed run to its trace. The suite picker now lists prompt and agent suites together, with their type, and is searchable.",
          },
        ],
        tour: {
          description:
            "Pick an agent, see its baseline from real runs, and fail any run that calls the wrong tool or costs too much.",
          useCases: [
            "Make sure a support agent always searches the docs before answering",
            "Catch an agent that starts sending email it should only draft",
            "Notice when a prompt change makes runs slower or more expensive",
          ],
          tourVisual: "agent-suite",
          docTarget: {
            categoryId: "tabs",
            slug: "evals-tab",
            title: "Evals",
          },
        },
      },
    ],
  },
];
