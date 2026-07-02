import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

interface WorkflowNodeFixture {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

interface PluginSummaryFixture {
  id: string;
  name: string;
  version: string;
  kind: string;
  description: string;
  enabled: boolean;
  nodes: {
    key: string;
    name: string;
    kind: "action" | "trigger";
    description: string;
    fields: {
      key: string;
      label: string;
      type: "string" | "number" | "boolean" | "select";
      required?: boolean;
      secret?: boolean;
      options?: { label: string; value: string }[];
    }[];
  }[];
}

const pluginFixture: PluginSummaryFixture = {
  id: "acme-crm",
  name: "Acme CRM",
  version: "1.0.0",
  kind: "action",
  description: "CRM plugin",
  enabled: true,
  nodes: [
    {
      key: "createContact",
      name: "Create Contact",
      kind: "action",
      description: "Create a contact",
      fields: [
        { key: "email", label: "Email", type: "string", required: true },
        { key: "priority", label: "Priority", type: "number" },
      ],
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

function pluginNode(data: Record<string, unknown>): WorkflowNodeFixture {
  return {
    id: "plugin-node",
    type: "plugin",
    position: { x: 120, y: 160 },
    data: { label: "Acme Plugin", ...data },
  };
}

async function fulfillJson(route: Route, status: number, body: unknown): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockPluginIcon(page: Page): Promise<void> {
  await page.route("**/api/plugins/*/icon**", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Icon not found" }),
    });
  });
}

function pluginFieldLabel(page: Page, label: string, required = false): Locator {
  return page.locator(".properties-panel").getByText(required ? `${label} *` : label, {
    exact: true,
  });
}

async function openPluginProperties(
  page: Page,
  nodeData: Record<string, unknown>,
): Promise<string> {
  const workflow = await createWorkflow(
    page,
    `Plugin Properties ${Date.now()}`,
    [pluginNode(nodeData)],
  );
  await page.goto(`/workflows/${workflow.id}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(1);
  await page.getByRole("button", { name: "Properties", exact: true }).click();
  await page.locator('.vue-flow__node[data-id="plugin-node"]').click();
  return workflow.id;
}

async function openWithPlugins(
  page: Page,
  nodeData: Record<string, unknown>,
  plugins: PluginSummaryFixture[],
): Promise<string> {
  await mockPluginIcon(page);
  await page.route("**/api/plugins", async (route) => {
    await fulfillJson(route, 200, plugins);
  });
  return openPluginProperties(page, nodeData);
}

test("shows a loading state while plugin definitions load", async ({ page }) => {
  await mockPluginIcon(page);
  let releasePlugins: () => void = () => {};
  const pluginsLoaded = new Promise<void>((resolve) => {
    releasePlugins = resolve;
  });
  await page.route("**/api/plugins", async (route) => {
    await pluginsLoaded;
    await fulfillJson(route, 200, [pluginFixture]);
  });

  const workflowId = await openPluginProperties(page, {
    pluginId: "acme-crm",
    pluginNodeKey: "createContact",
  });

  try {
    await expect(page.getByTestId("plugin-node-status")).toHaveText(
      "Loading plugin definition...",
    );
    releasePlugins();
    await expect(pluginFieldLabel(page, "Email", true)).toBeVisible();
  } finally {
    releasePlugins();
    await deleteWorkflow(page, workflowId);
  }
});

test("shows when plugins are disabled", async ({ page }) => {
  await mockPluginIcon(page);
  await page.route("**/api/plugins", async (route) => {
    await fulfillJson(route, 404, {
      detail: "Plugins are disabled. Set HEYM_PLUGINS_ENABLED=true to enable them.",
    });
  });
  const workflowId = await openPluginProperties(page, {
    pluginId: "acme-crm",
    pluginNodeKey: "createContact",
  });

  try {
    await expect(page.getByTestId("plugin-node-status")).toContainText(
      "Plugins are disabled",
    );
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("shows when plugin loading fails", async ({ page }) => {
  await mockPluginIcon(page);
  await page.route("**/api/plugins", async (route) => {
    await fulfillJson(route, 500, { detail: "Plugin database offline" });
  });
  const workflowId = await openPluginProperties(page, {
    pluginId: "acme-crm",
    pluginNodeKey: "createContact",
  });

  try {
    await expect(page.getByTestId("plugin-node-status")).toHaveText(
      "Unable to load plugins: Plugin database offline",
    );
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("shows when no plugins are installed", async ({ page }) => {
  const workflowId = await openWithPlugins(page, {
    pluginId: "acme-crm",
    pluginNodeKey: "createContact",
  }, []);

  try {
    await expect(page.getByTestId("plugin-node-status")).toHaveText(
      "No plugins are installed on this instance.",
    );
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("shows when a plugin node is not bound to a package", async ({ page }) => {
  const workflowId = await openWithPlugins(page, {}, [pluginFixture]);

  try {
    await expect(page.getByTestId("plugin-node-status")).toHaveText(
      "This node is not bound to a plugin package.",
    );
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("falls back to the first action node without a plugin node key", async ({ page }) => {
  const workflowId = await openWithPlugins(page, {
    pluginId: "acme-crm",
  }, [pluginFixture]);

  try {
    await expect(pluginFieldLabel(page, "Email", true)).toBeVisible();
    await expect(page.getByTestId("plugin-node-status")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("shows missing and disabled plugin states", async ({ page }) => {
  let workflowId = await openWithPlugins(page, {
    pluginId: "missing-plugin",
    pluginNodeKey: "createContact",
  }, [pluginFixture]);

  try {
    await expect(page.getByTestId("plugin-node-status")).toHaveText(
      'Plugin "missing-plugin" is not installed on this instance.',
    );
  } finally {
    await deleteWorkflow(page, workflowId);
  }

  await page.unroute("**/api/plugins");
  workflowId = await openWithPlugins(page, {
    pluginId: "acme-crm",
    pluginNodeKey: "createContact",
  }, [{ ...pluginFixture, enabled: false }]);

  try {
    await expect(page.getByTestId("plugin-node-status")).toHaveText(
      'Plugin "Acme CRM" is installed but disabled.',
    );
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("falls back to the first action node when plugin node key is unavailable", async ({
  page,
}) => {
  const workflowId = await openWithPlugins(page, {
    pluginId: "acme-crm",
    pluginNodeKey: "missingNode",
  }, [pluginFixture]);

  try {
    await expect(pluginFieldLabel(page, "Email", true)).toBeVisible();
    await expect(page.getByTestId("plugin-node-status")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("shows when fallback cannot find a matching plugin node kind", async ({ page }) => {
  const triggerOnlyPlugin: PluginSummaryFixture = {
    ...pluginFixture,
    nodes: [
      {
        key: "pollInbox",
        name: "Poll Inbox",
        kind: "trigger",
        description: "Poll an inbox",
        fields: [{ key: "folder", label: "Folder", type: "string" }],
      },
    ],
  };
  const workflowId = await openWithPlugins(page, {
    pluginId: "acme-crm",
  }, [triggerOnlyPlugin]);

  try {
    await expect(page.getByTestId("plugin-node-status")).toHaveText(
      'Plugin "Acme CRM" does not expose any action nodes.',
    );
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});

test("renders fields for a valid plugin node", async ({ page }) => {
  const workflowId = await openWithPlugins(page, {
    pluginId: "acme-crm",
    pluginNodeKey: "createContact",
  }, [pluginFixture]);

  try {
    await expect(pluginFieldLabel(page, "Email", true)).toBeVisible();
    await expect(pluginFieldLabel(page, "Priority")).toBeVisible();
    await expect(page.getByTestId("plugin-node-status")).toHaveCount(0);
  } finally {
    await deleteWorkflow(page, workflowId);
  }
});
