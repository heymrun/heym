import { describe, expect, it } from "vitest";

import {
  paletteScore,
  parsePaletteQuery,
  rankByPaletteScore,
  termScore,
  unscopedQuery,
} from "@/lib/paletteSearch";

describe("parsePaletteQuery", () => {
  it("reads a group word at the end or the start", () => {
    expect(parsePaletteQuery("mcp tab")).toEqual({ terms: ["mcp"], scope: "tabs" });
    expect(parsePaletteQuery("Tabs  MCP")).toEqual({ terms: ["mcp"], scope: "tabs" });
    expect(parsePaletteQuery("order workflow")).toEqual({ terms: ["order"], scope: "workflows" });
  });

  it("keeps a lone group word as a scope with no terms", () => {
    expect(parsePaletteQuery("tab")).toEqual({ terms: [], scope: "tabs" });
  });

  it("leaves other queries unscoped", () => {
    expect(parsePaletteQuery("eval suite")).toEqual({ terms: ["eval", "suite"], scope: null });
    expect(parsePaletteQuery("  ")).toEqual({ terms: [], scope: null });
    expect(unscopedQuery("doc summarizer")).toEqual({
      terms: ["doc", "summarizer"],
      scope: null,
    });
  });
});

describe("termScore", () => {
  it("ranks exact over prefix over word prefix over contains", () => {
    expect(termScore("evals", "Evals")).toBeGreaterThan(termScore("eval", "Evals"));
    expect(termScore("eval", "Evals")).toBeGreaterThan(termScore("board", "Kanban Board"));
    expect(termScore("board", "Kanban Board")).toBeGreaterThan(termScore("table", "DataTable"));
    expect(termScore("table", "DataTable")).toBeGreaterThan(0);
  });

  it("matches letters in order within a short stretch", () => {
    expect(termScore("crdntl", "Credentials")).toBeGreaterThan(0);
    expect(termScore("vct", "Vectors")).toBeGreaterThan(0);
    expect(termScore("abc", "a long name before b and later c")).toBe(0);
  });

  it("does not match letters spread over several words", () => {
    expect(termScore("mcp", "send test mail (Copy)")).toBe(0);
    expect(termScore("mcp", "translate-to-german (Copy)")).toBe(0);
    expect(termScore("mcp", "Agent skill translate-to-german.")).toBe(0);
    expect(termScore("mcp", "MCP Call Node")).toBeGreaterThan(0);
  });

  it("forgives one typo in a word of four letters or more", () => {
    expect(termScore("evlas", "Evals")).toBeGreaterThan(0);
    expect(termScore("credentails", "Credentials")).toBeGreaterThan(0);
    expect(termScore("anlytics", "Analytics")).toBeGreaterThan(0);
    expect(termScore("tracs", "Traces")).toBeGreaterThan(0);
    expect(termScore("mpc", "MCP")).toBe(0);
  });
});

describe("paletteScore", () => {
  it("needs every term to match", () => {
    expect(paletteScore("Support flow", [], ["support", "flow"])).toBeGreaterThan(0);
    expect(paletteScore("Support flow", [], ["support", "billing"])).toBe(0);
  });

  it("counts other fields at half weight", () => {
    const label = paletteScore("Refunds", ["handles invoices"], ["refunds"]);
    const description = paletteScore("Billing", ["refunds and invoices"], ["refunds"]);
    expect(label).toBeGreaterThan(description);
    expect(description).toBeGreaterThan(0);
  });
});

describe("rankByPaletteScore", () => {
  const tabs = ["Workflows", "Evals", "Traces", "Credentials", "MCP"].map((label) => ({ label }));

  it("finds the Evals tab from a partial word", () => {
    const ranked = rankByPaletteScore(tabs, ["eval"], (tab) => ({ label: tab.label }));
    expect(ranked.map((tab) => tab.label)).toEqual(["Evals"]);
  });

  it("keeps the original order for equal scores and returns all items without terms", () => {
    expect(rankByPaletteScore(tabs, [], (tab) => ({ label: tab.label }))).toBe(tabs);
    const ranked = rankByPaletteScore(tabs, ["s"], (tab) => ({ label: tab.label }));
    expect(ranked.map((tab) => tab.label)).toEqual(["Workflows", "Evals", "Traces", "Credentials"]);
  });
});
