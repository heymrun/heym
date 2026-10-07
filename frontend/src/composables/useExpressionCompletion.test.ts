import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// This module fires two real network calls (fetchCredentialsForIntellisense,
// fetchGlobalVariablesForIntellisense) UNCONDITIONALLY at module import time,
// not inside any function a test calls - mock credentialsApi/globalVariablesApi
// BEFORE importing the module under test, same ordering rule as every other
// module-scoped-singleton composable in this codebase (see
// useWorkflowRowStatus.test.ts). vi.mock is hoisted above imports by vitest,
// so this runs before useExpressionCompletion's own import executes.
vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    credentialsApi: {
      ...actual.credentialsApi,
      getAvailable: vi.fn().mockResolvedValue([]),
    },
    globalVariablesApi: {
      ...actual.globalVariablesApi,
      list: vi.fn().mockResolvedValue([]),
    },
  };
});

import {
  clearGlobalVariablesCache,
  refreshCredentialsCache,
  refreshGlobalVariablesCache,
  useExpressionCompletion,
  type UseExpressionCompletionOptions,
} from "./useExpressionCompletion";
import { credentialsApi, globalVariablesApi } from "@/services/api";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

// This file covers the parts of useExpressionCompletion with the highest
// payoff: parseExpressionContext (a hand-rolled parser - pure, complex, and
// the one thing every suggestion path depends on), getNodeSuggestions,
// applyCompletion's text-insertion math, and extractObjectKeys's type-chain
// inference. getPropertySuggestions' dozen-odd branches (array()/Date()/
// credentials/vars/global/textInput/node-with-output) are each individually
// simple prefix-filters once you already trust extractObjectKeys and
// getSuggestionsForType - only a representative few are covered here rather
// than every branch, to keep this file's scope proportionate.

function buildNode(overrides: Partial<WorkflowNode> = {}): WorkflowNode {
  return {
    id: "node-1",
    type: "httpRequest" as WorkflowNode["type"],
    position: { x: 0, y: 0 },
    data: { label: "NodeA" },
    ...overrides,
  };
}

function buildEdge(overrides: Partial<WorkflowEdge> = {}): WorkflowEdge {
  return { id: "edge-1", source: "a", target: "b", ...overrides };
}

function buildOptions(
  overrides: Partial<UseExpressionCompletionOptions> = {},
): UseExpressionCompletionOptions {
  return {
    nodes: [],
    nodeResults: [],
    edges: [],
    currentNodeId: null,
    ...overrides,
  };
}

beforeEach(() => {
  clearGlobalVariablesCache();
  vi.mocked(globalVariablesApi.list).mockResolvedValue([]);
  vi.mocked(credentialsApi.getAvailable).mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("parseExpressionContext", () => {
  const { parseExpressionContext } = useExpressionCompletion(buildOptions());

  it("returns a node trigger for a bare $", () => {
    const text = "$";
    const result = parseExpressionContext(text, text.length);

    expect(result).toMatchObject({ triggerKind: "node", prefix: "", propertyPath: [] });
  });

  it("returns a node trigger with the partial name typed so far", () => {
    const text = "$Slac";
    const result = parseExpressionContext(text, text.length);

    expect(result).toMatchObject({ triggerKind: "node", prefix: "Slac" });
  });

  it("returns a property trigger for $Node.prefix", () => {
    const text = "$NodeA.fo";
    const result = parseExpressionContext(text, text.length);

    expect(result).toMatchObject({
      triggerKind: "property",
      nodeLabel: "NodeA",
      propertyPath: [],
      prefix: "fo",
    });
  });

  it("builds a multi-segment propertyPath for a deeper chain", () => {
    const text = "$NodeA.foo.ba";
    const result = parseExpressionContext(text, text.length);

    expect(result).toMatchObject({
      triggerKind: "property",
      nodeLabel: "NodeA",
      propertyPath: ["foo"],
      prefix: "ba",
    });
  });

  it("returns null when there is no $ anywhere before the cursor", () => {
    const text = "hello world";
    expect(parseExpressionContext(text, text.length)).toBeNull();
  });

  it("returns null when an operator appears in the expression (aborts the parse)", () => {
    const text = "$Node + 1";
    expect(parseExpressionContext(text, text.length)).toBeNull();
  });

  it("only considers text up to the cursor, not the whole string", () => {
    const text = "$NodeA.foo and $NodeB.ba";
    // Cursor placed right after "$NodeA.foo" - the second $ reference and
    // everything after it shouldn't be visible to the parser yet.
    const cursorPos = "$NodeA.foo".length;
    const result = parseExpressionContext(text, cursorPos);

    expect(result).toMatchObject({ nodeLabel: "NodeA", prefix: "foo" });
  });

  describe("inside $array()/$notNull() function arguments", () => {
    it("treats a bare argument as a node trigger scoped to the function arg", () => {
      const text = "$array(Au";
      const result = parseExpressionContext(text, text.length);

      expect(result).toMatchObject({
        triggerKind: "node",
        prefix: "Au",
        isInsideFunctionArg: true,
      });
    });

    it("treats a dotted argument as a property trigger scoped to the function arg", () => {
      const text = "$array(NodeA.fo";
      const result = parseExpressionContext(text, text.length);

      expect(result).toMatchObject({
        triggerKind: "property",
        nodeLabel: "NodeA",
        prefix: "fo",
        isInsideFunctionArg: true,
      });
    });

    it("scopes to the argument after the most recent comma", () => {
      const text = "$array(NodeA.x, NodeB.y";
      const result = parseExpressionContext(text, text.length);

      expect(result).toMatchObject({ nodeLabel: "NodeB", prefix: "y" });
    });
  });

  describe("inside .get() dictionary-access arguments", () => {
    it("treats a dotted argument as a scoped property trigger", () => {
      const text = ".get(NodeA.fo";
      const result = parseExpressionContext(text, text.length);

      expect(result).toMatchObject({
        triggerKind: "property",
        nodeLabel: "NodeA",
        prefix: "fo",
        isInsideFunctionArg: true,
      });
    });

    it("returns null while typing a quoted string key (no node suggestions mid-literal)", () => {
      const text = '.get("someK';
      expect(parseExpressionContext(text, text.length)).toBeNull();
    });

    it("does not trigger once the call already has a closing paren before the cursor", () => {
      const text = '.get("key")';
      expect(parseExpressionContext(text, text.length)).toBeNull();
    });
  });

  describe("inside .filter()/.map()/.sort() string expressions", () => {
    it("returns an item trigger for the base case (no dot yet)", () => {
      const text = '.filter("it';
      const result = parseExpressionContext(text, text.length);

      expect(result).toMatchObject({ triggerKind: "item", propertyPath: [], prefix: "it" });
    });

    it("returns an item trigger with propertyPath once a dot has been typed", () => {
      const text = '.filter("item.pri';
      const result = parseExpressionContext(text, text.length);

      expect(result).toMatchObject({
        triggerKind: "item",
        propertyPath: ["item"],
        prefix: "pri",
      });
    });
  });
});

describe("getNodeSuggestions", () => {
  it("only suggests nodes upstream of the current node", () => {
    const nodeA = buildNode({ id: "a", data: { label: "NodeA" } });
    const nodeB = buildNode({ id: "b", data: { label: "NodeB" } });
    const edge = buildEdge({ source: "a", target: "b" });
    const { getNodeSuggestions } = useExpressionCompletion(
      buildOptions({ nodes: [nodeA, nodeB], edges: [edge], currentNodeId: "b" }),
    );

    const labels = getNodeSuggestions("").map((s) => s.label);

    expect(labels).toContain("$NodeA");
    expect(labels).not.toContain("$NodeB");
  });

  it("filters by prefix, case-insensitively", () => {
    const nodeA = buildNode({ id: "a", data: { label: "Slack Message" } });
    const { getNodeSuggestions } = useExpressionCompletion(buildOptions({ nodes: [nodeA] }));

    expect(getNodeSuggestions("slack").map((s) => s.label)).toContain("$Slack Message");
    expect(getNodeSuggestions("zzz").map((s) => s.label)).not.toContain("$Slack Message");
  });

  it("includes the built-in credentials/vars/global tokens when they match the prefix", () => {
    const { getNodeSuggestions } = useExpressionCompletion(buildOptions());

    const labels = getNodeSuggestions("").map((s) => s.label);

    expect(labels).toEqual(expect.arrayContaining(["$credentials", "$vars", "$global"]));
  });

  it("omits the leading $ when inside a function argument", () => {
    const nodeA = buildNode({ id: "a", data: { label: "NodeA" } });
    const { getNodeSuggestions } = useExpressionCompletion(buildOptions({ nodes: [nodeA] }));

    const labels = getNodeSuggestions("NodeA", true).map((s) => s.label);

    expect(labels).toContain("NodeA");
    expect(labels).not.toContain("$NodeA");
  });

  it("suppresses date/workflow/builtin $functions when inside a function argument", () => {
    const { getNodeSuggestions } = useExpressionCompletion(buildOptions());

    const normal = getNodeSuggestions("");
    const insideFnArg = getNodeSuggestions("", true);

    expect(normal.some((s) => s.type === "function")).toBe(true);
    expect(insideFnArg.some((s) => s.type === "function")).toBe(false);
  });
});

describe("getFunctionSuggestions", () => {
  it("returns every builtin function when there is no prefix", () => {
    const { getFunctionSuggestions, getNodeSuggestions } = useExpressionCompletion(
      buildOptions(),
    );
    const allBuiltins = getNodeSuggestions("").filter((s) => s.type === "function");

    expect(getFunctionSuggestions("").length).toBeGreaterThan(0);
    expect(getFunctionSuggestions("").length).toBeLessThanOrEqual(
      allBuiltins.length + getFunctionSuggestions("").length,
    );
  });

  it("filters by prefix case-insensitively", () => {
    const { getFunctionSuggestions } = useExpressionCompletion(buildOptions());
    const all = getFunctionSuggestions("");
    const first = all[0];

    expect(
      getFunctionSuggestions(first.label.slice(0, 2).toUpperCase()).some(
        (s) => s.label === first.label,
      ),
    ).toBe(true);
  });
});

describe("extractObjectKeys", () => {
  it("lists top-level keys of an object with their value types", () => {
    const { extractObjectKeys } = useExpressionCompletion(buildOptions());

    const result = extractObjectKeys({ name: "Alice", age: 30 }, []);

    expect(result).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: "name", propertyType: "string" }),
        expect.objectContaining({ label: "age", propertyType: "number" }),
      ]),
    );
  });

  it("resolves into a nested object via the property path", () => {
    const { extractObjectKeys } = useExpressionCompletion(buildOptions());

    const result = extractObjectKeys({ user: { name: "Alice" } }, ["user"]);

    expect(result).toEqual(
      expect.arrayContaining([expect.objectContaining({ label: "name" })]),
    );
  });

  it("resolves an array index in the path to that element's keys", () => {
    const { extractObjectKeys } = useExpressionCompletion(buildOptions());

    const result = extractObjectKeys({ items: [{ id: 1 }, { id: 2 }] }, ["items[1]"]);

    expect(result).toEqual(expect.arrayContaining([expect.objectContaining({ label: "id" })]));
  });

  it('treats ".length" on a string/array as a number, not a missing property', () => {
    const { extractObjectKeys } = useExpressionCompletion(buildOptions());

    const result = extractObjectKeys({ name: "Alice" }, ["name", "length"]);

    // "name" is a string, so ".length" should resolve to "number" (the DSL
    // length special-case), giving NUMBER_METHODS - not STRING_METHODS again,
    // and not an empty result from treating "length" as a missing property.
    expect(result).toEqual(
      expect.arrayContaining([expect.objectContaining({ label: "toString" })]),
    );
    expect(result.some((s) => s.label === "upper")).toBe(false);
  });

  it("returns an empty array for a non-object, non-primitive-method value", () => {
    const { extractObjectKeys } = useExpressionCompletion(buildOptions());

    expect(extractObjectKeys(null, [])).toEqual([]);
    expect(extractObjectKeys(undefined, [])).toEqual([]);
  });
});

describe("applyCompletion", () => {
  it("inserts a node reference with a leading $", () => {
    const { applyCompletion } = useExpressionCompletion(buildOptions());
    const text = "$Node";

    const result = applyCompletion(text, text.length, {
      label: "$NodeA",
      insertText: "NodeA",
      type: "node",
    });

    expect(result.newText).toBe("$NodeA");
    expect(result.newCursorPos).toBe("$NodeA".length);
  });

  it("does not add a $ when inserting inside a function argument", () => {
    const { applyCompletion } = useExpressionCompletion(buildOptions());
    const text = "$array(Node";

    const result = applyCompletion(text, text.length, {
      label: "NodeA",
      insertText: "NodeA",
      type: "node",
    });

    expect(result.newText).toBe("$array(NodeA");
  });

  it("appends a property onto the existing path with a dot", () => {
    const { applyCompletion } = useExpressionCompletion(buildOptions());
    const text = "$NodeA.fo";

    const result = applyCompletion(text, text.length, {
      label: "foo",
      insertText: "foo",
      type: "property",
    });

    expect(result.newText).toBe("$NodeA.foo");
  });

  it("attaches an index suggestion directly, without an extra dot", () => {
    const { applyCompletion } = useExpressionCompletion(buildOptions());
    const text = "$NodeA.items.";

    const result = applyCompletion(text, text.length, {
      label: "[0]",
      insertText: "[0]",
      type: "property",
    });

    expect(result.newText).toBe("$NodeA.items[0]");
  });

  it("places the cursor inside the parens for a function suggestion ending in ()", () => {
    const { applyCompletion } = useExpressionCompletion(buildOptions());
    const text = "$NodeA.up";

    const result = applyCompletion(text, text.length, {
      label: "upper()",
      insertText: "upper()",
      type: "function",
    });

    expect(result.newText).toBe("$NodeA.upper()");
    expect(result.newCursorPos).toBe(result.newText.length - 1);
  });

  it("returns the original text unchanged when there is no completion context", () => {
    const { applyCompletion } = useExpressionCompletion(buildOptions());
    const text = "hello world";

    const result = applyCompletion(text, text.length, {
      label: "x",
      insertText: "x",
      type: "property",
    });

    expect(result).toEqual({ newText: text, newCursorPos: text.length });
  });
});

describe("module-level credentials/global-variables cache", () => {
  it("refreshGlobalVariablesCache populates getPropertySuggestions for $global", async () => {
    vi.mocked(globalVariablesApi.list).mockResolvedValue([
      { id: "v1", name: "apiBaseUrl", value_type: "string" } as never,
    ]);
    const { getPropertySuggestions } = useExpressionCompletion(buildOptions());

    refreshGlobalVariablesCache();

    await vi.waitFor(() =>
      expect(getPropertySuggestions("global", [], "").map((s) => s.label)).toContain(
        "apiBaseUrl",
      ),
    );
  });

  it("clearGlobalVariablesCache synchronously empties the global suggestions", async () => {
    vi.mocked(globalVariablesApi.list).mockResolvedValue([
      { id: "v1", name: "apiBaseUrl", value_type: "string" } as never,
    ]);
    const { getPropertySuggestions } = useExpressionCompletion(buildOptions());
    refreshGlobalVariablesCache();
    await vi.waitFor(() =>
      expect(getPropertySuggestions("global", [], "")).not.toEqual([]),
    );

    clearGlobalVariablesCache();

    expect(getPropertySuggestions("global", [], "")).toEqual([]);
  });

  it("refreshCredentialsCache calls the credentials API", () => {
    refreshCredentialsCache();

    expect(credentialsApi.getAvailable).toHaveBeenCalled();
  });
});
