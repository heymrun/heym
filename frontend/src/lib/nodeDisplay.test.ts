import { describe, expect, it } from "vitest";

import { LayoutTemplate } from "lucide-vue-next";

import { nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";

import { resolveNodeDisplay } from "./nodeDisplay";

describe("resolveNodeDisplay", () => {
  describe("known node types", () => {
    it("preserves label and summary from node data", () => {
      expect(resolveNodeDisplay("llm", { label: "Summarize", model: "gpt-4o" })).toMatchObject({
        label: "Summarize",
        typeLabel: "LLM",
        summary: "gpt-4o",
        icon: nodeIcons.llm,
        iconColorClass: nodeIconColorClass.llm,
        tileFilling: false,
      });
    });

    it("uses definition label when node data label is empty", () => {
      const display = resolveNodeDisplay("llm", { label: "", model: "gpt-4o" });
      expect(display.label).toBe("LLM");
      expect(display.typeLabel).toBe("LLM");
      expect(display.summary).toBe("gpt-4o");
    });

    it("preserves tile-filling behavior for branded nodes", () => {
      expect(resolveNodeDisplay("heym", {}).tileFilling).toBe(true);
      expect(resolveNodeDisplay("llm", {}).tileFilling).toBe(false);
    });

    it("returns definition icon and color for known types", () => {
      const display = resolveNodeDisplay("slack", {});
      expect(display.icon).toBe(nodeIcons.slack);
      expect(display.iconColorClass).toBe(nodeIconColorClass.slack);
      expect(display.typeLabel).toBe("Slack");
    });
  });

  describe("unknown node types", () => {
    it("does not throw when node type is not in NODE_DEFINITIONS", () => {
      expect(() => resolveNodeDisplay("unknownNodeType", {})).not.toThrow();
    });

    it("returns humanized type as label and typeLabel for unknown nodes", () => {
      const display = resolveNodeDisplay("deletedNode", {});
      expect(display.label).toBe("Deleted Node");
      expect(display.typeLabel).toBe("Deleted Node");
    });

    it("returns humanized type as summary when no specific data is available", () => {
      const display = resolveNodeDisplay("legacyCustomNode", {});
      expect(display.summary).toBe("Unsupported node type: Legacy Custom Node");
    });

    it("preserves custom label for unknown node types while keeping humanized typeLabel", () => {
      const display = resolveNodeDisplay("unknownType", { label: "My custom node" });
      expect(display.label).toBe("My custom node");
      expect(display.typeLabel).toBe("Unknown Type");
    });

    it("extracts operation data for unknown integration-like types", () => {
      const display = resolveNodeDisplay("legacyIntegration", { legacyOperation: "archive" });
      expect(display.summary).toBe("archive");
    });

    it("uses LayoutTemplate icon for unknown node types", () => {
      const display = resolveNodeDisplay("unknownType", {});
      expect(display.icon).toBe(LayoutTemplate);
    });

    it("uses muted foreground color for unknown node types", () => {
      const display = resolveNodeDisplay("unknownType", {});
      expect(display.iconColorClass).toBe("text-muted-foreground");
    });

    it("disables tile-filling for unknown node types", () => {
      const display = resolveNodeDisplay("unknownBrandNode", {});
      expect(display.tileFilling).toBe(false);
    });

    it("preserves stale node label and metadata", () => {
      expect(resolveNodeDisplay("legacyNode", { label: "Legacy step", url: "https://example.com" })).toMatchObject({
        label: "Legacy step",
        summary: "https://example.com",
        icon: LayoutTemplate,
        iconColorClass: "text-muted-foreground",
        tileFilling: false,
      });
    });
  });

  describe("edge cases", () => {
    it("handles empty label gracefully", () => {
      const display = resolveNodeDisplay("unknownType", { label: "" });
      expect(display.label).toBe("Unknown Type");
    });

    it("handles whitespace-only label gracefully", () => {
      const display = resolveNodeDisplay("unknownType", { label: "   " });
      expect(display.label).toBe("Unknown Type");
    });

    it("ignores non-string data when resolving summary", () => {
      const display = resolveNodeDisplay("unknownType", { model: 123, url: null });
      expect(display.summary).toContain("Unsupported node type");
    });
  });
});
