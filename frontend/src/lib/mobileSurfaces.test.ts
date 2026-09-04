/**
 * Source-level regression tests for the four mobile workflow editor components.
 *
 * These tests read each component's source file (following the same pattern as
 * NodePanel.test.ts and ExecutionSpanDetails.test.ts in this repository) and
 * assert that:
 *
 *   1. The component imports / calls resolveNodeDisplay() — the shared resolver
 *      that safely handles unknown runtime node types.
 *   2. The previously-unsafe direct NODE_DEFINITIONS[node.type].label /
 *      .description accesses are gone from the components that must not use them.
 *   3. The previously-unsafe direct nodeIcons[node.type] and
 *      nodeIconColorClass[node.type] accesses are gone from components where the
 *      resolver is now responsible for icon / color resolution.
 *
 * These tests intentionally do not mount Vue components or call resolveNodeDisplay()
 * themselves — that is covered by nodeDisplay.test.ts.  The purpose here is to
 * guard against regressions where a future edit re-introduces the unsafe accesses.
 */

import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

// Resolve each component path relative to this test file, matching the
// pattern used by NodePanel.test.ts and ExecutionSpanDetails.test.ts.
const componentUrl = (name: string): URL =>
  new URL(`../components/Canvas/${name}`, import.meta.url);

describe("MobileWorkflowTreeNode.vue", () => {
  it("imports resolveNodeDisplay from the shared resolver", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeNode.vue"), "utf8");
    expect(src).toMatch(
      /import\s*\{[^}]*\bresolveNodeDisplay\b[^}]*\}\s*from\s*"@\/lib\/nodeDisplay"/,
    );
  });

  it("calls resolveNodeDisplay() for icon / color / label resolution", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeNode.vue"), "utf8");
    expect(src).toContain("resolveNodeDisplay(");
  });

  it("does not directly access NODE_DEFINITIONS for node type lookups", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeNode.vue"), "utf8");
    // NODE_DEFINITIONS should not be imported at all — it is no longer needed
    // in this component since resolveNodeDisplay() encapsulates the lookup.
    expect(src).not.toMatch(
      /import\s*\{[^}]*\bNODE_DEFINITIONS\b[^}]*\}\s*from\s*"@\/types\/node"/,
    );
  });

  it("does not directly index nodeIcons by node type", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeNode.vue"), "utf8");
    expect(src).not.toMatch(/\bnodeIcons\s*\[/);
  });

  it("does not directly index nodeIconColorClass by node type", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeNode.vue"), "utf8");
    expect(src).not.toMatch(/\bnodeIconColorClass\s*\[/);
  });
});

describe("MobileWorkflowTreeConnectionSheet.vue", () => {
  it("imports resolveNodeDisplay from the shared resolver", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeConnectionSheet.vue"), "utf8");
    expect(src).toMatch(
      /import\s*\{[^}]*\bresolveNodeDisplay\b[^}]*\}\s*from\s*"@\/lib\/nodeDisplay"/,
    );
  });

  it("calls resolveNodeDisplay() for candidate node display", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeConnectionSheet.vue"), "utf8");
    expect(src).toContain("resolveNodeDisplay(");
  });

  it("does not directly access NODE_DEFINITIONS for node type lookups", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeConnectionSheet.vue"), "utf8");
    expect(src).not.toMatch(
      /import\s*\{[^}]*\bNODE_DEFINITIONS\b[^}]*\}\s*from\s*"@\/types\/node"/,
    );
  });

  it("does not directly index nodeIcons by node type", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeConnectionSheet.vue"), "utf8");
    expect(src).not.toMatch(/\bnodeIcons\s*\[/);
  });

  it("does not directly index nodeIconColorClass by node type", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeConnectionSheet.vue"), "utf8");
    expect(src).not.toMatch(/\bnodeIconColorClass\s*\[/);
  });

  it("does not use NODE_DEFINITIONS to resolve candidate labels", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeConnectionSheet.vue"), "utf8");
    // The old pattern was: NODE_DEFINITIONS[node.type].label or [candidate.type].label
    expect(src).not.toMatch(/NODE_DEFINITIONS\s*\[\s*\w+\.type\s*\]\s*\.\s*label/);
  });
});

describe("MobileWorkflowTreeNodesTab.vue", () => {
  it("imports resolveNodeDisplay from the shared resolver", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeNodesTab.vue"), "utf8");
    expect(src).toMatch(
      /import\s*\{[^}]*\bresolveNodeDisplay\b[^}]*\}\s*from\s*"@\/lib\/nodeDisplay"/,
    );
  });

  it("calls resolveNodeDisplay() for selectedLabel and remove confirmation", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeNodesTab.vue"), "utf8");
    expect(src).toContain("resolveNodeDisplay(");
  });

  it("does not use NODE_DEFINITIONS to look up a runtime node type label", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTreeNodesTab.vue"), "utf8");
    // NODE_DEFINITIONS[nodeType].defaultData is a legitimate safe call (known NodeType
    // from the editor palette) and is allowed to remain.  The unsafe pattern that was
    // removed is indexing by a runtime .type property for label / description.
    expect(src).not.toMatch(/NODE_DEFINITIONS\s*\[\s*\w+\.type\s*\]\s*\.\s*label/);
    expect(src).not.toMatch(/NODE_DEFINITIONS\s*\[\s*\w+\.type\s*\]\s*\.\s*description/);
  });
});

describe("MobileWorkflowTree.vue", () => {
  it("imports resolveNodeDisplay from the shared resolver", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTree.vue"), "utf8");
    expect(src).toMatch(
      /import\s*\{[^}]*\bresolveNodeDisplay\b[^}]*\}\s*from\s*"@\/lib\/nodeDisplay"/,
    );
  });

  it("calls resolveNodeDisplay() for the selected node label", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTree.vue"), "utf8");
    expect(src).toContain("resolveNodeDisplay(");
  });

  it("does not directly access NODE_DEFINITIONS for node type lookups", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTree.vue"), "utf8");
    expect(src).not.toMatch(
      /import\s*\{[^}]*\bNODE_DEFINITIONS\b[^}]*\}\s*from\s*"@\/types\/node"/,
    );
  });

  it("does not use NODE_DEFINITIONS to resolve the selected node label", async () => {
    const src = await readFile(componentUrl("MobileWorkflowTree.vue"), "utf8");
    expect(src).not.toMatch(/NODE_DEFINITIONS\s*\[\s*\w+\.type\s*\]\s*\.\s*label/);
  });
});
