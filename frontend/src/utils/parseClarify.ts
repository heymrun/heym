import { jsonrepair } from "jsonrepair";

import type {
  ClarifyAnswer,
  ClarifyPayload,
  ClarifyQuestion,
} from "@/types/clarify";

const FENCE = "```heym-clarify";

function isValidQuestion(q: unknown): q is ClarifyQuestion {
  if (!q || typeof q !== "object") return false;
  const obj = q as Record<string, unknown>;
  const validType =
    obj.type === "single" || obj.type === "multi" || obj.type === "text";
  return (
    typeof obj.id === "string" &&
    typeof obj.text === "string" &&
    validType &&
    (obj.options === undefined || Array.isArray(obj.options)) &&
    (obj.allowOther === undefined || typeof obj.allowOther === "boolean")
  );
}

function validate(parsed: unknown): ClarifyQuestion[] | null {
  if (!parsed || typeof parsed !== "object") return null;
  const questions = (parsed as { questions?: unknown }).questions;
  if (!Array.isArray(questions) || questions.length === 0) return null;
  if (!questions.every(isValidQuestion)) return null;
  return questions.map((q) => ({
    id: q.id,
    text: q.text,
    type: q.type,
    options: q.options,
    allowOther: q.allowOther,
  }));
}

function bodyBetweenFences(content: string): string | null {
  const start = content.indexOf(FENCE);
  if (start === -1) return null;
  const afterFence = content.slice(start + FENCE.length);
  const firstNewline = afterFence.search(/\n/);
  const bodyStart = firstNewline >= 0 ? firstNewline + 1 : 0;
  const rest = afterFence.slice(bodyStart);
  const closeIdx = rest.indexOf("```");
  return closeIdx >= 0 ? rest.slice(0, closeIdx).trim() : rest.trim();
}

export function extractClarifyBlock(content: string): ClarifyQuestion[] | null {
  const raw = bodyBetweenFences(content);
  if (!raw) return null;
  try {
    return validate(JSON.parse(raw) as ClarifyPayload);
  } catch {
    try {
      return validate(JSON.parse(jsonrepair(raw)) as ClarifyPayload);
    } catch {
      return null;
    }
  }
}

// Remove the raw clarify fence from text so it is not shown as a code block;
// the ClarifyCard renders the questions instead.
export function stripClarifyBlock(content: string): string {
  const start = content.indexOf(FENCE);
  if (start === -1) return content;
  const afterFence = content.slice(start + FENCE.length);
  const firstNewline = afterFence.search(/\n/);
  const bodyStart = firstNewline >= 0 ? firstNewline + 1 : 0;
  const rest = afterFence.slice(bodyStart);
  const closeIdx = rest.indexOf("```");
  const tail = closeIdx >= 0 ? rest.slice(closeIdx + 3) : "";
  return (content.slice(0, start) + tail).trim();
}

export function serializeAnswers(
  questions: ClarifyQuestion[],
  answers: ClarifyAnswer[],
): string {
  const byId = new Map(answers.map((a) => [a.id, a]));
  const lines = questions.map((q) => {
    const a = byId.get(q.id);
    const parts: string[] = [];
    if (a) {
      if (a.selected.length > 0) parts.push(...a.selected);
      if (a.other.trim()) parts.push(`Other: "${a.other.trim()}"`);
    }
    const value = parts.length > 0 ? parts.join(", ") : "(no answer)";
    return `- ${q.text} → ${value}`;
  });
  return ["[Plan answers]", ...lines].join("\n");
}
