import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

describe("execution span details", () => {
  it("makes only the span output content selectable", async () => {
    const source = await readFile(new URL("./ExecutionSpanDetails.vue", import.meta.url), "utf8");

    expect(source).toContain('<div class="select-text">');
  });

  it("keeps the timeline control available during an active execution", async () => {
    const source = await readFile(new URL("./DebugPanel.vue", import.meta.url), "utf8");
    const timelineButton = source.slice(
      source.lastIndexOf("<Button", source.indexOf('title="Execution timeline"')),
      source.indexOf('title="Execution timeline"'),
    );

    expect(timelineButton).toContain(
      'v-if="isExecuting || executionResult || nodeResults.length > 0"',
    );
    expect(timelineButton).not.toContain("!isExecuting");
  });
});
