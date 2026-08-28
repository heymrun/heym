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
 */
export const RELEASE_REGISTRY: ReleaseEntry[] = [
  {
    releaseId: "2026.10",
    publishedAt: new Date("2026-08-27T00:00:00Z"),
    headline: "Share the load across more than one instance",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: false,
      sectionOrder: ["cluster-load-distribution"],
    },
    sections: [
      {
        id: "cluster-load-distribution",
        title: "Split execution across instances",
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
    headline:
      "A rebuilt workflow list, Python on the canvas, branded folders, readable Playwright runs, and workflows that serve web pages",
    releaseTour: {
      label: "New in Heym",
      introTitle: "Five new things in this release",
      introDescription:
        "A quick look at what changed since your last update. Takes about a minute.",
      tourEnabled: true,
      sectionOrder: [
        "workflow-listing",
        "code-node",
        "folder-icons",
        "playwright-ai-steps",
        "html-output-mapper",
      ],
    },
    sections: [
      {
        id: "workflow-listing",
        title: "The workflow list, rebuilt around what you were about to do",
        blocks: [
          {
            type: "prose",
            markdown:
              "The Workflows tab is now a two-pane list. Rows carry a status chip - **Running**, **Scheduled**, **Listening**, **Paused**, **Manual** - and selecting one fills a preview beside it with the trigger, the last run, and every step in execution order. **Run Now** hands the workflow to the Quick Drawer so you can run it without opening the editor.",
          },
        ],
        tour: {
          description:
            "Click a row to preview it, double-click to open the editor. Filter the whole list by status, copy a ready cURL for webhook workflows, or jump straight to a step's properties.",
          useCases: [
            "See which workflows are running or paused without opening any of them",
            "Run a workflow from the list, inputs and all, and stay where you are",
            "Copy a working cURL for a webhook workflow instead of assembling one",
          ],
          tourVisual: "workflow-listing",
          docTarget: { categoryId: "tabs", slug: "workflows-tab", title: "Workflows Tab" },
        },
      },
      {
        id: "code-node",
        title: "Run Python right on the canvas",
        blocks: [
          {
            type: "prose",
            markdown:
              "The new **Code** node runs Python in a sandbox, so glue logic no longer needs a Function node workaround or an external service. Input arrives as `items`, whatever you return becomes the node output, and the editor formats your code on demand.",
          },
        ],
        tour: {
          description:
            "Drop a Code node between any two steps and reshape data in Python. It runs sandboxed, with no network and no filesystem access.",
          useCases: [
            "Reshape an API response before it reaches an Agent",
            "Filter or aggregate rows without chaining five Set nodes",
            "Compute a value that expressions cannot express cleanly",
          ],
          tourVisual: "code-node",
          docTarget: { categoryId: "nodes", slug: "code-node", title: "Code Node" },
        },
      },
      {
        id: "folder-icons",
        title: "Give every folder its own icon",
        blocks: [
          {
            type: "prose",
            markdown:
              "Workflow folders now carry a custom icon picked from a curated set of about 50. Right-click a folder, choose **Change icon**, and the sidebar stops being a wall of identical glyphs.",
          },
        ],
        tour: {
          description:
            "Pick an icon per folder from the picker dialog. Search by name, or clear it to fall back to the default folder glyph.",
          useCases: [
            "Tell client folders apart at a glance in a long sidebar",
            "Mark what a folder is for: billing, alerts, scraping, internal",
            "Flag the folder your team touches every day",
          ],
          tourVisual: "folder-icons",
          docTarget: { categoryId: "tabs", slug: "workflows-tab", title: "Workflows Tab" },
        },
      },
      {
        id: "playwright-ai-steps",
        title: "Playwright AI steps you can actually read",
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
      {
        id: "html-output-mapper",
        title: "Workflows that answer with a web page",
        blocks: [
          {
            type: "prose",
            markdown:
              "The new **HTML output mapper** node renders a page from a template, and when it is a workflow's only terminal node the execute webhook responds with `text/html` instead of JSON. The cURL dialog gained a **request method** selector, so a workflow can answer a plain browser `GET`, and the workflow list marks these with a **WEB** chip.",
          },
        ],
        tour: {
          description:
            "Drop an HTML output mapper at the end of a workflow, set the request method to GET, and the workflow's URL opens in a browser as a real page.",
          useCases: [
            "Serve a generated status page without standing up a web server",
            "Return a confirmation screen a person can actually read",
            "Publish a report an Agent writes, straight to a URL",
          ],
          tourVisual: "html-output-mapper",
          docTarget: {
            categoryId: "nodes",
            slug: "html-output-mapper-node",
            title: "HTML output mapper",
          },
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
