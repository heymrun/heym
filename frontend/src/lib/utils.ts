import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(date));
}

export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export function generateId(): string {
  return `node_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

export function hasNestedDollarInParentheses(text: string): boolean {
  if (!text) return false;
  let inString = false;
  let stringChar = "";
  let parenDepth = 0;
  let bracketDepth = 0;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    if (inString) {
      if (char === stringChar && text[i - 1] !== "\\") {
        inString = false;
      }
      continue;
    }

    if (char === '"' || char === "'") {
      inString = true;
      stringChar = char;
      continue;
    }

    if (char === "(") {
      parenDepth++;
      continue;
    }

    if (char === ")") {
      parenDepth = Math.max(0, parenDepth - 1);
      continue;
    }

    if (char === "[") {
      bracketDepth++;
      continue;
    }

    if (char === "]") {
      bracketDepth = Math.max(0, bracketDepth - 1);
      continue;
    }

    if (char === "$" && i + 1 < text.length && /[a-zA-Z]/.test(text[i + 1])) {
      if (parenDepth > 0 || bracketDepth > 0) {
        return true;
      }
    }
  }

  return false;
}

export function hasMultipleDollarExpressions(text: string): boolean {
  return hasNestedDollarInParentheses(text);
}

export interface SourceNodeInfo {
  label: string;
  type: string;
}

export function buildDynamicRef(sourceNode: SourceNodeInfo | null): string {
  const label = sourceNode?.label || "input";
  const isTextInput = !sourceNode || sourceNode.type === "textInput";
  const bodyPart = isTextInput ? ".body" : "";
  return `$${label}${bodyPart}.text`;
}

function replaceInputRefsInObject(
  obj: Record<string, unknown>,
  replacement: string
): Record<string, unknown> {
  const result: Record<string, unknown> = {};

  for (const key in obj) {
    const value = obj[key];
    if (typeof value === "string" && value.includes("$input.")) {
      result[key] = value.replace(/\$input\./g, replacement);
    } else if (Array.isArray(value)) {
      result[key] = value.map((item) => {
        if (typeof item === "object" && item !== null) {
          return replaceInputRefsInObject(item as Record<string, unknown>, replacement);
        }
        if (typeof item === "string" && item.includes("$input.")) {
          return item.replace(/\$input\./g, replacement);
        }
        return item;
      });
    } else {
      result[key] = value;
    }
  }

  return result;
}

export function replaceInputRefs<T>(
  data: T,
  sourceNode: SourceNodeInfo | null
): T {
  const dynamicRef = buildDynamicRef(sourceNode);
  const replacement = dynamicRef.replace(".text", ".");
  const result = replaceInputRefsInObject(data as Record<string, unknown>, replacement);
  return result as T;
}

function replaceNodeLabelRefsInValue(
  value: string,
  oldLabel: string,
  newRef: string
): string {
  const pattern = new RegExp(`\\$${oldLabel}(?=\\.|\\s|$|\\))`, "g");
  return value.replace(pattern, newRef);
}

function replaceNodeLabelRefsInObject(
  obj: Record<string, unknown>,
  labelMap: Map<string, string>
): Record<string, unknown> {
  const result: Record<string, unknown> = {};

  for (const key in obj) {
    const value = obj[key];
    if (typeof value === "string") {
      let newValue = value;
      for (const [oldLabel, newRef] of labelMap) {
        newValue = replaceNodeLabelRefsInValue(newValue, oldLabel, newRef);
      }
      result[key] = newValue;
    } else if (Array.isArray(value)) {
      result[key] = value.map((item) => {
        if (typeof item === "object" && item !== null) {
          return replaceNodeLabelRefsInObject(item as Record<string, unknown>, labelMap);
        }
        if (typeof item === "string") {
          let newValue = item;
          for (const [oldLabel, newRef] of labelMap) {
            newValue = replaceNodeLabelRefsInValue(newValue, oldLabel, newRef);
          }
          return newValue;
        }
        return item;
      });
    } else if (typeof value === "object" && value !== null) {
      result[key] = replaceNodeLabelRefsInObject(value as Record<string, unknown>, labelMap);
    } else {
      result[key] = value;
    }
  }

  return result;
}

export function replaceNodeLabelRefs<T>(
  data: T,
  labelMap: Map<string, string>
): T {
  if (typeof data !== "object" || data === null) {
    return data;
  }
  const result = replaceNodeLabelRefsInObject(data as Record<string, unknown>, labelMap);
  return result as T;
}
