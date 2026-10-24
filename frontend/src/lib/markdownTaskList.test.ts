import { describe, expect, it } from "vitest";

import { codeFenceLines, hasTaskItems, parseMarkdownBlocks } from "./markdownTaskList";

describe("markdown task lists and fenced code", () => {
  it("does not treat task syntax in a code block as checkboxes", () => {
    expect(hasTaskItems("Example:\n```markdown\n- [ ] not a checkbox\n```")).toBe(false);
  });

  it("keeps a code block in one html block around real task items", () => {
    const md = "- [ ] real\n\n```md\n- [ ] in code\n```\n\n- [x] real too";
    const blocks = parseMarkdownBlocks(md);
    const tasks = blocks.flatMap((b) => (b.type === "taskList" ? b.items : []));
    expect(tasks.map((t) => t.lineIndex)).toEqual([0, 6]);
    const html = blocks.filter((b) => b.type === "html").map((b) => b.content);
    expect(html.some((content) => content.includes("```md\n- [ ] in code\n```"))).toBe(true);
  });

  it("follows fence length and character", () => {
    const lines = "````\n```\n- [ ] q\n```\n````\n~~~\n```\n~~~\n- [ ] after".split("\n");
    expect([...codeFenceLines(lines)]).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
  });

  it("still finds plain task items", () => {
    expect(hasTaskItems("- [ ] todo\n* [x] done")).toBe(true);
  });
});
