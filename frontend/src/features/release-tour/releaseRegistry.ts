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
    releaseId: "2026.12",
    publishedAt: new Date("2026-09-20T00:00:00Z"),
    headline: "Let a reasoning model keep its train of thought",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["responses-api"],
    },
    sections: [
      {
        id: "responses-api",
        title: "Route a model call through the Responses API",
        publishedAt: new Date("2026-09-20T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The **LLM** and **Agent** nodes have a new **Use Responses API** checkbox. It is off by default. When it is on, the node calls the Responses API instead of Chat Completions. Prompts, tools and JSON output behave exactly as before, so a node you already rely on keeps producing what it produced yesterday.",
          },
          {
            type: "prose",
            markdown:
              "It matters most on an Agent node running a reasoning model. The Responses API returns the model's reasoning alongside each tool call, and Heym feeds it back on the next turn, so the agent keeps its train of thought across a multi-step tool loop instead of starting over after every tool result. Nothing is stored on the provider's side: the conversation stays in Heym and the reasoning travels as an encrypted blob.",
          },
          {
            type: "prose",
            markdown:
              "It works with an OpenAI credential, and with a custom credential whose gateway supports the endpoint, so a self-hosted or proxied setup can use it too. Google credentials do not support it, and it cannot be combined with Batch mode. The node panel tells you where a given credential stands before you run anything, and a node set to use it either runs on it or stops with a message naming the reason.",
          },
        ],
        tour: {
          description:
            "Keep a reasoning model's chain of thought across tool calls by switching the node to the Responses API.",
          useCases: [
            "Keep a multi-step agent's reasoning intact from one tool call to the next",
            "Use it with an OpenAI credential or with your own compatible gateway",
            "Spend fewer tokens when a long tool loop reuses reasoning it already produced",
          ],
          tourVisual: "responses-api",
          docTarget: {
            categoryId: "nodes",
            slug: "agent-node",
            title: "Agent Node",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.11",
    publishedAt: new Date("2026-09-01T00:00:00Z"),
    headline: "Keep a vector store in step with its source",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["rag-upsert-delete"],
    },
    sections: [
      {
        id: "rag-upsert-delete",
        title: "Upsert and delete documents by your own ID",
        publishedAt: new Date("2026-09-01T10:00:00Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "The **RAG / Vector Store** node has two new operations: **Upsert** and **Delete**. Both address a document by a unique ID that lives inside the payload rather than by the store's internal point ID, so a document keeps the identifier your own system already uses - a CRM record ID, an SKU, a page slug. A **Document ID Field** names the field (default `doc_id`) and **Document ID** carries the value, and both accept expressions.",
          },
          {
            type: "prose",
            markdown:
              "Upsert removes every point stored under that ID before writing the new version, so a document that was split into chunks is replaced as a whole instead of duplicated. Delete reports `deleted: true` or `false`, so removing an ID that is not there is a plain result rather than a failed run. Both work identically on Qdrant and on Postgres (pgvector).",
          },
          {
            type: "prose",
            markdown:
              "**Document metadata now resolves expressions.** Writing `{ \"url\": \"$start.url\" }` on Insert or Upsert stores what the run actually produced, and a value that is one whole expression keeps its type, so a number stays a number and still matches a search filter.",
          },
        ],
        tour: {
          description:
            "Replace or remove a stored document by the ID your own system uses, without searching for it first.",
          useCases: [
            "Re-sync a knowledge base when the source record changes",
            "Drop a document from the store when it is deleted upstream",
            "Tag a document with the URL or record ID the run came from",
          ],
          tourVisual: "rag-upsert-delete",
          docTarget: {
            categoryId: "nodes",
            slug: "rag-node",
            title: "RAG / Vector Store",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.10",
    publishedAt: new Date("2026-08-27T00:00:00Z"),
    headline: "Share the load across more than one instance",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["cluster-load-distribution"],
    },
    sections: [
      {
        id: "cluster-load-distribution",
        title: "Split execution across instances",
        publishedAt: new Date("2026-08-29T10:12:49Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Point a second Heym instance at the same database and it joins as a worker. Background runs - cron, webhooks, MCP tool calls, chat triggers - are shared between the instances by a percentage you set under **Settings \u2192 Instances**. The instances never talk to each other: Postgres carries the work, so a worker needs no open port and no route back to the main instance.",
          },
          {
            type: "prose",
            markdown:
              "Work that touches local files, a coding-agent workspace or an installed plugin always runs on the main instance, and the settings panel shows how much of your last 24 hours that was - so you can tell when percentages cannot help. Every run in History now names the instance that executed it, and both history dialogs let you filter down to one.",
          },
        ],
        tour: {
          description:
            "Add worker instances against the same database and split background execution between them by percentage, with each instance's status, latency and version in one table.",
          useCases: [
            "Keep heavy agent and crawler runs off the machine serving the UI",
            "Take an instance out of rotation for maintenance without stopping work",
            "See which instance executed any run, and filter history down to one",
          ],
          tourVisual: "cluster-instances",
          docTarget: {
            categoryId: "reference",
            slug: "cluster",
            title: "Load Distribution",
          },
        },
      },
    ],
  },
  {
    releaseId: "2026.09",
    publishedAt: new Date("2026-08-26T00:00:00Z"),
    headline: "Sign in with your own identity provider",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["oidc-sso"],
    },
    sections: [
      {
        id: "oidc-sso",
        title: "Sign in with your identity provider",
        publishedAt: new Date("2026-08-26T19:53:29Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Heym can now authenticate people against any **OpenID Connect** provider. An instance administrator pastes an issuer URL under **Settings → SSO**, and Heym reads the authorization, token, and key endpoints from the provider's own discovery document. No provider is hardcoded, so Keycloak, Okta, Entra ID, Auth0 and Google all connect the same way.",
          },
          {
            type: "prose",
            markdown:
              "People who have never signed in get an account on first sign-in, optionally limited to your own email domains. Password sign-in stays available beside SSO, and can be switched off once a connection test has passed - accounts listed in `HEYM_ADMIN_EMAILS` keep password access so a misconfigured provider can never lock you out.",
          },
        ],
        tour: {
          description:
            "Configure single sign-on against any OIDC provider from the settings panel. Paste an issuer URL, copy the redirect URI into your provider, and test the connection before you turn it on.",
          useCases: [
            "Let your team sign in with the accounts they already have",
            "Restrict new accounts to your own email domains",
            "Turn off password sign-in once SSO is verified",
          ],
          tourVisual: "sso-login",
          docTarget: { categoryId: "reference", slug: "sso", title: "Single Sign-On" },
        },
      },
    ],
  },
  {
    releaseId: "2026.08",
    publishedAt: new Date("2026-08-18T00:00:00Z"),
    headline: "Playwright runs you can actually read",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: ["playwright-ai-steps"],
    },
    sections: [
      {
        id: "playwright-ai-steps",
        title: "Playwright AI steps you can actually read",
        publishedAt: new Date("2026-08-23T14:09:53Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "AI-written browser steps now report what they attempted and why they failed instead of surfacing a bare stack trace. Screenshots open in a lightbox you can page through, and the generated code carries fewer automation fingerprints.",
          },
        ],
        tour: {
          description:
            "Describe a browser step in plain language and Playwright writes it. When a step fails, the error names the step; every screenshot opens full size in a gallery.",
          useCases: [
            "Scrape a site that has no API, described in one sentence",
            "See exactly which step broke when a selector goes stale",
            "Page through run screenshots to confirm what the browser saw",
          ],
          tourVisual: "playwright-ai-steps",
          docTarget: { categoryId: "nodes", slug: "playwright-node", title: "Playwright Node" },
        },
      },
    ],
  },
  {
    releaseId: "2026.08-unreleased",
    publishedAt: new Date("2026-08-25T00:00:00Z"),
    headline: "Inspect an execution span without leaving its timeline",
    releaseTour: {
      label: "New in Heym",
      introTitle: "A closer look at every execution span",
      introDescription:
        "See the timing, retries, traces, errors, and outputs behind the selected step.",
      tourEnabled: true,
      sectionOrder: ["span-details-inspector"],
    },
    sections: [
      {
        id: "span-details-inspector",
        title: "Diagnose a run from the timeline",
        publishedAt: new Date("2026-08-27T05:23:28Z"),
        blocks: [
          {
            type: "prose",
            markdown:
              "Select a span in the execution timeline to inspect its status, timing, retries, trace, error, and output in one place.",
          },
        ],
        tour: {
          description:
            "Click a timeline span to open its details in place of the rows. Follow a trace or inspect the node output without losing your place in the run.",
          useCases: [
            "Find the slow or failed step in a long workflow run",
            "See the last error and retry attempts without reopening the node",
            "Connect a trace ID to the output that caused a failure",
          ],
          tourVisual: "span-details-inspector",
          docTarget: { categoryId: "reference", slug: "execution-history", title: "Execution History" },
        },
      },
    ],
  },
];
