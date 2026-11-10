import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { getAllDocItems, getDocPath, getPrevNextDoc } from "@/docs/manifest";
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

describe("incident documentation discovery", () => {
  it.each([
    ["incident playbook", "Incident Playbook (L0)", "incident-playbook"],
    ["operations runbook", "Operations Runbook (L1)", "operations-runbook"],
  ])("finds %s from the command palette", (query, title, slug) => {
    const { terms } = parsePaletteQuery(query);
    const results = rankByPaletteScore(getAllDocItems(), terms, (item) => ({
      label: item.title,
      others: [item.slug, item.categoryLabel],
    }));
    expect(results[0]?.title).toBe(title);
    expect(getDocPath(results[0]!.categoryId, results[0]!.slug)).toBe(`/docs/reference/${slug}`);
  });

  it("keeps the playbook and runbook next to each other for article navigation", () => {
    expect(getPrevNextDoc("reference/incident-playbook").next?.path)
      .toBe("/docs/reference/operations-runbook");
    expect(getPrevNextDoc("reference/operations-runbook").prev?.path)
      .toBe("/docs/reference/incident-playbook");
  });
});
