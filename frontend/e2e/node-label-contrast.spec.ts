import { expect, test } from "@playwright/test";

import { contrastRatio } from "./color-contrast";
import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

const nodes = [
  { type: "loop", name: "Loop", label: "responsesLoop" },
  { type: "set", name: "Set", label: "shapeResponse" },
  { type: "chartOutput", name: "Chart Output", label: "colorChanger" },
];

for (const theme of ["dark", "light"]) {
  test(`keeps node type labels readable in the ${theme} theme`, async ({ page }) => {
    await prepareAuthenticatedPage(page);
    await page.addInitScript((value) => localStorage.setItem("theme", value), theme);
    const workflow = await createWorkflow(page, "Node label contrast", nodes.map(({ type, label }, index) => ({
      id: type,
      type,
      position: { x: 0, y: index * 180 },
      data: { label },
    })));

    try {
      await page.goto(`/workflows/${workflow.id}`);
      await expect(page.locator("html")).toHaveClass(theme === "dark" ? /\bdark\b/ : /^(?!.*\bdark\b).*$/);
      await page.getByRole("button", { name: "Properties", exact: true }).click();
      const panel = page.locator(".properties-panel");

      for (const { type, name, label } of nodes) {
        await page.locator(`.vue-flow__node[data-id="${type}"]`).click();
        const heading = panel.getByRole("heading", { name: label, exact: true });
        const typeLabel = heading.locator("..").getByText(name, { exact: true });
        await expect(typeLabel).toBeVisible();
        expect.soft(await contrastRatio(typeLabel), `${theme} ${name} contrast`).toBeGreaterThanOrEqual(4.5);
      }
    } finally {
      await deleteWorkflow(page, workflow.id);
    }
  });
}
