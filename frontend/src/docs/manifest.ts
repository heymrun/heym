export interface DocItem {
  slug: string;
  title: string;
}

export interface DocCategory {
  id: string;
  label: string;
  items: DocItem[];
}

export const DOCS_MANIFEST: Record<string, DocCategory> = {
  "getting-started": {
    id: "getting-started",
    label: "Getting Started",
    items: [
      { slug: "introduction", title: "Introduction" },
      { slug: "why-heym", title: "Why Heym" },
      { slug: "quick-start", title: "Quick Start" },
      { slug: "core-concepts", title: "Core Concepts" },
      { slug: "running-and-deployment", title: "Running & Deployment" },
    ],
  },
  nodes: {
    id: "nodes",
    label: "Nodes",
    items: [
      { slug: "agent-node", title: "Agent Node" },
      { slug: "input-node", title: "Input" },
      { slug: "cron-node", title: "Cron" },
      { slug: "telegram-trigger-node", title: "Telegram Trigger" },
      { slug: "imap-trigger-node", title: "IMAP Trigger" },
      { slug: "websocket-trigger-node", title: "WebSocket Trigger" },
      { slug: "rabbitmq-node", title: "RabbitMQ" },
      { slug: "llm-node", title: "LLM" },
      { slug: "rag-node", title: "Qdrant RAG" },
      { slug: "condition-node", title: "Condition" },
      { slug: "switch-node", title: "Switch" },
      { slug: "merge-node", title: "Merge" },
      { slug: "loop-node", title: "Loop" },
      { slug: "set-node", title: "Set" },
      { slug: "variable-node", title: "Variable" },
      { slug: "execute-node", title: "Execute" },
      { slug: "http-node", title: "HTTP" },
      { slug: "websocket-send-node", title: "WebSocket Send" },
      { slug: "telegram-node", title: "Telegram" },
      { slug: "slack-node", title: "Slack" },
      { slug: "slack-trigger-node", title: "Slack Trigger" },
      { slug: "send-email-node", title: "Send Email" },
      { slug: "redis-node", title: "Redis" },
      { slug: "grist-node", title: "Grist" },
      { slug: "google-sheets-node", title: "Google Sheets" },
      { slug: "bigquery-node", title: "BigQuery" },
      { slug: "drive-node", title: "Drive" },
      { slug: "datatable-node", title: "DataTable" },
      { slug: "crawler-node", title: "Crawler" },
      { slug: "playwright-node", title: "Playwright" },
      { slug: "output-node", title: "Output" },
      { slug: "json-output-mapper-node", title: "JSON output mapper" },
      { slug: "wait-node", title: "Wait" },
      { slug: "sticky-note-node", title: "Sticky Note" },
      { slug: "console-log-node", title: "Console Log" },
      { slug: "disable-node", title: "Disable Node" },
      { slug: "throw-error-node", title: "Throw Error" },
      { slug: "error-handler-node", title: "Error Handler" },
    ],
  },
  reference: {
    id: "reference",
    label: "Reference",
    items: [
      { slug: "node-types", title: "Node Types" },
      { slug: "features", title: "Full Feature Set" },
      { slug: "expression-dsl", title: "Expression DSL" },
      { slug: "global-variables", title: "Global Variables" },
      { slug: "expression-evaluation-dialog", title: "Expression Evaluation Dialog" },
      { slug: "workflow-structure", title: "Workflow Structure" },
      { slug: "canvas-features", title: "Canvas Features" },
      { slug: "keyboard-shortcuts", title: "Keyboard Shortcuts" },
      { slug: "ai-assistant", title: "AI Assistant" },
      { slug: "chat-with-docs", title: "Chat with Docs" },
      { slug: "workflow-organization", title: "Workflow Organization" },
      { slug: "quick-drawer", title: "Quick Drawer" },
      { slug: "contextual-showcase", title: "Contextual Showcase" },
      { slug: "credentials", title: "Credentials" },
      { slug: "credentials-sharing", title: "Credentials Sharing" },
      { slug: "teams", title: "Teams" },
      { slug: "parallel-execution", title: "Parallel Execution" },
      { slug: "agent-architecture", title: "Agent Architecture" },
      { slug: "agent-persistent-memory", title: "Agent Persistent Memory" },
      { slug: "human-in-the-loop", title: "Human-in-the-Loop" },
      { slug: "webhooks", title: "Webhooks" },
      { slug: "execution-tokens", title: "Execution Tokens" },
      { slug: "sse-streaming", title: "SSE Streaming" },
      { slug: "triggers", title: "Triggers" },
      { slug: "execution-history", title: "Execution History" },
      { slug: "edit-history", title: "Edit History" },
      { slug: "user-settings", title: "User Settings" },
      { slug: "download-import", title: "Download & Import" },
      { slug: "portal", title: "Portal" },
      { slug: "file-generation", title: "File Generation" },
      { slug: "drive", title: "Drive" },
      { slug: "security", title: "Security" },
      { slug: "integrations", title: "Third-Party Integrations" },
      { slug: "guardrails", title: "Guardrails" },
      { slug: "enterprise", title: "Enterprise" },
    ],
  },
  tabs: {
    id: "tabs",
    label: "Dashboard Tabs",
    items: [
      { slug: "workflows-tab", title: "Workflows" },
      { slug: "templates-tab", title: "Templates" },
      { slug: "global-variables-tab", title: "Variables" },
      { slug: "chat-tab", title: "Chat" },
      { slug: "drive-tab", title: "Drive" },
      { slug: "credentials-tab", title: "Credentials" },
      { slug: "vectorstores-tab", title: "Vectorstores" },
      { slug: "mcp-tab", title: "MCP" },
      { slug: "traces-tab", title: "Traces" },
      { slug: "analytics-tab", title: "Analytics" },
      { slug: "evals-tab", title: "Evals" },
      { slug: "teams-tab", title: "Teams" },
      { slug: "datatable-tab", title: "DataTable" },
      { slug: "scheduled-tab", title: "Scheduled" },
      { slug: "logs-tab", title: "Logs" },
    ],
  },
};

export function getDocPath(categoryId: string, slug: string): string {
  return `/docs/${categoryId}/${slug}`;
}

export function getPrevNextDoc(
  currentPath: string
): { prev: { path: string; title: string } | null; next: { path: string; title: string } | null } {
  const items = getAllDocItems();
  const normalized = currentPath.replace(/^\//, "").replace(/\/$/, "").replace(/^docs\//, "");
  const idx = items.findIndex((i) => `${i.categoryId}/${i.slug}` === normalized);
  if (idx < 0) return { prev: null, next: null };
  const prevItem = idx > 0 ? items[idx - 1] : null;
  const nextItem = idx >= 0 && idx < items.length - 1 ? items[idx + 1] : null;
  return {
    prev: prevItem ? { path: getDocPath(prevItem.categoryId, prevItem.slug), title: prevItem.title } : null,
    next: nextItem ? { path: getDocPath(nextItem.categoryId, nextItem.slug), title: nextItem.title } : null,
  };
}

export function getAllDocItems(): { categoryId: string; categoryLabel: string; slug: string; title: string }[] {
  const items: { categoryId: string; categoryLabel: string; slug: string; title: string }[] = [];
  for (const [categoryId, category] of Object.entries(DOCS_MANIFEST)) {
    for (const item of category.items) {
      items.push({
        categoryId,
        categoryLabel: category.label,
        slug: item.slug,
        title: item.title,
      });
    }
  }
  return items;
}
