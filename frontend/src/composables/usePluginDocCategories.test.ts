import { describe, expect, it } from "vitest";

import { getAllDocItems } from "@/docs/manifest";
import { buildPluginDocCategories } from "@/composables/usePluginDocCategories";

describe("plugin doc categories", () => {
  it("adds installed plugins as a searchable docs category", () => {
    const categories = buildPluginDocCategories([
      {
        id: "acme-crm",
        name: "Acme CRM",
        version: "1.0.0",
        kind: "package",
        description: "CRM actions",
        enabled: true,
        nodes: [],
      },
      {
        id: "disabled-plugin",
        name: "Disabled Plugin",
        version: "1.0.0",
        kind: "package",
        description: "Disabled actions",
        enabled: false,
        nodes: [],
      },
    ]);

    expect(categories.plugins?.items).toEqual([
      { slug: "acme-crm", title: "Acme CRM" },
      { slug: "disabled-plugin", title: "Disabled Plugin" },
    ]);
    expect(getAllDocItems(categories)).toContainEqual({
      categoryId: "plugins",
      categoryLabel: "Plugins",
      slug: "acme-crm",
      title: "Acme CRM",
    });
  });
});
