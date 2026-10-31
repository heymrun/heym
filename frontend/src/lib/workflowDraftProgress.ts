/**
 * The progress line for a workflow DSL still being written, such as the AI Builder's reply:
 * `Writing "Lead intake" · 3 nodes (start, Agent, result)`. Mirrors the backend's
 * `workflow_draft_message` (backend/app/services/chat_progress.py) so Chat and the canvas agree.
 */

const SHOWN_NODE_LABELS = 3;
const NAME_PATTERN = /"name"\s*:\s*"((?:[^"\\]|\\.)*)"/;

/** The JSON string opening at `start` and the index after it; null while it is unfinished. */
function readString(text: string, start: number): [string | null, number] {
  let index = start + 1;
  while (index < text.length) {
    const char = text[index];
    if (char === "\\") {
      index += 2;
      continue;
    }
    if (char === '"') {
      try {
        return [JSON.parse(text.slice(start, index + 1)) as string, index + 1];
      } catch {
        return [null, index + 1];
      }
    }
    index += 1;
  }
  return [null, text.length];
}

function workflowName(text: string): string | null {
  const match = NAME_PATTERN.exec(text);
  if (!match) return null;
  try {
    return (JSON.parse(`"${match[1]}"`) as string) || null;
  } catch {
    return null;
  }
}

/** One entry per node object written so far, with its label once that string is complete. */
function nodeLabels(text: string): Array<string | null> {
  const marker = text.indexOf('"nodes"');
  if (marker < 0) return [];
  const start = text.indexOf("[", marker);
  if (start < 0) return [];
  const labels: Array<string | null> = [];
  let depth = 0;
  let index = start + 1;
  let awaitingLabel = false;
  while (index < text.length) {
    const char = text[index];
    if (char === '"') {
      const [value, end] = readString(text, index);
      if (value === null) break;
      if (text.slice(end, end + 3).trimStart().startsWith(":")) {
        // A node's label sits in its `data` object, one level below the node.
        awaitingLabel = value === "label" && depth === 2 && labels[labels.length - 1] === null;
      } else if (awaitingLabel) {
        labels[labels.length - 1] = value;
        awaitingLabel = false;
      }
      index = end;
      continue;
    }
    if (char === "{" || char === "[") {
      if (char === "{" && depth === 0) labels.push(null);
      depth += 1;
    } else if (char === "}" || char === "]") {
      depth -= 1;
      if (depth < 0) break;
    }
    index += 1;
  }
  return labels;
}

export function workflowDraftMessage(text: string): string {
  const nodesAt = text.indexOf('"nodes"');
  const name = workflowName(nodesAt >= 0 ? text.slice(0, nodesAt) : text);
  const subject = name ? `"${name}"` : "the workflow";
  const labels = nodeLabels(text);
  if (labels.length === 0) return `Writing ${subject}`;
  const count = `${labels.length} node${labels.length === 1 ? "" : "s"}`;
  const named = labels.filter((label): label is string => Boolean(label));
  if (named.length === 0) return `Writing ${subject} · ${count}`;
  let shown = named.slice(-SHOWN_NODE_LABELS).join(", ");
  if (named.length > SHOWN_NODE_LABELS) shown = `…, ${shown}`;
  return `Writing ${subject} · ${count} (${shown})`;
}

/** The line for a streaming assistant reply, once it has started a workflow JSON block. */
export function streamingWorkflowProgress(content: string): string | null {
  const fence = content.indexOf("```json");
  if (fence < 0) return null;
  return workflowDraftMessage(content.slice(fence));
}
