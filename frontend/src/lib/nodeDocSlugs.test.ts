import { describe, expect, it } from "vitest";

import { NODE_DOC_SLUGS } from "@/lib/nodeDocSlugs";

const NODE_DOC_PAGES = Object.keys(import.meta.glob("../docs/content/nodes/*.md"));

describe("NODE_DOC_SLUGS", () => {
  it("points every node type at a docs page that exists", () => {
    const pages = new Set(NODE_DOC_PAGES.map((path) => path.split("/").pop()?.replace(/\.md$/, "")));

    for (const [nodeType, slug] of Object.entries(NODE_DOC_SLUGS)) {
      expect(pages.has(slug), `${nodeType} -> ${slug}`).toBe(true);
    }
  });

  it("uses plain lowercase slugs the backend accepts", () => {
    for (const slug of Object.values(NODE_DOC_SLUGS)) {
      expect(slug).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    }
  });
});
