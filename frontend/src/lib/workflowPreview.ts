import type { NodeData, Workflow, WorkflowEdge, WorkflowNode } from "@/types/workflow";

/** Nodes that never appear as a step in the preview panel. */
const NON_STEP_NODE_TYPES = new Set(["sticky"]);

/** Node types that start a workflow on their own. Mirrors backend TRIGGER_NODE_TYPES. */
export const TRIGGER_NODE_TYPES = new Set([
  "cron",
  "telegramTrigger",
  "slackTrigger",
  "discordTrigger",
  "imapTrigger",
  "websocketTrigger",
  "fileUploadTrigger",
  "heymTrigger",
  "pluginTrigger",
  "rabbitmq",
]);

export interface WorkflowStep {
  id: string;
  /** 1-based position, rendered as "01", "02", ... */
  order: number;
  title: string;
  subtitle: string;
  active: boolean;
}

export interface TriggerSummary {
  headline: string;
  detail: string;
  /** Set only for webhook-invoked workflows, where a ready-to-run request beats prose. */
  curl?: string;
  /** Public chat portal URL, when the workflow exposes one. */
  portalUrl?: string;
}

/** The public portal address for a workflow, or null when no portal is published. */
export function buildPortalUrl(workflow: Workflow, origin?: string): string | null {
  if (!workflow.portal_enabled || !workflow.portal_slug) return null;
  const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  return `${base.replace(/\/$/, "")}/chat/${workflow.portal_slug}`;
}

/** "slackTrigger" -> "Slack Trigger" */
export function humanizeNodeType(nodeType: string): string {
  const spaced = nodeType.replace(/([a-z0-9])([A-Z])/g, "$1 $2");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function firstNonEmpty(...values: (string | undefined | null)[]): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim().length > 0) return value.trim();
  }
  return null;
}

/**
 * The most identifying detail we can show under a step's title: the model, the operation,
 * the schedule - whatever this node type actually configures.
 */
export function describeNode(node: WorkflowNode): string {
  const data = (node.data ?? {}) as NodeData & Record<string, unknown>;

  const specific = firstNonEmpty(
    data.model,
    data.cronExpression ? `cron: ${data.cronExpression}` : null,
    data.websocketUrl,
    data.targetWorkflowName,
    findOperationValue(data),
    data.conversion,
  );

  if (specific) return specific;
  return humanizeNodeType(node.type);
}

/** Every integration node names its own operation field (`githubOperation`, `s3Operation`, ...). */
function findOperationValue(data: Record<string, unknown>): string | null {
  for (const [key, value] of Object.entries(data)) {
    if (!key.endsWith("Operation")) continue;
    if (typeof value === "string" && value.trim().length > 0) return value.trim();
  }
  return null;
}

/**
 * Order steps the way the graph runs them: breadth-first from the start nodes, with any
 * node the traversal never reaches appended so nothing silently disappears.
 */
export function orderWorkflowSteps(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): WorkflowStep[] {
  const eligible = nodes.filter((node) => !NON_STEP_NODE_TYPES.has(node.type));
  const eligibleIds = new Set(eligible.map((node) => node.id));

  const outgoing = new Map<string, string[]>();
  const targeted = new Set<string>();
  for (const edge of edges) {
    if (!eligibleIds.has(edge.source) || !eligibleIds.has(edge.target)) continue;
    const list = outgoing.get(edge.source) ?? [];
    list.push(edge.target);
    outgoing.set(edge.source, list);
    targeted.add(edge.target);
  }

  const byId = new Map(eligible.map((node) => [node.id, node]));
  const visited = new Set<string>();
  const ordered: WorkflowNode[] = [];

  const queue = eligible.filter((node) => !targeted.has(node.id)).map((node) => node.id);
  while (queue.length > 0) {
    const id = queue.shift() as string;
    if (visited.has(id)) continue;
    visited.add(id);
    const node = byId.get(id);
    if (node) ordered.push(node);
    for (const next of outgoing.get(id) ?? []) {
      if (!visited.has(next)) queue.push(next);
    }
  }

  for (const node of eligible) {
    if (!visited.has(node.id)) ordered.push(node);
  }

  return ordered.map((node, index) => ({
    id: node.id,
    order: index + 1,
    title: firstNonEmpty(node.data?.label) ?? humanizeNodeType(node.type),
    subtitle: describeNode(node),
    active: node.data?.active !== false,
  }));
}

/**
 * What starts this workflow. Trigger nodes describe themselves; anything else is reachable
 * over the workflow's own execute endpoint, so the auth mode is the useful detail.
 */
export function summarizeTrigger(workflow: Workflow): TriggerSummary {
  const portalUrl = buildPortalUrl(workflow) ?? undefined;
  const triggerNodes = workflow.nodes.filter((node) => TRIGGER_NODE_TYPES.has(node.type));
  const activeTrigger = triggerNodes.find((node) => node.data?.active !== false);
  const node = activeTrigger ?? triggerNodes[0];

  if (node) {
    const paused = node.data?.active === false;
    if (node.type === "cron") {
      const expression = firstNonEmpty(node.data?.cronExpression) ?? "not configured";
      return {
        headline: `Schedule: ${expression}`,
        detail: paused ? "Cron trigger is deactivated" : "Runs on the configured cron schedule",
        portalUrl,
      };
    }
    const label = firstNonEmpty(node.data?.label);
    return {
      headline: humanizeNodeType(node.type),
      detail: paused
        ? "Trigger is deactivated"
        : label
          ? `Listening on "${label}"`
          : "Listening for incoming events",
      portalUrl,
    };
  }

  // The endpoint is a UUID-laden line nobody can act on and the auth mode is already
  // spelled out in the request, so the card shows a copy button instead of prose.
  return {
    headline: "Webhook",
    detail: "",
    curl: buildWorkflowCurl(workflow),
    portalUrl,
  };
}

/**
 * A runnable POST for this workflow's execute endpoint, mirroring the editor's cURL panel:
 * same headers, same auth placeholders, body keys taken from the start node's input fields.
 */
export function buildWorkflowCurl(workflow: Workflow, origin?: string): string {
  const base = origin ?? (typeof window === "undefined" ? "" : window.location.origin);
  const path = workflow.sse_enabled
    ? `/api/workflows/${workflow.id}/execute/stream`
    : `/api/workflows/${workflow.id}/execute`;
  const url = `${base.replace(/\/$/, "")}${path}`;

  const method = (workflow.http_method || "POST").toUpperCase();
  const sendsBody = method !== "GET" && method !== "DELETE";

  const headers = ['-H "X-Trigger-Source: API"'];
  if (sendsBody) {
    headers.unshift('-H "Content-Type: application/json"');
  }
  if (workflow.sse_enabled) {
    headers.push('-H "Accept: text/event-stream"');
  }
  if (workflow.auth_type === "header_auth") {
    headers.push(`-H "${workflow.auth_header_key || "X-API-Key"}: <your-secret-value>"`);
  } else if (workflow.auth_type === "jwt") {
    headers.push('-H "Authorization: Bearer <your-execution-token>"');
  }

  const lines = [
    `curl -X ${method}${workflow.sse_enabled ? " --no-buffer" : ""} \\`,
    ...headers.map((header) => `  ${header} \\`),
  ];
  if (sendsBody) {
    const body = JSON.stringify(buildSampleInputs(workflow));
    lines.push(`  "${url}" \\`, `  -d '${body}'`);
  } else {
    lines.push(`  "${url}"`);
  }
  return lines.join("\n");
}

/** Body keys come from the input fields of start nodes, so the sample matches what the run reads. */
function buildSampleInputs(workflow: Workflow): Record<string, string> {
  const targeted = new Set(workflow.edges.map((edge) => edge.target));
  const inputs: Record<string, string> = {};

  for (const node of workflow.nodes) {
    if (targeted.has(node.id) || node.data?.active === false) continue;
    for (const field of node.data?.inputFields ?? []) {
      if (field.key) inputs[field.key] = field.defaultValue ?? "";
    }
  }

  return inputs;
}
