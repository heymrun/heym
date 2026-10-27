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
    releaseId: "2026.23",
    publishedAt: new Date("2026-10-27T12:00:00Z"),
    headline: "Reach the Heym Agent from other agents over A2A",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
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
      sectionOrder: ["agent-suite", "chat-evals", "concurrency-limit", "canvas-collaboration"],
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
      {
        id: "chat-evals",
        title: "Create and run eval suites from Chat",
        publishedAt: new Date("2026-10-26T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Ask **Chat** for an eval suite in plain words, for example *\"make a prompt suite for my support prompt and compare gpt-4o with gpt-4.1-mini\"*. Chat writes the test cases with their expected answers. It asks which credential and models to use, or uses your only one. Then it saves the suite in **Evals**, runs it, and reports each model's pass count and the cases that failed.",
          },
          {
            type: "prose",
            markdown:
              "For an **agent suite**, Chat picks the agent and writes the run inputs itself. It can run the workflow and save those runs as the baseline, take the baseline from the agent's latest runs, or store the numbers you give it. The same works from an MCP client through `heym_chat`.",
          },
        ],
        tour: {
          description:
            "Describe the suite you want. Chat writes the test cases, picks the credential with you, and runs it.",
          useCases: [
            "Compare two models on a prompt without building the suite by hand",
            "Build an agent's baseline from fresh runs when it has none yet",
            "Re-run a suite from an MCP client and read what failed",
          ],
          tourVisual: "chat-evals",
          docTarget: {
            categoryId: "tabs",
            slug: "chat-tab",
            title: "Chat",
          },
        },
      },
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
      {
        id: "canvas-collaboration",
        title: "Work on a canvas together",
        publishedAt: new Date("2026-10-25T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Everyone who opens a workflow now shows as an avatar at the top left of the canvas. Edits reach every open canvas as they happen, and each person's pointer moves in their own color. Anyone with edit access can save the shared draft, and **Ctrl+Z** undoes only your own changes.",
          },
          {
            type: "prose",
            markdown:
              "Click an avatar to **follow** that person: your editor shows what they look at, where they point, the dialogs and AI Assistant they open and the runs they start, with your own access. Press **Esc** to stop. Turn on the **microphone** next to the avatars to talk with everyone on the canvas.",
          },
        ],
        tour: {
          description:
            "See who is on the canvas, edit together live, follow someone's view and talk with the microphone.",
          useCases: [
            "Build a workflow with a teammate without taking turns",
            "Walk someone through a run by letting them follow you",
            "Review a workflow together while talking it through",
          ],
          tourVisual: "canvas-collaboration",
          docTarget: {
            categoryId: "reference",
            slug: "canvas-collaboration",
            title: "Canvas Collaboration",
          },
        },
      },
    ],
  },
];
