const TASK_ITEM_RE = /^(\s*)([-*+])\s+\[([ xX])\]\s+(.*)$/;
const FENCE_RE = /^ {0,3}(`{3,}|~{3,})(.*)$/;

/**
 * Indexes of the lines inside fenced code blocks (fences included): a `- [ ] item`
 * line in a code sample is text, not a checkbox. Same rules as the backend's
 * `code_fence_lines`: a fence closes at a fence of the same character that is at
 * least as long and has nothing after it.
 */
export function codeFenceLines(lines: string[]): Set<number> {
  const inside = new Set<number>();
  let opening: { char: string; length: number } | null = null;
  lines.forEach((line, index) => {
    const match = FENCE_RE.exec(line);
    const fence = match?.[1] ?? "";
    const rest = match?.[2] ?? "";
    if (opening === null) {
      if (match && !(fence[0] === "`" && rest.includes("`"))) {
        opening = { char: fence[0] ?? "`", length: fence.length };
        inside.add(index);
      }
      return;
    }
    inside.add(index);
    if (fence && fence[0] === opening.char && fence.length >= opening.length && rest.trim() === "") {
      opening = null;
    }
  });
  return inside;
}

export interface TaskListItem {
  lineIndex: number;
  checked: boolean;
  text: string;
}

export type MarkdownBlock =
  | { type: "html"; content: string }
  | { type: "taskList"; items: TaskListItem[] };

export function hasTaskItems(markdown: string): boolean {
  const lines = markdown.split("\n");
  const code = codeFenceLines(lines);
  return lines.some((line, index) => !code.has(index) && TASK_ITEM_RE.test(line));
}

export function parseMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const lines = markdown.split("\n");
  const code = codeFenceLines(lines);
  const blocks: MarkdownBlock[] = [];
  let htmlLines: string[] = [];
  let taskItems: TaskListItem[] = [];

  const flushHtml = (): void => {
    if (htmlLines.length > 0) {
      blocks.push({ type: "html", content: htmlLines.join("\n") });
      htmlLines = [];
    }
  };

  const flushTaskList = (): void => {
    if (taskItems.length > 0) {
      blocks.push({ type: "taskList", items: [...taskItems] });
      taskItems = [];
    }
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    const match = code.has(index) ? null : TASK_ITEM_RE.exec(line);
    if (match) {
      flushHtml();
      taskItems.push({
        lineIndex: index,
        checked: match[3]?.toLowerCase() === "x",
        text: match[4] ?? "",
      });
      continue;
    }
    if (line.trim() === "" && taskItems.length > 0) {
      flushTaskList();
      htmlLines.push(line);
      continue;
    }
    flushTaskList();
    htmlLines.push(line);
  }

  flushHtml();
  flushTaskList();
  return blocks;
}

export function toggleTaskItemLocal(markdown: string, lineIndex: number): string {
  const lines = markdown.split("\n");
  const line = lines[lineIndex];
  if (line === undefined) {
    throw new Error(`Invalid line_index: ${lineIndex}`);
  }
  const match = TASK_ITEM_RE.exec(line);
  if (!match) {
    throw new Error(`Line ${lineIndex} is not a task list item`);
  }
  const indent = match[1] ?? "";
  const bullet = match[2] ?? "-";
  const check = match[3] ?? " ";
  const rest = match[4] ?? "";
  const newCheck = check.toLowerCase() === "x" ? " " : "x";
  lines[lineIndex] = `${indent}${bullet} [${newCheck}] ${rest}`;
  return lines.join("\n");
}

export function updateTaskItemLocal(markdown: string, lineIndex: number, text: string): string {
  const lines = markdown.split("\n");
  const line = lines[lineIndex];
  if (line === undefined) {
    throw new Error(`Invalid line_index: ${lineIndex}`);
  }
  const match = TASK_ITEM_RE.exec(line);
  if (!match) {
    throw new Error(`Line ${lineIndex} is not a task list item`);
  }
  const indent = match[1] ?? "";
  const bullet = match[2] ?? "-";
  const check = match[3] ?? " ";
  lines[lineIndex] = `${indent}${bullet} [${check}] ${text}`;
  return lines.join("\n");
}

export function removeTaskItemLocal(markdown: string, lineIndex: number): string {
  const lines = markdown.split("\n");
  const line = lines[lineIndex];
  if (line === undefined) {
    throw new Error(`Invalid line_index: ${lineIndex}`);
  }
  if (!TASK_ITEM_RE.test(line)) {
    throw new Error(`Line ${lineIndex} is not a task list item`);
  }
  lines.splice(lineIndex, 1);
  if (
    lineIndex < lines.length
    && (lines[lineIndex] ?? "").trim() === ""
    && lineIndex > 0
    && (lines[lineIndex - 1] ?? "").trim() === ""
  ) {
    lines.splice(lineIndex, 1);
  }
  return lines.join("\n");
}

export function updateOrRemoveTaskItemLocal(
  markdown: string,
  lineIndex: number,
  text: string,
): string {
  if (text.trim() === "") {
    return removeTaskItemLocal(markdown, lineIndex);
  }
  return updateTaskItemLocal(markdown, lineIndex, text);
}
