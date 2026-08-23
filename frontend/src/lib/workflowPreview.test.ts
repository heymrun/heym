import { describe, expect, it } from "vitest";

import type { Workflow, WorkflowEdge, WorkflowNode } from "@/types/workflow";
import {
  buildPortalUrl,
  buildWorkflowCurl,
  humanizeNodeType,
  orderWorkflowSteps,
  summarizeTrigger,
} from "@/lib/workflowPreview";

function node(id: string, type: string, data: Record<string, unknown> = {}): WorkflowNode {
  return { id, type, position: { x: 0, y: 0 }, data } as unknown as WorkflowNode;
}

function edge(source: string, target: string): WorkflowEdge {
  return { id: `${source}-${target}`, source, target };
}

function workflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: "wf-1",
    name: "wf",
    description: null,
    nodes: [],
    edges: [],
    auth_type: "jwt",
    auth_header_key: null,
    auth_header_value: null,
    auth_header_value_set: false,
    webhook_body_mode: "legacy",
    allow_anonymous: false,
    owner_id: "owner-1",
    cache_ttl_seconds: null,
    rate_limit_requests: null,
    rate_limit_window_seconds: null,
    sse_enabled: false,
    sse_node_config: {},
    auto_recover_runs: true,
    error_workflow_id: null,
    minutes_saved_per_run: null,
    workflow_timeout_seconds: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  } as Workflow;
}

describe("humanizeNodeType", () => {
  it("splits camelCase into words", () => {
    expect(humanizeNodeType("slackTrigger")).toBe("Slack Trigger");
    expect(humanizeNodeType("http")).toBe("Http");
  });
});

describe("orderWorkflowSteps", () => {
  it("orders steps by graph traversal, not array order", () => {
    const nodes = [node("c", "output"), node("a", "textInput"), node("b", "llm")];
    const edges = [edge("a", "b"), edge("b", "c")];

    expect(orderWorkflowSteps(nodes, edges).map((step) => step.id)).toEqual(["a", "b", "c"]);
  });

  it("numbers steps from 1", () => {
    const steps = orderWorkflowSteps([node("a", "textInput"), node("b", "output")], [edge("a", "b")]);

    expect(steps.map((step) => step.order)).toEqual([1, 2]);
  });

  it("treats every node without an incoming edge as a start node", () => {
    const nodes = [node("a", "textInput"), node("b", "llm"), node("solo", "http")];
    const steps = orderWorkflowSteps(nodes, [edge("a", "b")]);

    expect(steps.map((step) => step.id).sort()).toEqual(["a", "b", "solo"]);
  });

  it("appends nodes the traversal cannot reach, so a cycle hides nothing", () => {
    // x and y only point at each other, so neither is a start node.
    const nodes = [node("a", "textInput"), node("x", "llm"), node("y", "llm")];
    const steps = orderWorkflowSteps(nodes, [edge("x", "y"), edge("y", "x")]);

    expect(steps.map((step) => step.id)).toEqual(["a", "x", "y"]);
  });

  it("skips sticky notes", () => {
    const steps = orderWorkflowSteps([node("a", "textInput"), node("s", "sticky")], []);

    expect(steps.map((step) => step.id)).toEqual(["a"]);
  });

  it("prefers the label, then the most identifying config value", () => {
    const steps = orderWorkflowSteps(
      [
        node("a", "llm", { label: "Summarize", model: "gpt-4o" }),
        node("b", "github", { githubOperation: "createIssue" }),
        node("c", "cron", { cronExpression: "0 * * * *" }),
        node("d", "output"),
      ],
      [],
    );

    expect(steps.map((step) => [step.title, step.subtitle])).toEqual([
      ["Summarize", "gpt-4o"],
      ["Github", "createIssue"],
      ["Cron", "cron: 0 * * * *"],
      ["Output", "Output"],
    ]);
  });

  it("marks deactivated nodes inactive", () => {
    const steps = orderWorkflowSteps([node("a", "llm", { active: false })], []);

    expect(steps[0].active).toBe(false);
  });
});

describe("summarizeTrigger", () => {
  it("describes an active cron schedule", () => {
    const summary = summarizeTrigger(
      workflow({ nodes: [node("n1", "cron", { cronExpression: "0 9 * * *" })] }),
    );

    expect(summary.headline).toBe("Schedule: 0 9 * * *");
    expect(summary.curl).toBeUndefined();
  });

  it("reports a deactivated trigger", () => {
    const summary = summarizeTrigger(
      workflow({ nodes: [node("n1", "cron", { cronExpression: "0 9 * * *", active: false })] }),
    );

    expect(summary.detail).toContain("deactivated");
  });

  it("describes an event trigger", () => {
    const summary = summarizeTrigger(
      workflow({ nodes: [node("n1", "slackTrigger", { label: "slackEvent" })] }),
    );

    expect(summary.headline).toBe("Slack Trigger");
    expect(summary.curl).toBeUndefined();
  });

  it("offers a cURL and no auth prose for webhook workflows", () => {
    const summary = summarizeTrigger(workflow({ nodes: [node("n1", "textInput")] }));

    expect(summary.headline).toBe("Webhook");
    expect(summary.detail).toBe("");
    expect(summary.curl).toContain("curl -X POST");
  });
});

describe("buildPortalUrl", () => {
  it("returns null when no portal is published", () => {
    expect(buildPortalUrl(workflow(), "https://heym.test")).toBeNull();
    expect(
      buildPortalUrl(workflow({ portal_enabled: true, portal_slug: null }), "https://heym.test"),
    ).toBeNull();
    expect(
      buildPortalUrl(workflow({ portal_enabled: false, portal_slug: "support" }), "https://heym.test"),
    ).toBeNull();
  });

  it("builds the chat URL from the slug", () => {
    expect(
      buildPortalUrl(workflow({ portal_enabled: true, portal_slug: "support" }), "https://heym.test"),
    ).toBe("https://heym.test/chat/support");
  });
});

describe("summarizeTrigger portal link", () => {
  it("carries the portal URL on a webhook workflow", () => {
    const summary = summarizeTrigger(
      workflow({
        nodes: [node("n1", "textInput")],
        portal_enabled: true,
        portal_slug: "support",
      }),
    );

    expect(summary.portalUrl).toContain("/chat/support");
    expect(summary.curl).toBeTruthy();
  });

  it("carries the portal URL on a cron workflow too", () => {
    const summary = summarizeTrigger(
      workflow({
        nodes: [node("n1", "cron", { cronExpression: "0 9 * * *" })],
        portal_enabled: true,
        portal_slug: "daily",
      }),
    );

    expect(summary.portalUrl).toContain("/chat/daily");
  });

  it("leaves the portal URL unset when no portal exists", () => {
    expect(summarizeTrigger(workflow({ nodes: [node("n1", "textInput")] })).portalUrl)
      .toBeUndefined();
  });
});

describe("buildWorkflowCurl", () => {
  it("includes the execute endpoint and default headers", () => {
    const command = buildWorkflowCurl(workflow(), "https://heym.test");

    expect(command).toContain('"https://heym.test/api/workflows/wf-1/execute"');
    expect(command).toContain('-H "Content-Type: application/json"');
    expect(command).toContain('-H "X-Trigger-Source: API"');
  });

  it("uses the stream endpoint and SSE headers when SSE is on", () => {
    const command = buildWorkflowCurl(workflow({ sse_enabled: true }), "https://heym.test");

    expect(command).toContain("/execute/stream");
    expect(command).toContain("--no-buffer");
    expect(command).toContain('-H "Accept: text/event-stream"');
  });

  it("uses the configured header name for header auth", () => {
    const command = buildWorkflowCurl(
      workflow({ auth_type: "header_auth", auth_header_key: "X-Custom" }),
      "https://heym.test",
    );

    expect(command).toContain('-H "X-Custom: <your-secret-value>"');
  });

  it("defaults to POST when no method is configured", () => {
    const command = buildWorkflowCurl(workflow(), "https://heym.test");

    expect(command).toContain("curl -X POST");
  });

  it("uses the configured method", () => {
    const command = buildWorkflowCurl(workflow({ http_method: "PUT" }), "https://heym.test");

    expect(command).toContain("curl -X PUT");
  });

  it("drops the body and content type for GET", () => {
    const command = buildWorkflowCurl(workflow({ http_method: "GET" }), "https://heym.test");

    expect(command).toContain("curl -X GET");
    expect(command).not.toContain("Content-Type");
    expect(command).not.toContain("-d '");
  });

  it("drops the body for DELETE", () => {
    const command = buildWorkflowCurl(workflow({ http_method: "DELETE" }), "https://heym.test");

    expect(command).toContain("curl -X DELETE");
    expect(command).not.toContain("-d '");
  });

  it("omits an auth header for anonymous workflows", () => {
    const command = buildWorkflowCurl(workflow({ auth_type: "anonymous" }), "https://heym.test");

    expect(command).not.toContain("Authorization");
    expect(command).not.toContain("<your-secret-value>");
  });

  it("builds the body from start node input fields only", () => {
    const command = buildWorkflowCurl(
      workflow({
        nodes: [
          node("a", "textInput", { inputFields: [{ key: "text", defaultValue: "hi" }] }),
          node("b", "textInput", { inputFields: [{ key: "downstream" }] }),
        ],
        edges: [edge("a", "b")],
      }),
      "https://heym.test",
    );

    expect(command).toContain(`-d '{"text":"hi"}'`);
    expect(command).not.toContain("downstream");
  });
});
