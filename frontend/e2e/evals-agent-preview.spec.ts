import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  createWorkflow,
  deleteWorkflow,
  prepareAuthenticatedPage,
  selectSearchableOption,
} from "./support";

const ORCHESTRATOR = "node_orchestrator";

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

function agentData(label: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    label,
    model: "claude-haiku-5-5",
    temperature: 0.3,
    systemInstruction: "You are a travel expert.",
    userMessage: "$cityInput.text",
    tools: [],
    mcpConnections: [],
    skills: [],
    toolTimeoutSeconds: 30,
    requestTimeoutSeconds: 60,
    maxToolIterations: 30,
    ...extra,
  };
}

// A layout that does not overlap in the editor, packed the way people leave their canvas.
function workflowNodes(): Record<string, unknown>[] {
  return [
    {
      id: "node_city",
      type: "textInput",
      position: { x: 0, y: 120 },
      data: { label: "cityInput", inputFields: [{ key: "text" }] },
    },
    {
      id: ORCHESTRATOR,
      type: "agent",
      position: { x: 260, y: 120 },
      data: agentData("orchestrator", {
        isOrchestrator: true,
        subAgentLabels: ["bestActivities", "bestFoods"],
      }),
    },
    {
      id: "node_output",
      type: "output",
      position: { x: 500, y: 120 },
      data: { label: "travelRecommendation", message: "$orchestrator.text" },
    },
    {
      id: "node_knowledge",
      type: "rag",
      position: { x: 260, y: -100 },
      data: { label: "cityKnowledge" },
    },
    {
      id: "node_activities",
      type: "agent",
      position: { x: 140, y: 330 },
      data: agentData("bestActivities", { model: "glm-5.3-flash" }),
    },
    {
      id: "node_foods",
      type: "agent",
      position: { x: 400, y: 330 },
      data: agentData("bestFoods", { model: "gpt-6-luna" }),
    },
  ];
}

function workflowEdges(): Record<string, unknown>[] {
  return [
    { id: "e_city", source: "node_city", target: ORCHESTRATOR },
    { id: "e_output", source: ORCHESTRATOR, target: "node_output" },
    {
      id: "e_knowledge",
      source: "node_knowledge",
      target: ORCHESTRATOR,
      sourceHandle: "tool-output",
      targetHandle: "tool-input",
    },
  ];
}

async function nodeBoxes(scope: Locator): Promise<Map<string, Box>> {
  const nodes = scope.locator(".vue-flow__node");
  await expect(nodes.first()).toBeVisible();
  const boxes = new Map<string, Box>();
  for (let index = 0; index < (await nodes.count()); index += 1) {
    const node = nodes.nth(index);
    const id = await node.getAttribute("data-id");
    const box = await node.boundingBox();
    if (id && box) boxes.set(id, box);
  }
  return boxes;
}

function overlapping(boxes: Map<string, Box>): string[] {
  const entries = [...boxes.entries()];
  const pairs: string[] = [];
  for (let i = 0; i < entries.length; i += 1) {
    for (let j = i + 1; j < entries.length; j += 1) {
      const [idA, a] = entries[i];
      const [idB, b] = entries[j];
      if (a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height) {
        pairs.push(`${idA} × ${idB}`);
      }
    }
  }
  return pairs;
}

async function openAgentStep(page: Page, workflowId: string, workflowName: string): Promise<void> {
  // The picker lists agents that have run; this one has no traces in a fresh database.
  await page.route("**/api/evals/agents", (route) =>
    route.fulfill({
      json: [
        {
          workflow_id: workflowId,
          workflow_name: workflowName,
          node_id: ORCHESTRATOR,
          node_label: "orchestrator",
          run_count: 3,
          last_run_at: new Date().toISOString(),
        },
      ],
    }),
  );
  await page.goto("/evals?new=agent");
  await selectSearchableOption(page, page.getByTestId("agent-suite-workflow"), workflowName);
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("the agent preview keeps the editor's layout without overlapping nodes", async ({ page }) => {
  const name = `Agent preview ${Date.now()}`;
  const workflow = await createWorkflow(page, name, workflowNodes(), workflowEdges());
  try {
    await page.goto(`/workflows/${workflow.id}`);
    expect(overlapping(await nodeBoxes(page.locator(".vue-flow").first()))).toEqual([]);

    await openAgentStep(page, workflow.id, name);
    const canvas = page.getByTestId("agent-suite-canvas");
    await expect(canvas.locator(`.vue-flow__node[data-id="${ORCHESTRATOR}"]`)).toBeVisible();
    expect(overlapping(await nodeBoxes(canvas))).toEqual([]);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("the agent's details list nodes attached to its tool input", async ({ page }) => {
  const name = `Agent tools ${Date.now()}`;
  const workflow = await createWorkflow(page, name, workflowNodes(), workflowEdges());
  try {
    await openAgentStep(page, workflow.id, name);
    const details = page.getByTestId("agent-suite-agent-details");
    await expect(details).toContainText("Sub-agent");
    await expect(details.getByText("cityKnowledge")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
