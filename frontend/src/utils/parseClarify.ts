import { jsonrepair } from "jsonrepair";

import type {
  ClarifyAnswer,
  ClarifyCredentialEdit,
  ClarifyCredentialRef,
  ClarifyOption,
  ClarifyPayload,
  ClarifyQuestion,
  ClarifyQuestionType,
} from "@/types/clarify";
import type { CredentialType } from "@/types/credential";

import { CREDENTIAL_TYPE_LABELS } from "@/types/credential";

const FENCE = "```heym-clarify";
const MAX_CREDENTIAL_NAME_LENGTH = 100;
const CREDENTIAL_TYPES = new Set<string>(Object.keys(CREDENTIAL_TYPE_LABELS));
const CREDENTIAL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Options arrive as plain strings or `{label, prefill?, create?, edit?}` objects.
interface RawClarifyQuestion {
  id: string;
  text: string;
  type: ClarifyQuestionType;
  options?: unknown[];
  allowOther?: boolean;
  prefillLabel?: string;
  optional?: boolean;
}

function isValidOption(option: unknown): boolean {
  if (!option || typeof option !== "object") return true;
  const obj = option as Record<string, unknown>;
  return (
    typeof obj.label === "string" &&
    (obj.prefill === undefined || typeof obj.prefill === "string")
  );
}

function isValidQuestion(q: unknown): q is RawClarifyQuestion {
  if (!q || typeof q !== "object") return false;
  const obj = q as Record<string, unknown>;
  const validType =
    obj.type === "single" || obj.type === "multi" || obj.type === "text";
  return (
    typeof obj.id === "string" &&
    typeof obj.text === "string" &&
    validType &&
    (obj.options === undefined ||
      (Array.isArray(obj.options) && obj.options.every(isValidOption))) &&
    (obj.allowOther === undefined || typeof obj.allowOther === "boolean") &&
    (obj.prefillLabel === undefined || typeof obj.prefillLabel === "string") &&
    (obj.optional === undefined || typeof obj.optional === "boolean")
  );
}

function parseCreate(value: unknown): ClarifyCredentialRef | undefined {
  if (!value || typeof value !== "object") return undefined;
  const { type, name } = value as Record<string, unknown>;
  if (typeof type !== "string" || !CREDENTIAL_TYPES.has(type)) return undefined;
  if (typeof name !== "string") return undefined;
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > MAX_CREDENTIAL_NAME_LENGTH) return undefined;
  return { type: type as CredentialType, name: trimmed };
}

function parseEdit(value: unknown): ClarifyCredentialEdit | undefined {
  if (!value || typeof value !== "object") return undefined;
  const { id } = value as Record<string, unknown>;
  if (typeof id !== "string" || !CREDENTIAL_ID.test(id.trim())) return undefined;
  return { id: id.trim() };
}

function normalizeOption(option: unknown, singleChoice: boolean): ClarifyOption {
  if (!option || typeof option !== "object") return { label: String(option) };
  const raw = option as Record<string, unknown>;
  const normalized: ClarifyOption = { label: raw.label as string };
  if (!singleChoice) return normalized;
  if (typeof raw.prefill === "string") normalized.prefill = raw.prefill;
  const create = parseCreate(raw.create);
  const edit = create ? undefined : parseEdit(raw.edit);
  if (create) normalized.create = create;
  if (edit) normalized.edit = edit;
  return normalized;
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
    options: q.options?.map((option) => normalizeOption(option, q.type === "single")),
    allowOther: q.allowOther,
    prefillLabel: q.prefillLabel,
    optional: q.optional,
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

function withPrefill(
  q: ClarifyQuestion,
  label: string,
  edited: string | undefined,
): string {
  const option = q.options?.find((o) => o.label === label);
  const value = edited?.trim();
  if (option?.prefill === undefined || !value) return label;
  return `${label} (${q.prefillLabel?.trim() || "Value"}: "${value}")`;
}

function answerLabel(q: ClarifyQuestion, label: string, a: ClarifyAnswer): string {
  const option = q.options?.find((o) => o.label === label);
  if (a.credential && (option?.create || option?.edit)) {
    const verb = option.create ? "Created" : "Updated";
    return `${verb} credential "${a.credential.name}" (${a.credential.type})`;
  }
  return withPrefill(q, label, a.prefill);
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
      if (a.selected.length > 0) {
        parts.push(...a.selected.map((label) => answerLabel(q, label, a)));
      }
      if (a.other.trim()) parts.push(`Other: "${a.other.trim()}"`);
    }
    const empty = q.optional ? "(skipped)" : "(no answer)";
    const value = parts.length > 0 ? parts.join(", ") : empty;
    return `- ${q.text} → ${value}`;
  });
  return ["[Plan answers]", ...lines].join("\n");
}
