import type { CompletionSuggestion, PropertyType } from "@/types/expression";

export type ResolvedSuggestionType = PropertyType | "date";

function normalizeMethodName(part: string): string {
  const funcMatch = part.match(/^(\w+)\(/);
  if (funcMatch) {
    return funcMatch[1];
  }
  return part;
}

export function inferChainedMethodReturnType(
  part: string,
  methodSuggestions: CompletionSuggestion[],
): ResolvedSuggestionType | null {
  const methodName = normalizeMethodName(part);
  const methodSuggestion = methodSuggestions.find((suggestion) => suggestion.label === methodName);
  if (!methodSuggestion) {
    return null;
  }

  if (methodSuggestion.propertyType === "object") {
    return "date";
  }

  return methodSuggestion.propertyType ?? null;
}

export function resolveDatePropertyPathType(
  propertyPath: string[],
  methodSuggestions: CompletionSuggestion[],
): ResolvedSuggestionType {
  let currentType: ResolvedSuggestionType = "date";

  for (const part of propertyPath) {
    if (currentType !== "date") {
      return currentType;
    }

    const inferredType = inferChainedMethodReturnType(part, methodSuggestions);
    if (!inferredType) {
      return "unknown";
    }
    currentType = inferredType;
  }

  return currentType;
}
