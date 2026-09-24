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
  {
    releaseId: "2026.14",
    publishedAt: new Date("2026-09-22T00:00:00Z"),
    headline: "Let a model pick the model",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["model-router"],
    },
    sections: [
      {
        id: "model-router",
        title: "One credential, the right model every time",
        publishedAt: new Date("2026-09-22T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The new **Model Router** credential does not hold a key. It holds a decision model, a list of your existing OpenAI, Google and Custom credentials, and a sentence for each one saying when it should be used. Pick the router in any model dropdown, choose **Auto**, and the decision model reads each request and sends it to the model you described.",
          },
          {
            type: "prose",
            markdown:
              "It works everywhere a model is chosen: the **LLM** and **Agent** nodes, **Chat**, **AI Defaults**, **Dashboards** and the expression builder. An agent re-routes as its tool loop progresses, so a cheap model can take the early turns and a stronger one can take the turn that actually needs it.",
          },
          {
            type: "prose",
            markdown:
              "Nothing is hidden. **Traces** shows `Auto Model / GPT-5` rather than just the model, costs are still attributed to the model that ran, and the canvas **Execution Log** and **Span View** show which turn went where. Mark one option as the fallback and a decision model outage never stops a run.",
          },
        ],
        tour: {
          description:
            "A credential that picks the model per request, with both the router and the model it chose visible in every trace.",
          useCases: [
            "Send short questions to a cheap model and hard ones to a strong one, automatically",
            "Let an agent start cheap and escalate only on the turn that needs it",
            "See Auto Model / GPT-5 in Traces, the Execution Log and the Span View",
          ],
          tourVisual: "model-router",
          docTarget: {
            categoryId: "reference",
            slug: "credentials",
            title: "Credentials",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.13",
    publishedAt: new Date("2026-09-21T00:00:00Z"),
    headline: "Ask a model for a decision, not an essay",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["decision-node"],
    },
    sections: [
      {
        id: "decision-node",
        title: "Get a typed answer instead of a paragraph",
        publishedAt: new Date("2026-09-21T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The new **Decision** node asks a decision model typed questions about whatever the run has produced so far. You give it a **state**, such as a ticket, a diff or a form submission, plus a list of questions, and it answers each one with a probability instead of a paragraph you then have to parse.",
          },
          {
            type: "prose",
            markdown:
              "Questions come in three shapes. **Noul** asks whether a condition holds and returns how likely a yes is. **Choice** picks one option from a set you define and shows the full distribution. **Score** rates the state along levels you write, and can land between them. Choice and score answers carry their own confidence, so a **Switch** can branch on the answer while a **Condition** gates on how certain the model was.",
          },
          {
            type: "prose",
            markdown:
              "Write the questions yourself, or describe what you want judged and let **Generate with AI** draft them. If your endpoint speaks a different contract, turn on **Custom request body** and send the JSON you need. Connect it with a **Decision Model** credential pointing at a hosted or self-hosted endpoint, and every call shows up in Traces.",
          },
        ],
        tour: {
          description:
            "Ask a model typed questions about the run's state and branch on the answer instead of parsing prose.",
          useCases: [
            "Route a ticket to the right team and branch on how confident the call was",
            "Score how risky a change looks before a step that cannot be undone",
            "Draft the questions from a plain sentence with Generate with AI",
          ],
          tourVisual: "decision-node",
          docTarget: {
            categoryId: "nodes",
            slug: "decision-node",
            title: "Decision",
          },
        },
      },
    ],
  },
];
