import { describe, expect, it } from "vitest";

import {
  codeFenceLines,
  hasTaskItems,
  parseMarkdownBlocks,
  removeTaskItemLocal,
  toggleTaskItemLocal,
  updateTaskItemLocal,
} from "./markdownTaskList";

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

describe("Windows line endings", () => {
  // The server (`markdown_task_list.py`) reads these lines as task items and edits them by
  // index; the expected strings below are what its toggle, update and remove return.
  const crlf = "Release\r\n- [ ] Tag\r\n- [x] Notes";

  it("finds task items on CRLF lines at the server's line indexes", () => {
    expect(hasTaskItems("- [ ] Tag\r\n- [x] Notes")).toBe(true);
    const items = parseMarkdownBlocks(crlf).flatMap((block) =>
      block.type === "taskList" ? block.items : [],
    );
    expect(items.map((item) => [item.lineIndex, item.text, item.checked])).toEqual([
      [1, "Tag", false],
      [2, "Notes", true],
    ]);
  });

  it("keeps a task line inside a CRLF code fence as text", () => {
    // FENCE_RE did not match a fence line ending in "\r"; matching without it keeps the
    // fenced line out of the checkboxes.
    const fenced = "```\r\n- [ ] not a task\r\n```\r\n- [ ] Ship";
    const items = parseMarkdownBlocks(fenced).flatMap((block) =>
      block.type === "taskList" ? block.items : [],
    );
    expect(items.map((item) => [item.lineIndex, item.text])).toEqual([[3, "Ship"]]);
  });

  it("edits them as the server does", () => {
    expect(toggleTaskItemLocal(crlf, 1)).toBe("Release\r\n- [x] Tag\r\n- [x] Notes");
    expect(updateTaskItemLocal(crlf, 1, "Tag v2")).toBe("Release\r\n- [ ] Tag v2\n- [x] Notes");
    expect(removeTaskItemLocal(crlf, 1)).toBe("Release\r\n- [x] Notes");
  });
});
