import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { getAllDocItems, getDocPath } from "@/docs/manifest";
import { parsePaletteQuery, rankByPaletteScore } from "@/lib/paletteSearch";

describe("Kubernetes documentation", () => {
  it("includes the complete deployment README in the bundled docs", () => {
    const article = readFileSync(
      new URL("./content/getting-started/kubernetes.md", import.meta.url),
      "utf8",
    );
    const readme = readFileSync(
      new URL("../../../deploy/kubernetes/README.md", import.meta.url),
      "utf8",
    );

    expect(article).toContain(readme.slice(readme.indexOf("\n\n") + 2));
  });

  it.each(["kubernetes", "kubernetes docs", "docs kubernetes"])(
    "finds the deployment page in the command palette for %s",
    (query) => {
      const { terms } = parsePaletteQuery(query);
      const results = rankByPaletteScore(getAllDocItems(), terms, (item) => ({
        label: item.title,
        others: [item.slug, item.categoryLabel],
      }));

      expect(results[0]?.title).toBe("Kubernetes Deployment");
      expect(getDocPath(results[0]!.categoryId, results[0]!.slug)).toBe(
        "/docs/getting-started/kubernetes",
      );
    },
  );
});
