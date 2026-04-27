import type { ShowcaseAction, ShowcaseContext, ShowcaseDefinition, ShowcaseDocTarget } from "@/features/showcase/showcase.types";

function docsTarget(categoryId: string, slug: string, title?: string): ShowcaseDocTarget {
  return { categoryId, slug, title };
}

function docsAction(id: string, label: string, description: string, target: ShowcaseDocTarget): ShowcaseAction {
  return {
    id,
    label,
    description,
    kind: "docs",
    docTarget: target,
  };
}

function routeAction(id: string, label: string, description: string, to: string): ShowcaseAction {
  return {
    id,
    label,
    description,
    kind: "route",
    to,
  };
}

export const SHOWCASE_DEFINITIONS: Record<ShowcaseContext, ShowcaseDefinition> = {
  "dashboard:workflows": {
    id: "dashboard:workflows",
    title: "Workflows",
    summary: "Create, organize, import, and revisit the workflows that power your AI automations.",
    bullets: [
      "Open workflows fast, keep folders tidy, and jump back into recent work.",
      "Use the command palette when you want speed without browsing the grid.",
      "Treat this tab as your operating base for everything that happens in the editor.",
    ],
    highlights: [
      { eyebrow: "Core surface", title: "Workflow library", description: "Browse root items, folders, and scheduled deletions in one place.", tone: "primary" },
      { eyebrow: "Fast path", title: "Quick creation", description: "Create new workflows or import JSON when you already know what you want.", tone: "blue" },
      { eyebrow: "Daily flow", title: "Organize before scale", description: "Folders and pinning keep growing automation sets manageable.", tone: "green" },
    ],
    actions: [
      docsAction("workflow-docs", "Read workflow guide", "Open the full workflows tab reference.", docsTarget("tabs", "workflows-tab", "Workflows Tab")),
      routeAction("open-templates", "Open templates", "Jump to the templates tab for reusable starting points.", "/?tab=templates"),
    ],
    details: [
      { id: "workflows-structure", title: "What belongs here", content: "Use this surface for workflow lifecycle tasks: create, rename, move, import, archive, and choose what to open next." },
      { id: "workflows-speed", title: "When to stay lightweight", content: "If you only need a quick run from another page, use Quick Drawer. Come back here when you need structure and management." },
    ],
    docsTarget: docsTarget("tabs", "workflows-tab", "Workflows Tab"),
  },
  "dashboard:templates": {
    id: "dashboard:templates",
    title: "Templates",
    summary: "Start from reusable workflow blueprints instead of rebuilding the same patterns from scratch.",
    bullets: [
      "Use templates when the workflow shape is known but the details still vary.",
      "Good templates shorten onboarding and reduce repeated canvas work.",
      "Share patterns here, then fine-tune them in the editor.",
    ],
    highlights: [
      { eyebrow: "Reuse", title: "Blueprint mindset", description: "Capture proven workflow structures and apply them again quickly.", tone: "primary" },
      { eyebrow: "Team speed", title: "Consistent starting points", description: "Templates help teams converge on the same good patterns.", tone: "blue" },
      { eyebrow: "Lower friction", title: "Less blank-canvas time", description: "Choose a ready-made frame, then customize only what matters.", tone: "amber" },
    ],
    actions: [
      docsAction("templates-docs", "Open template docs", "Read how templates fit into the dashboard flow.", docsTarget("tabs", "templates-tab", "Templates Tab")),
      routeAction("open-workflows", "Back to workflows", "Return to the main workflow library.", "/"),
    ],
    details: [
      { id: "templates-why", title: "Why templates matter", content: "They turn repeated node layouts into reusable assets, which is especially helpful when your team ships variations of the same workflow pattern." },
      { id: "templates-when", title: "Best time to use them", content: "Reach for templates when the structure is stable but names, prompts, credentials, or destinations change from use case to use case." },
    ],
    docsTarget: docsTarget("tabs", "templates-tab", "Templates Tab"),
  },
  "dashboard:globalvariables": {
    id: "dashboard:globalvariables",
    title: "Variables",
    summary: "Store shared values once and reference them across workflows without repeating the same data everywhere.",
    bullets: [
      "Keep frequently reused values in one durable place.",
      "Use variables to reduce prompt drift and duplicated configuration.",
      "Share values intentionally when multiple workflows depend on the same source of truth.",
    ],
    highlights: [
      { eyebrow: "Persistence", title: "Cross-run memory", description: "Global values survive past a single workflow execution.", tone: "green" },
      { eyebrow: "Cleaner configs", title: "Less duplication", description: "Update once instead of editing many node fields.", tone: "primary" },
      { eyebrow: "Expressions", title: "Works in DSL", description: "Reference values directly in node expressions and prompts.", tone: "blue" },
    ],
    actions: [
      docsAction("variables-docs", "Read variables docs", "Open the variables dashboard guide.", docsTarget("tabs", "global-variables-tab", "Variables Tab")),
    ],
    details: [
      { id: "variables-pattern", title: "Common pattern", content: "Store endpoints, shared prompt fragments, environment-specific settings, or IDs that multiple workflows need to read." },
      { id: "variables-boundary", title: "What not to store", content: "Keep secrets and provider auth in credentials, not in global variables." },
    ],
    docsTarget: docsTarget("tabs", "global-variables-tab", "Variables Tab"),
  },
  "dashboard:chat": {
    id: "dashboard:chat",
    title: "Chat",
    summary: "Use the dashboard chat surface as a quick conversational entry point into your workflows and platform tasks.",
    bullets: [
      "Great for fast questions, workflow help, and lightweight execution flows.",
      "This surface favors speed and iteration over full editor control.",
      "When the shape is clear, move into a workflow or docs for depth.",
    ],
    highlights: [
      { eyebrow: "Natural language", title: "Fast interaction", description: "Use plain language instead of navigating the whole app first.", tone: "primary" },
      { eyebrow: "Bridge surface", title: "From idea to action", description: "Chat is useful when you know the goal but not the exact path yet.", tone: "blue" },
      { eyebrow: "Companion", title: "Pairs well with docs", description: "Use it alongside documentation when you want both answers and reference.", tone: "amber" },
    ],
    actions: [
      docsAction("chat-docs", "Open chat docs", "Read the dashboard chat guide.", docsTarget("tabs", "chat-tab", "Chat Tab")),
      docsAction("assistant-docs", "AI assistant reference", "See how Heym's assistant fits into workflow creation.", docsTarget("reference", "ai-assistant", "AI Assistant")),
    ],
    details: [
      { id: "chat-intent", title: "Best use cases", content: "Use chat for quick workflow questions, short platform guidance, and fast operational steps that do not need deep canvas work." },
      { id: "chat-next-step", title: "When to switch surfaces", content: "Move into the editor once you need node-level control, or into docs when you want a durable reference." },
    ],
    docsTarget: docsTarget("tabs", "chat-tab", "Chat Tab"),
  },
  "dashboard:drive": {
    id: "dashboard:drive",
    title: "Drive",
    summary: "View, manage, and share files generated by your workflow skills.",
    bullets: [
      "Skills write files to a special output directory and Heym captures them automatically.",
      "Share files via token links or password-protected Basic Auth URLs.",
      "Download files with one click (preview is not available).",
    ],
    highlights: [
      { eyebrow: "Storage", title: "Auto-captured files", description: "Skills write to _OUTPUT_DIR and files appear here after execution.", tone: "primary" },
      { eyebrow: "Sharing", title: "Flexible access control", description: "Public links, password protection, expiry, and download limits.", tone: "blue" },
      { eyebrow: "Formats", title: "PDF, DOCX, CSV & more", description: "Generate any file type with reportlab, python-docx, or plain Python.", tone: "green" },
    ],
    actions: [
      docsAction("drive-docs", "Open Drive docs", "Read the full Drive tab reference.", docsTarget("tabs", "drive-tab", "Drive Tab")),
      docsAction("file-gen-docs", "File generation guide", "Learn how skills generate files.", docsTarget("reference", "file-generation", "File Generation")),
    ],
    details: [
      { id: "drive-how", title: "How files get here", content: "When a skill writes files to the _OUTPUT_DIR directory, Heym stores them on disk and creates download tokens. The files then appear in this tab." },
      { id: "drive-share", title: "Sharing options", content: "Create public token links for anyone, or password-protected Basic Auth URLs. Set expiration and download limits per link." },
    ],
    docsTarget: docsTarget("tabs", "drive-tab", "Drive Tab"),
  },
  "dashboard:credentials": {
    id: "dashboard:credentials",
    title: "Credentials",
    summary: "Manage the keys, tokens, and connection details that let workflows talk to outside systems safely.",
    bullets: [
      "Keep secrets centralized instead of scattering them through nodes.",
      "Credentials power LLMs, integrations, vector stores, and more.",
      "Share access when teams need the same connection without copying secrets.",
    ],
    highlights: [
      { eyebrow: "Security", title: "Centralized secrets", description: "Store auth once and reuse it across workflows.", tone: "green" },
      { eyebrow: "Integrations", title: "Broad coverage", description: "Credentials unlock providers such as OpenAI, Slack, Redis, and Grist.", tone: "primary" },
      { eyebrow: "Collaboration", title: "Share intentionally", description: "Use team or user sharing instead of duplicate records.", tone: "blue" },
    ],
    actions: [
      docsAction("credentials-docs", "Read credential docs", "Open the credentials dashboard guide.", docsTarget("tabs", "credentials-tab", "Credentials Tab")),
      docsAction("integrations-docs", "See integrations", "Browse integration setup details.", docsTarget("reference", "integrations", "Third-Party Integrations")),
    ],
    details: [
      { id: "credentials-use", title: "Where they show up", content: "Credentials are referenced from node configuration, then resolved securely during execution." },
      { id: "credentials-sharing", title: "Team-friendly model", content: "Prefer sharing when multiple builders need the same provider access; it keeps runtime behavior consistent and easier to audit." },
    ],
    docsTarget: docsTarget("tabs", "credentials-tab", "Credentials Tab"),
  },
  "dashboard:vectorstores": {
    id: "dashboard:vectorstores",
    title: "Vectorstores",
    summary: "Prepare and manage retrieval backends for workflows that need memory, document search, or RAG-style context injection.",
    bullets: [
      "Vectorstores are the storage side of retrieval-aware workflows.",
      "Use them with RAG nodes and AI flows that need document grounding.",
      "Think of this tab as infrastructure for smarter prompting.",
    ],
    highlights: [
      { eyebrow: "RAG infra", title: "Searchable memory", description: "Keep documents ready for semantic retrieval when workflows need context.", tone: "primary" },
      { eyebrow: "Quality", title: "Better grounding", description: "Retrieval reduces hallucination risk by providing supporting material.", tone: "green" },
      { eyebrow: "Operations", title: "Manage once", description: "Create and reuse vector stores across multiple workflows.", tone: "blue" },
    ],
    actions: [
      docsAction("vectors-docs", "Open vectorstore docs", "Read the vectorstores dashboard guide.", docsTarget("tabs", "vectorstores-tab", "Vectorstores Tab")),
      docsAction("rag-docs", "See RAG node docs", "Open the Qdrant RAG node reference.", docsTarget("nodes", "rag-node", "Qdrant RAG")),
    ],
    details: [
      { id: "vectors-role", title: "Where this fits", content: "This tab prepares the storage layer. The actual retrieval logic lives inside workflows, usually through RAG or agent patterns." },
      { id: "vectors-choice", title: "When to use it", content: "Choose vectorstores when your workflow needs to search unstructured knowledge instead of relying only on the model's built-in memory." },
    ],
    docsTarget: docsTarget("tabs", "vectorstores-tab", "Vectorstores Tab"),
  },
  "dashboard:mcp": {
    id: "dashboard:mcp",
    title: "MCP",
    summary: "Manage Model Context Protocol connections so agent workflows can safely reach tools and external capabilities.",
    bullets: [
      "MCP turns external tool ecosystems into usable agent context.",
      "Use this tab when agents need richer capabilities than static prompts.",
      "Connection quality here directly affects the tool layer inside your agents.",
    ],
    highlights: [
      { eyebrow: "Agent tools", title: "External capability layer", description: "Expose tool servers that agents can call during reasoning.", tone: "primary" },
      { eyebrow: "Runtime control", title: "Connection setup", description: "Configure endpoints, labels, and transport so workflows can rely on them.", tone: "blue" },
      { eyebrow: "Platform depth", title: "Beyond prompts", description: "MCP helps Heym workflows act, not just answer.", tone: "amber" },
    ],
    actions: [
      docsAction("mcp-docs", "Open MCP docs", "Read the MCP tab guide.", docsTarget("tabs", "mcp-tab", "MCP Tab")),
      docsAction("agent-architecture-docs", "Agent architecture", "See how MCP fits into agent execution.", docsTarget("reference", "agent-architecture", "Agent Architecture")),
    ],
    details: [
      { id: "mcp-fit", title: "Where it matters", content: "This surface is most important when your agent needs tool use, environment access, or system integrations that live outside a single node." },
      { id: "mcp-ops", title: "Operational mindset", content: "Treat MCP connections like shared infrastructure: stable labels, clear ownership, and predictable transport settings make debugging much easier." },
    ],
    docsTarget: docsTarget("tabs", "mcp-tab", "MCP Tab"),
  },
  "dashboard:traces": {
    id: "dashboard:traces",
    title: "Traces",
    summary: "Inspect detailed AI and workflow execution traces when you need to understand what happened, not just whether it worked.",
    bullets: [
      "Use traces for debugging, analysis, and prompt-quality inspection.",
      "They help explain model behavior, latency, and execution paths.",
      "This is where you go after a surprising result or flaky run.",
    ],
    highlights: [
      { eyebrow: "Debugging", title: "See hidden steps", description: "Trace data exposes what the workflow and model actually did.", tone: "primary" },
      { eyebrow: "Evaluation", title: "Support iteration", description: "Use traces when tuning prompts, tools, or model selection.", tone: "blue" },
      { eyebrow: "Confidence", title: "Explain outcomes", description: "Good traces reduce guesswork during failure analysis.", tone: "green" },
    ],
    actions: [
      docsAction("traces-docs", "Open traces docs", "Read the traces dashboard guide.", docsTarget("tabs", "traces-tab", "Traces Tab")),
    ],
    details: [
      { id: "traces-when", title: "When this becomes essential", content: "Traces matter most once your workflows become multi-step, model-heavy, or tool-driven, because the surface-level output stops telling the whole story." },
      { id: "traces-vs-history", title: "Trace vs history", content: "Execution history shows that a run happened. Traces help explain why the run behaved the way it did." },
    ],
    docsTarget: docsTarget("tabs", "traces-tab", "Traces Tab"),
  },
  "dashboard:analytics": {
    id: "dashboard:analytics",
    title: "Analytics",
    summary: "Track usage patterns and system behavior so you can understand what is active, growing, or drifting over time.",
    bullets: [
      "Use analytics to spot adoption, throughput, and unusual changes.",
      "This is a platform-level view rather than a single-run debug tool.",
      "Pair it with traces and history when you want both signal and explanation.",
    ],
    highlights: [
      { eyebrow: "Signals", title: "Usage visibility", description: "See trends instead of reasoning from one run at a time.", tone: "primary" },
      { eyebrow: "Capacity", title: "Operational awareness", description: "Spikes and drops become easier to notice and investigate.", tone: "amber" },
      { eyebrow: "Decision support", title: "What to optimize next", description: "Analytics helps prioritize the workflows and surfaces that matter most.", tone: "blue" },
    ],
    actions: [
      docsAction("analytics-docs", "Open analytics docs", "Read the analytics dashboard guide.", docsTarget("tabs", "analytics-tab", "Analytics Tab")),
    ],
    details: [
      { id: "analytics-purpose", title: "What this is for", content: "Use analytics when your question is about patterns, adoption, or aggregate behavior rather than one workflow failure." },
      { id: "analytics-followup", title: "How to act on it", content: "Spot the signal here, then move into traces, history, or the editor to understand the root cause and change the workflow." },
    ],
    docsTarget: docsTarget("tabs", "analytics-tab", "Analytics Tab"),
  },
  "dashboard:teams": {
    id: "dashboard:teams",
    title: "Teams",
    summary: "Manage shared access so workflows, credentials, variables, and vector stores can be used collaboratively without duplication.",
    bullets: [
      "Teams are the cleanest way to share platform resources at scale.",
      "Use them when access should follow a group rather than one person.",
      "This tab helps collaboration stay organized as the workspace grows.",
    ],
    highlights: [
      { eyebrow: "Collaboration", title: "Share by group", description: "Grant access once to a team instead of repeating user-level shares.", tone: "primary" },
      { eyebrow: "Operational clarity", title: "Cleaner ownership", description: "Resources become easier to manage when sharing follows real teams.", tone: "green" },
      { eyebrow: "Scale", title: "Less admin overhead", description: "New members inherit access from the team instead of manual rework.", tone: "blue" },
    ],
    actions: [
      docsAction("teams-docs", "Open teams docs", "Read the teams dashboard guide.", docsTarget("tabs", "teams-tab", "Teams Tab")),
      docsAction("sharing-docs", "Credential sharing", "See how resource sharing works in detail.", docsTarget("reference", "credentials-sharing", "Credentials Sharing")),
    ],
    details: [
      { id: "teams-role", title: "What teams unlock", content: "Teams connect identity and resource access, which helps keep workflows and infrastructure aligned with how people actually work together." },
      { id: "teams-tip", title: "Practical usage", content: "Prefer team sharing when a workflow or credential belongs to an ongoing group, not just a temporary pair of collaborators." },
    ],
    docsTarget: docsTarget("tabs", "teams-tab", "Teams Tab"),
  },
  "dashboard:logs": {
    id: "dashboard:logs",
    title: "Logs",
    summary: "Read stack-level logs when you need infrastructure visibility beyond workflow outputs and execution panels.",
    bullets: [
      "Use logs for service debugging, container health, and environment issues.",
      "This surface helps when the problem is below the workflow layer.",
      "Pair it with traces when you need both app-level and system-level evidence.",
    ],
    highlights: [
      { eyebrow: "Infra view", title: "Container-level visibility", description: "See what backend services are doing underneath Heym's UI.", tone: "amber" },
      { eyebrow: "Troubleshooting", title: "Find root causes", description: "Logs help diagnose startup failures, crashes, or integration issues.", tone: "primary" },
      { eyebrow: "Complementary", title: "Different from workflow results", description: "Workflow output shows execution results; logs show system behavior.", tone: "blue" },
    ],
    actions: [
      docsAction("logs-docs", "Open logs docs", "Read the logs dashboard guide.", docsTarget("tabs", "logs-tab", "Logs Tab")),
    ],
    details: [
      { id: "logs-boundary", title: "When to use logs", content: "Come here when the issue looks environmental, service-level, or deployment-related rather than specific to one node configuration." },
      { id: "logs-combo", title: "Best paired with", content: "Use logs with traces and execution history to move from symptom to cause faster." },
    ],
    docsTarget: docsTarget("tabs", "logs-tab", "Logs Tab"),
  },
  evals: {
    id: "evals",
    title: "Evals",
    summary: "Create repeatable benchmarks for agent workflows so prompt, model, and workflow changes can be compared with less guesswork.",
    bullets: [
      "Suites and test cases help turn subjective workflow quality into something you can measure.",
      "This is the right place for regression checks before shipping prompt or model updates.",
      "Use it to compare multiple models against the same workload and scoring method.",
    ],
    highlights: [
      { eyebrow: "Quality loop", title: "Benchmark your agents", description: "Run the same suite repeatedly instead of relying on anecdotal checks.", tone: "primary" },
      { eyebrow: "Comparison", title: "Model and prompt testing", description: "See how different settings behave against the same test set.", tone: "blue" },
      { eyebrow: "Confidence", title: "Safer iteration", description: "Evals make improvements easier to prove before rollout.", tone: "green" },
    ],
    actions: [
      docsAction("evals-docs", "Open evals docs", "Read the evals page guide.", docsTarget("tabs", "evals-tab", "Evals Tab")),
      docsAction("agent-docs", "Agent node reference", "See the workflow surface that most eval suites target.", docsTarget("nodes", "agent-node", "Agent Node")),
    ],
    details: [
      { id: "evals-design", title: "How to think about suites", content: "A good suite mirrors real user cases, edge conditions, and any approval or HITL steps you cannot afford to break." },
      { id: "evals-usage", title: "What to compare", content: "Common comparisons include prompt variants, model choices, temperature settings, and workflow revisions across the same dataset." },
    ],
    docsTarget: docsTarget("tabs", "evals-tab", "Evals Tab"),
  },
  docs: {
    id: "docs",
    title: "Documentation",
    summary: "Browse concise platform reference material without leaving the app, then dive deeper only when you actually need it.",
    bullets: [
      "Docs in Heym are built for fast scanning first and detailed follow-up second.",
      "Use the sidebar, search, and related links to move between concepts quickly.",
      "The showcase here points you to the current article when one is open.",
    ],
    highlights: [
      { eyebrow: "In-app reference", title: "Always nearby", description: "Documentation stays inside the same product flow instead of sending you elsewhere.", tone: "primary" },
      { eyebrow: "Scannable", title: "Short before deep", description: "Articles lead with the essentials and branch out through related links.", tone: "blue" },
      { eyebrow: "Context aware", title: "Current article handoff", description: "When you are reading a doc already, the learn-more action follows that article.", tone: "green" },
    ],
    actions: [
      docsAction("docs-home", "Browse introduction", "Open the docs introduction as the default entry point.", docsTarget("getting-started", "introduction", "Introduction")),
    ],
    details: [
      { id: "docs-nav", title: "How to navigate fast", content: "Use the documentation sidebar for category browsing and command/search entry points when you already know the topic." },
      { id: "docs-depth", title: "How showcase helps", content: "The showcase layer keeps the summary lightweight and hands off to full docs only when you want deeper guidance." },
    ],
    docsTarget: docsTarget("getting-started", "introduction", "Introduction"),
  },
  "dashboard:schedules": {
    id: "dashboard:schedules",
    title: "Scheduled",
    summary: "See every active cron workflow on a visual calendar so you always know when your automations are set to run.",
    bullets: [
      "Switch between day, week, and month views to get the right level of resolution.",
      "Hover a block to preview the cron expression; click to jump straight to the canvas.",
      "Use this tab to audit scheduling density and spot overlapping automations.",
    ],
    highlights: [
      { eyebrow: "Visibility", title: "Calendar-first view", description: "Active cron workflows appear as blocks at their scheduled times.", tone: "primary" },
      { eyebrow: "Navigation", title: "One click to the canvas", description: "Click any block to open the workflow editor directly.", tone: "blue" },
      { eyebrow: "Range", title: "Day, week, or month", description: "Switch granularity to audit individual hours or plan across a whole month.", tone: "green" },
    ],
    actions: [
      docsAction("schedules-docs", "Open Scheduled docs", "Read the Scheduled tab reference.", docsTarget("tabs", "scheduled-tab", "Scheduled Tab")),
      docsAction("cron-node-docs", "Cron node reference", "See how to configure cron triggers on the canvas.", docsTarget("nodes", "cron-node", "Cron")),
    ],
    details: [
      { id: "schedules-when", title: "When to use this tab", content: "Use it to audit how much is running, spot scheduling conflicts, and confirm that important workflows are still active before and after changes." },
      { id: "schedules-color", title: "Color coding", content: "Each workflow gets a consistent color derived from its ID, so the same workflow is always the same color across day, week, and month views." },
    ],
    docsTarget: docsTarget("tabs", "scheduled-tab", "Scheduled Tab"),
  },
  "dashboard:datatable": {
    id: "dashboard:datatable",
    title: "DataTable",
    summary: "Create and manage structured data tables directly in Heym for use in workflows.",
    bullets: [
      "Create tables with typed columns, then populate them manually or via CSV import.",
      "Use the DataTable workflow node to read, write, and query rows programmatically.",
      "Share tables with users or teams with read or write permission levels.",
    ],
    highlights: [
      { eyebrow: "First-party data", title: "Built-in storage", description: "Store structured data without external databases or API keys.", tone: "primary" },
      { eyebrow: "Workflow integration", title: "DataTable node", description: "Find, insert, update, and remove rows from any workflow.", tone: "blue" },
      { eyebrow: "Collaboration", title: "Sharing & permissions", description: "Share tables with granular read/write access for users and teams.", tone: "green" },
    ],
    actions: [
      docsAction("datatable-docs", "DataTable tab docs", "Read the DataTable tab reference.", docsTarget("tabs", "datatable-tab", "DataTable")),
      docsAction("datatable-node-docs", "DataTable node docs", "Read the DataTable node reference.", docsTarget("nodes", "datatable-node", "DataTable")),
    ],
    details: [
      { id: "datatable-overview", title: "What are DataTables?", content: "DataTables are first-party structured storage in Heym. Define columns with types (string, number, boolean, date, JSON), manage rows with inline editing, and import/export CSV." },
      { id: "datatable-workflow", title: "Using in workflows", content: "The DataTable node supports find, getAll, getById, insert, update, remove, and upsert operations. No credentials needed — tables are accessed directly by the workflow owner." },
    ],
    docsTarget: docsTarget("tabs", "datatable-tab", "DataTable"),
  },
  editor: {
    id: "editor",
    title: "Workflow Editor",
    summary: "Build and refine workflows on the canvas, then inspect, debug, and iterate without leaving the execution context.",
    bullets: [
      "The editor is where node design, data flow, and execution behavior come together.",
      "Use side panels and history to move between building and debugging quickly.",
      "This page favors active editing, so the showcase stays compact by default.",
    ],
    highlights: [
      { eyebrow: "Canvas", title: "Visual workflow design", description: "Connect nodes, branch logic, and model the runtime flow directly.", tone: "primary" },
      { eyebrow: "Iteration", title: "Debug as you build", description: "Use history, debug panels, and execution results to tighten the loop.", tone: "blue" },
      { eyebrow: "Depth", title: "Advanced features nearby", description: "Portal, sharing, templates, and validation all live close to the canvas.", tone: "amber" },
    ],
    actions: [
      docsAction("canvas-docs", "Open canvas docs", "Read the canvas features reference.", docsTarget("reference", "canvas-features", "Canvas Features")),
      docsAction("shortcuts-docs", "Keyboard shortcuts", "Open the editor shortcut guide.", docsTarget("reference", "keyboard-shortcuts", "Keyboard Shortcuts")),
    ],
    details: [
      { id: "editor-flow", title: "Best working rhythm", content: "Build on the canvas, validate assumptions with execution output, and use side panels to adjust configuration without losing your place." },
      { id: "editor-complexity", title: "Why the showcase stays short", content: "The editor already carries a lot of interface density, so the showcase is deliberately a guide rail, not another heavy panel." },
    ],
    docsTarget: docsTarget("reference", "canvas-features", "Canvas Features"),
  },
};
