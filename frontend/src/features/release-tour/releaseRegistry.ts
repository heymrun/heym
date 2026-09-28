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
    releaseId: "2026.16",
    publishedAt: new Date("2026-09-27T00:00:00Z"),
    headline: "The AI Assistant tests what it builds and sets up your data tables",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["assistant-yolo-mode", "assistant-data-tables"],
    },
    sections: [
      {
        id: "assistant-yolo-mode",
        title: "YOLO mode: the AI Assistant tests what it builds",
        publishedAt: new Date("2026-09-27T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Check **YOLO mode** in the canvas **AI Assistant** and it no longer stops after applying a workflow. It runs the workflow on the canvas like **Run**, reads the result, and fixes the workflow until the run does what you asked, for up to five runs per message. Each reply lists its steps as they happen. You see the changes being applied, each attempt with the node it is executing, and a final **Verified** with a short summary.",
          },
          {
            type: "prose",
            markdown:
              "Before the first run it asks for test inputs, filled with values it suggests, and reuses them until the input fields change. It can also run your other workflows when it needs their result. When it needs a decision or a credential, it asks with the usual question card. Runs are real, so YOLO mode is off by default and **Stop** ends the loop at any time. Every message in the assistant also has a copy icon now, and you can drag the line above the message box to make it taller.",
          },
        ],
        tour: {
          description:
            "The AI Assistant runs the workflow it builds, reads the result and fixes it until it works.",
          useCases: [
            "Describe a workflow and get one that has already run successfully",
            "Let the assistant chase down a failing node without pasting errors back",
            "Check what another workflow returns before wiring it into an Execute node",
          ],
          tourVisual: "assistant-yolo-mode",
          docTarget: {
            categoryId: "reference",
            slug: "ai-assistant",
            title: "AI Assistant",
          },
        },
      },
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
  {
    releaseId: "2026.15",
    publishedAt: new Date("2026-09-23T00:00:00Z"),
    headline:
      "Add a credential without leaving the conversation, give your evals an independent judge, and share your dashboards",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["chat-credentials", "evals-judge", "dashboard-sharing"],
    },
    sections: [
      {
        id: "chat-credentials",
        title: "Create the credential a workflow needs, right in chat",
        publishedAt: new Date("2026-09-23T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "When a workflow you ask for needs a credential, the assistant asks which one to use. If you have a fitting credential it is listed next to **Create a new credential**; if you have none, the assistant asks whether to create one. You can always continue without one. Creating opens the credential form in the conversation, preset to the right type and a suggested name. You can also ask for a credential on its own, or ask to update one you own, and the same form opens on it.",
          },
          {
            type: "prose",
            markdown:
              "The values go straight to Heym. The model only learns the name and type, says it added the credential, and carries on building. OAuth credentials such as Google Sheets connect in a popup, with a link to open the authorization page yourself if the popup is blocked.",
          },
          {
            type: "prose",
            markdown:
              "It works in the canvas **AI Assistant**, the **Chat** tab (including the workflows Chat creates and edits for you) and **Chat with Heym**. When no node covers an operation, such as adding a tab to a Google Sheet, the assistant sends the same credential in an **HTTP** request.",
          },
        ],
        tour: {
          description:
            "Pick, create or update a credential inside the conversation; the model sees only its name and type.",
          useCases: [
            "Ask for a GitHub workflow and add the missing token without leaving chat",
            "Connect or reconnect a Google Sheets account through OAuth from the assistant's question",
            "Reach operations a node lacks through HTTP with the same credential",
          ],
          tourVisual: "chat-credentials",
          docTarget: {
            categoryId: "reference",
            slug: "credentials",
            title: "Credentials",
          },
        },
      },
      {
        id: "evals-judge",
        title: "Give your evals an independent judge",
        publishedAt: new Date("2026-09-23T12:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "**LLM-as-Judge** in the **Evals** tab can now hand scoring to a separate judge. Pick an OpenAI, OpenAI compatible, Gemini or **Decision Model** credential and type the judge's model. Each model answers the test input on its own, then the judge rates how closely that answer matches the expected output from 0 to 100. A decision model such as `jev-latest` computes that score from a probability distribution instead of writing a number about the answer.",
          },
          {
            type: "prose",
            markdown:
              "Temperature and reasoning effort leave the panel in this mode, so it only shows what the run uses. Every run keeps its judge: the history list names it, opening a past run loads it back for **Re-Run Evals**, and **Export** includes it. Leave the judge empty and each model scores its own answer, as before.",
          },
        ],
        tour: {
          description:
            "Score eval answers with a separate model or a decision model instead of asking each model to grade its own work.",
          useCases: [
            "Compare models on one suite with a single independent judge",
            "See which judge scored a past run in the history list and the export",
            "Re-run a past evaluation with the same judge in one click",
          ],
          tourVisual: "evals-judge",
          docTarget: {
            categoryId: "tabs",
            slug: "evals-tab",
            title: "Evals",
          },
        },
      },
      {
        id: "dashboard-sharing",
        title: "Keep several dashboards and share them with your team",
        publishedAt: new Date("2026-09-24T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The **Dashboard** tab now holds as many dashboards as you need. Switch between them from the selector at the top of the tab, or create one with **+**. The tab reopens the dashboard you used last, and the address bar links to the exact dashboard on screen.",
          },
          {
            type: "prose",
            markdown:
              "Share a dashboard with people or teams from its **settings**. **Read** lets them view and refresh the charts. **Write** also lets them add, change and delete widgets and open a widget's workflow. Widgets always run with the owner's credentials, so teammates see the same data without needing access to the accounts behind it.",
          },
          {
            type: "prose",
            markdown:
              "**Add widget** now draws an example of the chart type you pick, with sample data, so you can see how a proportion or bar gauge chart will look before you build it.",
          },
        ],
        tour: {
          description:
            "Keep several dashboards, switch between them, and share each one read-only or editable.",
          useCases: [
            "Keep a separate dashboard per team, product or customer",
            "Give stakeholders a read-only view that runs with your credentials",
            "Preview how a chart type looks before adding the widget",
          ],
          tourVisual: "dashboard-sharing",
          docTarget: {
            categoryId: "tabs",
            slug: "dashboard-tab",
            title: "Dashboard",
          },
        },
      },
    ],
  },
];
