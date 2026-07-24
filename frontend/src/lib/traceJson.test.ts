import { describe, expect, it } from "vitest";

import { getTraceJsonContent, isTraceJsonContent } from "@/lib/traceJson";

describe("trace JSON content", () => {
  it("recognizes object and array payloads", () => {
    expect(isTraceJsonContent({ jsonrpc: "2.0" })).toBe(true);
    expect(isTraceJsonContent([{ type: "mcp.call" }])).toBe(true);
  });

  it("parses JSON-encoded events and nested JSON strings for the tree", () => {
    const raw = JSON.stringify({
      jsonrpc: "2.0",
      result: JSON.stringify({ items: [{ id: 7, metadata: { active: true } }] }),
    });

    const content = getTraceJsonContent(raw);

    expect(content.isJson).toBe(true);
    expect(content.rawText).toBe(raw);
    expect(content.treeValue).toEqual({
      jsonrpc: "2.0",
      result: { items: [{ id: 7, metadata: { active: true } }] },
    });
  });

  it("preserves malformed JSON as plain text", () => {
    const malformed = '{"jsonrpc":"2.0","params": }';

    expect(getTraceJsonContent(malformed)).toEqual({
      isJson: false,
      rawText: malformed,
      treeValue: malformed,
    });
  });

  it("does not treat ordinary text or primitives as JSON trees", () => {
    expect(isTraceJsonContent("MCP request failed")).toBe(false);
    expect(isTraceJsonContent("true")).toBe(false);
    expect(isTraceJsonContent(null)).toBe(false);
  });
});
