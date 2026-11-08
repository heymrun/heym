import { createSSRApp, h, type Component } from "vue";
import { describe, expect, it, vi } from "vitest";
import { renderToString } from "vue/server-renderer";

import KeyRotationTab from "@/components/Layout/settings/KeyRotationTab.vue";

vi.mock("@/services/keyRotation", () => ({
  getKeyRotation: vi.fn(),
  startKeyRotation: vi.fn(),
}));

async function renderTab(): Promise<string> {
  const app = createSSRApp({
    render: () => h(KeyRotationTab as Component),
  });
  return renderToString(app);
}

function getSteps(html: string): string[] {
  return (html.match(/<li[^>]*>[\s\S]*?<\/li>/g) ?? []).map((item) =>
    item
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim(),
  );
}

describe("KeyRotationTab steps", () => {
  it("explains the rotation as four numbered steps", async () => {
    const html = await renderTab();
    expect(html).toContain("<ol");
    expect(html).toContain("list-decimal");

    const steps = getSteps(html);
    expect(steps).toHaveLength(4);
    expect(steps[0]).toMatch(/^Introduce\./);
    expect(steps[1]).toMatch(/^Promote\./);
    expect(steps[2]).toMatch(/^Re-encrypt\./);
    expect(steps[3]).toMatch(/^Retire\./);
  });

  it("names the two environment variables the steps change", async () => {
    const steps = getSteps(await renderTab()).join(" ");
    expect(steps).toContain("ENCRYPTION_KEYS_EXTRA");
    expect(steps).toContain("ENCRYPTION_KEY");
  });
});
