import { computed, ref } from "vue";

import type { CredentialForIntellisense } from "@/types/credential";
import type {
  CompletionContext,
  CompletionSuggestion,
  PropertyType,
  TriggerKind,
} from "@/types/expression";
import {
  ARRAY_METHODS,
  BOOLEAN_METHODS,
  BUILTIN_FUNCTIONS,
  DATE_BUILTINS,
  DATE_METHODS,
  FILTER_CONTEXT_FUNCTIONS,
  ITEM_PROPERTIES,
  ITEM_SUGGESTIONS,
  NUMBER_METHODS,
  OBJECT_METHODS,
  STRING_METHODS,
} from "@/types/expression";
import type { NodeResult, WorkflowEdge, WorkflowNode } from "@/types/workflow";

import { credentialsApi, globalVariablesApi } from "@/services/api";
import {
  resolveDatePropertyPathType,
  type ResolvedSuggestionType,
} from "@/composables/expressionCompletionTypeResolver";

const credentialsCache = ref<CredentialForIntellisense[]>([]);
const globalVariablesCache = ref<{ name: string; value_type: string }[]>([]);
let credentialsFetchPromise: Promise<void> | null = null;

async function fetchCredentialsForIntellisense(force = false): Promise<void> {
  if (!force && credentialsCache.value.length > 0) return;
  if (credentialsFetchPromise && !force) return credentialsFetchPromise;

  credentialsFetchPromise = (async () => {
    try {
      credentialsCache.value = await credentialsApi.getAvailable();
    } catch {
      credentialsCache.value = [];
    } finally {
      credentialsFetchPromise = null;
    }
  })();

  return credentialsFetchPromise;
}

fetchCredentialsForIntellisense();

let globalVariablesFetchPromise: Promise<void> | null = null;

async function fetchGlobalVariablesForIntellisense(
  force = false,
): Promise<void> {
  if (!force && globalVariablesCache.value.length > 0) return;
  if (globalVariablesFetchPromise && !force) return globalVariablesFetchPromise;

  globalVariablesFetchPromise = (async () => {
    try {
      const list = await globalVariablesApi.list();
      globalVariablesCache.value = list.map((v) => ({
        name: v.name,
        value_type: v.value_type || "string",
      }));
    } catch {
      globalVariablesCache.value = [];
    } finally {
      globalVariablesFetchPromise = null;
    }
  })();

  return globalVariablesFetchPromise;
}

fetchGlobalVariablesForIntellisense();

export function refreshCredentialsCache(): void {
  fetchCredentialsForIntellisense(true);
}

export function refreshGlobalVariablesCache(): void {
  fetchGlobalVariablesForIntellisense(true);
}

export function clearGlobalVariablesCache(): void {
  globalVariablesCache.value = [];
  globalVariablesFetchPromise = null;
}

const METHOD_RETURN_TYPES: Record<string, PropertyType> = {
  split: "array",
  reverse: "array",
  flat: "array",
  distinct: "array",
  distinctBy: "array",
  notNull: "array",
  add: "array",
  filter: "array",
  map: "array",
  sort: "array",
  take: "array",
  upper: "string",
  lower: "string",
  strip: "string",
  capitalize: "string",
  title: "string",
  charAt: "string",
  replace: "string",
  replaceAll: "string",
  regexReplace: "string",
  substring: "string",
  substr: "string",
  join: "string",
  first: "unknown",
  last: "unknown",
  random: "unknown",
  keys: "unknown",
  values: "unknown",
  entries: "unknown",
  length: "number",
  indexOf: "number",
  startswith: "boolean",
  endswith: "boolean",
  contains: "boolean",
  format: "string",
  toISO: "string",
  toDate: "string",
  toTime: "string",
  toUnix: "number",
  toMillis: "number",
  addDays: "object",
  addHours: "object",
  addMinutes: "object",
  addMonths: "object",
  addYears: "object",
  startOfDay: "object",
  endOfDay: "object",
  startOfMonth: "object",
  endOfMonth: "object",
};
METHOD_RETURN_TYPES["toString"] = "string";
METHOD_RETURN_TYPES["get"] = "unknown";

export interface UseExpressionCompletionOptions {
  nodes: WorkflowNode[];
  nodeResults: NodeResult[];
  edges: WorkflowEdge[];
  currentNodeId: string | null;
}

export function useExpressionCompletion(
  options: UseExpressionCompletionOptions,
) {
  const nodeLabels = computed(() => {
    return options.nodes.map((n) => n.data.label);
  });

  const upstreamNodeIds = computed(() => {
    if (!options.currentNodeId) return new Set<string>();

    const upstream = new Set<string>();
    const visited = new Set<string>();
    const queue = [options.currentNodeId];

    while (queue.length > 0) {
      const nodeId = queue.shift()!;
      if (visited.has(nodeId)) continue;
      visited.add(nodeId);

      for (const edge of options.edges) {
        if (edge.target === nodeId && !visited.has(edge.source)) {
          upstream.add(edge.source);
          queue.push(edge.source);
        }
      }
    }

    return upstream;
  });

  const upstreamNodes = computed(() => {
    if (!options.currentNodeId) return options.nodes;
    return options.nodes.filter((n) => upstreamNodeIds.value.has(n.id));
  });

  function getValueType(value: unknown): PropertyType {
    if (value === null) return "null";
    if (Array.isArray(value)) return "array";
    const type = typeof value;
    if (type === "string") return "string";
    if (type === "number") return "number";
    if (type === "boolean") return "boolean";
    if (type === "object") return "object";
    return "unknown";
  }

  /**
   * When METHOD_RETURN_TYPES marks a chain step as "unknown" (e.g. first/last/random,
   * keys/values/entries), use pinned/run output to infer the real value so completion
   * matches runtime type (object row vs string, or synthesized {key, value} entries)
   * instead of falling back to the "unknown" mix (which includes strings).
   */
  function tryResolveUnknownMethodOnSample(
    current: unknown,
    methodPart: string,
  ): unknown | undefined {
    const funcMatch = methodPart.match(/^(\w+)\(/);
    if (!funcMatch) {
      return undefined;
    }
    const methodName = funcMatch[1];

    // Object iteration methods synthesize a sample so downstream `.first()`,
    // `[0]`, `.key`, `.value`, and method chaining all see the correct shape.
    if (
      current &&
      typeof current === "object" &&
      !Array.isArray(current) &&
      (methodName === "entries" || methodName === "keys" || methodName === "values")
    ) {
      const objectEntries = Object.entries(current as Record<string, unknown>);
      if (objectEntries.length === 0) {
        return undefined;
      }
      if (methodName === "entries") {
        return objectEntries.map(([k, v]) => ({ key: k, value: v }));
      }
      if (methodName === "keys") {
        return objectEntries.map(([k]) => k);
      }
      return objectEntries.map(([, v]) => v);
    }

    if (!Array.isArray(current) || current.length === 0) {
      return undefined;
    }
    if (methodName === "first" || methodName === "random") {
      return current[0];
    }
    if (methodName === "last") {
      return current[current.length - 1];
    }
    return undefined;
  }

  function extractObjectKeys(
    obj: unknown,
    path: string[] = [],
  ): CompletionSuggestion[] {
    if (!obj || typeof obj !== "object") return [];

    let current: unknown = obj;
    let inferredType: PropertyType | null = null;
    let hasInferredType = false;

    for (const key of path) {
      const returnType = inferReturnType(key);
      if (returnType) {
        if (returnType === "unknown") {
          const stepped = tryResolveUnknownMethodOnSample(current, key);
          if (stepped !== undefined) {
            current = stepped;
            inferredType = null;
            hasInferredType = false;
            continue;
          }
        }
        inferredType = returnType;
        hasInferredType = true;
        continue;
      }

      if (hasInferredType) {
        // DSL: `.length` on string or array is a number (property access, not `length()`).
        // Without this, the segment is skipped and the chain stays typed as string, so
        // completions after `.length` stay wrong (string methods instead of number).
        if (key === "length" && (inferredType === "string" || inferredType === "array")) {
          inferredType = "number";
          continue;
        }
        continue;
      }

      inferredType = null;

      // Primitive strings have no enumerable "length" for `key in current`, so a path
      // like `$obj.keys().first().length` (first key name as string) must treat `.length`
      // as the DSL length → number, same as the `hasInferredType` branch for typed chains.
      if (key === "length" && typeof current === "string") {
        inferredType = "number";
        hasInferredType = true;
        continue;
      }

      const arrayMatch = key.match(/^(.+)\[(\d+)\]$/);
      if (arrayMatch) {
        const [, arrayKey, indexStr] = arrayMatch;
        const index = parseInt(indexStr, 10);
        if (current && typeof current === "object" && arrayKey in current) {
          const arr = (current as Record<string, unknown>)[arrayKey];
          if (Array.isArray(arr) && arr.length > index) {
            current = arr[index];
          } else {
            return getSuggestionsForType(inferredType);
          }
        } else {
          return getSuggestionsForType(inferredType);
        }
      } else if (current && typeof current === "object" && key in current) {
        current = (current as Record<string, unknown>)[key];
      } else {
        return getSuggestionsForType(inferredType);
      }
    }

    if (inferredType) {
      return getSuggestionsForType(inferredType);
    }

    if (!current || typeof current !== "object") {
      if (typeof current === "string") {
        return STRING_METHODS;
      }
      if (typeof current === "number") {
        return NUMBER_METHODS;
      }
      if (typeof current === "boolean") {
        return BOOLEAN_METHODS;
      }
      return [];
    }

    if (Array.isArray(current)) {
      const suggestions: CompletionSuggestion[] = [];
      if (current.length > 0) {
        const maxItems = Math.min(current.length, 5);
        for (let i = 0; i < maxItems; i++) {
          const itemType = getValueType(current[i]);
          suggestions.push({
            label: `[${i}]`,
            insertText: `[${i}]`,
            type: "property",
            detail: `Index ${i}`,
            propertyType: itemType,
          });
        }
        if (current.length > 5) {
          suggestions.push({
            label: `[...]`,
            insertText: `[0]`,
            type: "property",
            detail: `${current.length} items total`,
            propertyType: "unknown",
          });
        }
      }
      suggestions.push(...ARRAY_METHODS);
      return suggestions;
    }

    const suggestions: CompletionSuggestion[] = [];
    for (const [key, value] of Object.entries(current)) {
      const propertyType = getValueType(value);
      suggestions.push({
        label: key,
        insertText: key,
        type: "property",
        detail: propertyType,
        propertyType,
      });
    }
    suggestions.push(...OBJECT_METHODS);
    return suggestions;
  }

  function deduplicateSuggestions(suggestions: CompletionSuggestion[]): CompletionSuggestion[] {
    const seen = new Set<string>();
    return suggestions.filter((s) => {
      if (seen.has(s.label)) return false;
      seen.add(s.label);
      return true;
    });
  }

  function getSuggestionsForType(type: ResolvedSuggestionType | null): CompletionSuggestion[] {
    switch (type) {
      case "date":
        return DATE_METHODS;
      case "array":
        return ARRAY_METHODS;
      case "string":
        return STRING_METHODS;
      case "number":
        return NUMBER_METHODS;
      case "boolean":
        return BOOLEAN_METHODS;
      case "object":
        return OBJECT_METHODS;
      case "unknown":
        return deduplicateSuggestions([
          ...STRING_METHODS,
          ...NUMBER_METHODS,
          ...ARRAY_METHODS,
          ...OBJECT_METHODS,
          ...BOOLEAN_METHODS,
        ]);
      default:
        return [];
    }
  }

  function parseExpressionContext(
    text: string,
    cursorPos: number,
  ): CompletionContext | null {
    const textBeforeCursor = text.slice(0, cursorPos);

    const filterContext = detectFilterContext(textBeforeCursor);
    if (filterContext) {
      return filterContext;
    }

    // Check if we're inside $array(), $notNull() or similar function arguments
    const functionArgContext = detectFunctionArgContext(textBeforeCursor);
    if (functionArgContext) {
      return functionArgContext;
    }

    const dictGetArgContext = detectDictGetArgContext(textBeforeCursor);
    if (dictGetArgContext) {
      return dictGetArgContext;
    }

    const dollarIndex = textBeforeCursor.lastIndexOf("$");
    if (dollarIndex === -1) {
      return null;
    }

    const expressionText = textBeforeCursor.slice(dollarIndex + 1);

    const parts = splitExpressionParts(expressionText);
    if (parts.length === 0) {
      return null;
    }

    if (parts.length === 1) {
      return {
        triggerKind: "node" as TriggerKind,
        propertyPath: [],
        prefix: parts[0],
        startOffset: dollarIndex,
        endOffset: cursorPos,
      };
    }

    const nodeLabel = parts[0];
    const propertyPath = parts.slice(1, -1);
    const prefix = parts[parts.length - 1];

    return {
      triggerKind: "property" as TriggerKind,
      nodeLabel,
      propertyPath,
      prefix,
      startOffset: dollarIndex,
      endOffset: cursorPos,
    };
  }

  function detectFunctionArgContext(textBeforeCursor: string): CompletionContext | null {
    // Match $array(, $notNull(, etc. and detect if we're inside the arguments
    const functionPatterns = ["array", "notNull"];

    for (const func of functionPatterns) {
      const pattern = new RegExp(`\\$${func}\\(([\\s\\S]*)$`);
      const match = textBeforeCursor.match(pattern);

      if (match) {
        const argsContent = match[1];

        // Find the last argument being typed (after last comma or at start)
        let lastArgStart = 0;
        let depth = 0;
        let inString = false;
        let stringChar = "";

        for (let i = 0; i < argsContent.length; i++) {
          const char = argsContent[i];

          if (inString) {
            if (char === stringChar && argsContent[i - 1] !== "\\") {
              inString = false;
            }
            continue;
          }

          if (char === '"' || char === "'") {
            inString = true;
            stringChar = char;
            continue;
          }

          if (char === "(" || char === "[") {
            depth++;
            continue;
          }

          if (char === ")" || char === "]") {
            depth--;
            continue;
          }

          if (char === "," && depth === 0) {
            lastArgStart = i + 1;
          }
        }

        const currentArg = argsContent.slice(lastArgStart).trim();

        // Check if current arg has a dot - means we're accessing properties
        if (currentArg.includes(".")) {
          const parts = splitExpressionParts(currentArg);
          if (parts.length >= 2) {
            const nodeLabel = parts[0];
            const propertyPath = parts.slice(1, -1);
            const prefix = parts[parts.length - 1];

            return {
              triggerKind: "property" as TriggerKind,
              nodeLabel,
              propertyPath,
              prefix,
              startOffset: textBeforeCursor.length - currentArg.length,
              endOffset: textBeforeCursor.length,
              isInsideFunctionArg: true,
            };
          }
        }

        // Just typing a node reference
        return {
          triggerKind: "node" as TriggerKind,
          propertyPath: [],
          prefix: currentArg,
          startOffset: textBeforeCursor.length - currentArg.length,
          endOffset: textBeforeCursor.length,
          isInsideFunctionArg: true,
        };
      }
    }

    return null;
  }

  /** Inside ``.get(`` first or second argument: insert node paths without a leading ``$`` (same as ``$array()``). */
  function detectDictGetArgContext(textBeforeCursor: string): CompletionContext | null {
    const re = /\.get\s*\(/g;
    let last: RegExpExecArray | null = null;
    let m: RegExpExecArray | null;
    while ((m = re.exec(textBeforeCursor)) !== null) {
      last = m;
    }
    if (!last) {
      return null;
    }

    const openParenIndex = last.index + last[0].length - 1;
    const rawArgs = textBeforeCursor.slice(openParenIndex + 1);

    let depth = 1;
    let inString = false;
    let stringChar = "";
    let truncateAt = rawArgs.length;
    for (let i = 0; i < rawArgs.length; i++) {
      const char = rawArgs[i];
      if (inString) {
        if (char === stringChar && rawArgs[i - 1] !== "\\") {
          inString = false;
        }
        continue;
      }
      if (char === '"' || char === "'") {
        inString = true;
        stringChar = char;
        continue;
      }
      if (char === "(" || char === "[") {
        depth++;
        continue;
      }
      if (char === ")" || char === "]") {
        depth--;
        if (depth === 0) {
          truncateAt = i;
          break;
        }
        continue;
      }
    }

    const closeParenIndex = openParenIndex + 1 + truncateAt;
    if (textBeforeCursor.length > closeParenIndex) {
      return null;
    }

    const argsContent = rawArgs.slice(0, truncateAt);

    let lastArgStart = 0;
    depth = 0;
    inString = false;
    stringChar = "";

    for (let i = 0; i < argsContent.length; i++) {
      const char = argsContent[i];
      if (inString) {
        if (char === stringChar && argsContent[i - 1] !== "\\") {
          inString = false;
        }
        continue;
      }
      if (char === '"' || char === "'") {
        inString = true;
        stringChar = char;
        continue;
      }
      if (char === "(" || char === "[") {
        depth++;
        continue;
      }
      if (char === ")" || char === "]") {
        depth--;
        continue;
      }
      if (char === "," && depth === 0) {
        lastArgStart = i + 1;
      }
    }

    const currentArg = argsContent.slice(lastArgStart).trim();
    if (currentArg.startsWith('"') || currentArg.startsWith("'")) {
      return null;
    }

    if (currentArg.includes(".")) {
      const parts = splitExpressionParts(currentArg);
      if (parts.length >= 2) {
        const nodeLabel = parts[0];
        const propertyPath = parts.slice(1, -1);
        const prefix = parts[parts.length - 1];

        return {
          triggerKind: "property" as TriggerKind,
          nodeLabel,
          propertyPath,
          prefix,
          startOffset: textBeforeCursor.length - currentArg.length,
          endOffset: textBeforeCursor.length,
          isInsideFunctionArg: true,
        };
      }
    }

    return {
      triggerKind: "node" as TriggerKind,
      propertyPath: [],
      prefix: currentArg,
      startOffset: textBeforeCursor.length - currentArg.length,
      endOffset: textBeforeCursor.length,
      isInsideFunctionArg: true,
    };
  }

  function detectFilterContext(textBeforeCursor: string): CompletionContext | null {
    const filterFuncs = ["filter", "map", "sort"];

    for (const func of filterFuncs) {
      const patternWithDot = new RegExp(`\\.${func}\\(["']([^"']*)\\.([^"']*)$`);
      const matchWithDot = textBeforeCursor.match(patternWithDot);

      if (matchWithDot) {
        const beforeDot = matchWithDot[1] || "";
        const afterDot = matchWithDot[2] || "";

        return {
          triggerKind: "item" as TriggerKind,
          propertyPath: [beforeDot],
          prefix: afterDot,
          startOffset: textBeforeCursor.lastIndexOf(".") + 1,
          endOffset: textBeforeCursor.length,
          isInsideFilterExpr: true,
        };
      }

      const patternBase = new RegExp(`\\.${func}\\(["']([^"']*)$`);
      const matchBase = textBeforeCursor.match(patternBase);

      if (matchBase) {
        const innerExpr = matchBase[1] || "";

        return {
          triggerKind: "item" as TriggerKind,
          propertyPath: [],
          prefix: innerExpr,
          startOffset: matchBase.index! + func.length + 3,
          endOffset: textBeforeCursor.length,
          isInsideFilterExpr: true,
        };
      }
    }

    return null;
  }

  function splitExpressionParts(expr: string): string[] {
    const parts: string[] = [];
    let current = "";
    let depth = 0;
    let inString = false;
    let stringChar = "";

    for (let i = 0; i < expr.length; i++) {
      const char = expr[i];

      if (inString) {
        current += char;
        if (char === stringChar && expr[i - 1] !== "\\") {
          inString = false;
        }
        continue;
      }

      if (char === '"' || char === "'") {
        inString = true;
        stringChar = char;
        current += char;
        continue;
      }

      if (char === "(" || char === "[") {
        depth++;
        current += char;
        continue;
      }

      if (char === ")" || char === "]") {
        depth--;
        current += char;
        continue;
      }

      if (char === "." && depth === 0) {
        parts.push(current);
        current = "";
        continue;
      }

      if (/[\s+\-*/=<>!&|,]/.test(char) && depth === 0) {
        return [];
      }

      current += char;
    }

    parts.push(current);
    return parts;
  }

  function inferReturnType(part: string): PropertyType | null {
    const funcMatch = part.match(/^(\w+)\(/);
    if (funcMatch) {
      const methodName = funcMatch[1];
      return METHOD_RETURN_TYPES[methodName] || null;
    }
    const arrayIndexMatch = part.match(/^\[(\d+)\]$/);
    if (arrayIndexMatch) {
      return "unknown";
    }
    return null;
  }

  function getNodeSuggestions(prefix: string, isInsideFunctionArg = false): CompletionSuggestion[] {
    const suggestions: CompletionSuggestion[] = [];

    const nodesToSuggest = [...upstreamNodes.value].reverse();
    const labelPrefix = isInsideFunctionArg ? "" : "$";

    for (const node of nodesToSuggest) {
      const label = node.data.label;
      if (label.toLowerCase().startsWith(prefix.toLowerCase())) {
        suggestions.push({
          label: `${labelPrefix}${label}`,
          insertText: label,
          type: "node",
          detail: node.type || "input",
          description: `Reference ${label} node output`,
        });
      }
    }

    if ("credentials".startsWith(prefix.toLowerCase())) {
      suggestions.push({
        label: `${labelPrefix}credentials`,
        insertText: "credentials",
        type: "node",
        detail: "credentials",
        description: "Access stored credentials",
      });
    }

    if ("vars".startsWith(prefix.toLowerCase())) {
      suggestions.push({
        label: `${labelPrefix}vars`,
        insertText: "vars",
        type: "node",
        detail: "variables",
        description: "Access workflow variables",
      });
    }

    if ("global".startsWith(prefix.toLowerCase())) {
      suggestions.push({
        label: `${labelPrefix}global`,
        insertText: "global",
        type: "node",
        detail: "global variables",
        description: "Access global variable store",
      });
    }

    // Don't show date builtins or other $functions inside function args
    if (!isInsideFunctionArg) {
      const matchingDateBuiltins = DATE_BUILTINS.filter((f) =>
        f.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );

      for (const dateFunc of matchingDateBuiltins) {
        suggestions.push({
          label: `$${dateFunc.label}`,
          insertText: dateFunc.insertText,
          type: "function",
          detail: dateFunc.detail,
          description: dateFunc.description,
        });
      }

      const matchingFunctions = BUILTIN_FUNCTIONS.filter((f) =>
        f.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );

      for (const func of matchingFunctions) {
        suggestions.push({
          label: `$${func.label}()`,
          insertText: `${func.label}()`,
          type: "function",
          detail: func.detail,
          description: func.description,
        });
      }
    }

    return suggestions;
  }

  function getPropertySuggestions(
    nodeLabel: string,
    propertyPath: string[],
    prefix: string,
  ): CompletionSuggestion[] {
    // Check if nodeLabel is a builtin function that returns an array
    if (nodeLabel.startsWith("array(") || nodeLabel.startsWith("notNull(")) {
      const allSuggestions = ARRAY_METHODS;
      if (!prefix) {
        return allSuggestions;
      }
      return allSuggestions.filter((s) =>
        s.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );
    }

    if (nodeLabel === "now" || nodeLabel.startsWith("Date(")) {
      const resolvedType = resolveDatePropertyPathType(propertyPath, DATE_METHODS);
      const allSuggestions = getSuggestionsForType(resolvedType);
      if (!prefix) {
        return allSuggestions;
      }
      return allSuggestions.filter((s) =>
        s.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );
    }

    if (nodeLabel === "credentials") {
      const credentialSuggestions: CompletionSuggestion[] =
        credentialsCache.value.map((cred) => ({
          label: cred.name,
          insertText: cred.name,
          type: "property" as const,
          detail: cred.type,
          description: `Access ${cred.name} credential`,
          propertyType: "string" as PropertyType,
        }));

      if (!prefix) {
        return credentialSuggestions;
      }
      return credentialSuggestions.filter((s) =>
        s.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );
    }

    if (nodeLabel === "vars") {
      if (propertyPath.length === 0) {
        const variableNodes = options.nodes.filter(
          (n) => n.type === "variable",
        );
        const varSuggestions: CompletionSuggestion[] = variableNodes
          .map((node) => node.data.variableName)
          .filter((name): name is string => !!name)
          .filter((name, index, arr) => arr.indexOf(name) === index)
          .map((varName) => {
            const varNode = [...variableNodes]
              .reverse()
              .find((n: WorkflowNode) => n.data.variableName === varName);
            const varType = varNode?.data.variableType || "auto";
            return {
              label: varName,
              insertText: varName,
              type: "property" as const,
              detail: varType === "auto" ? "variable" : varType,
              description: `Access ${varName} variable`,
              propertyType: (varType === "auto"
                ? "unknown"
                : varType) as PropertyType,
            };
          });

        if (!prefix) {
          return varSuggestions;
        }
        return varSuggestions.filter((s) =>
          s.label.toLowerCase().startsWith(prefix.toLowerCase()),
        );
      }
      const varName = propertyPath[0];
      const variableNodes = options.nodes.filter((n) => n.type === "variable");
      const varNode = [...variableNodes]
        .reverse()
        .find((n: WorkflowNode) => n.data.variableName === varName);
      const varType = varNode?.data.variableType || "auto";

      let methodsForType: CompletionSuggestion[] = [];
      switch (varType) {
        case "string":
          methodsForType = STRING_METHODS;
          break;
        case "number":
          methodsForType = NUMBER_METHODS;
          break;
        case "boolean":
          methodsForType = BOOLEAN_METHODS;
          break;
        case "array":
          methodsForType = ARRAY_METHODS;
          break;
        case "object":
          methodsForType = OBJECT_METHODS;
          break;
        default:
          methodsForType = deduplicateSuggestions([
            ...STRING_METHODS,
            ...NUMBER_METHODS,
            ...ARRAY_METHODS,
            ...OBJECT_METHODS,
          ]);
      }

      if (!prefix) {
        return methodsForType;
      }
      return methodsForType.filter((s) =>
        s.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );
    }

    if (nodeLabel === "global") {
      if (propertyPath.length === 0) {
        const globalSuggestions: CompletionSuggestion[] =
          globalVariablesCache.value.map((v) => ({
            label: v.name,
            insertText: v.name,
            type: "property" as const,
            detail: v.value_type,
            description: `Access ${v.name} global variable`,
            propertyType: v.value_type as PropertyType,
          }));

        if (!prefix) {
          return globalSuggestions;
        }
        return globalSuggestions.filter((s) =>
          s.label.toLowerCase().startsWith(prefix.toLowerCase()),
        );
      }
      const varName = propertyPath[0];
      const globalVar = globalVariablesCache.value.find(
        (v) => v.name === varName,
      );
      const varType = globalVar?.value_type || "string";

      let methodsForType: CompletionSuggestion[] = [];
      switch (varType) {
        case "string":
          methodsForType = STRING_METHODS;
          break;
        case "number":
          methodsForType = NUMBER_METHODS;
          break;
        case "boolean":
          methodsForType = BOOLEAN_METHODS;
          break;
        case "array":
          methodsForType = ARRAY_METHODS;
          break;
        case "object":
          methodsForType = OBJECT_METHODS;
          break;
        default:
          methodsForType = deduplicateSuggestions([
            ...STRING_METHODS,
            ...NUMBER_METHODS,
            ...ARRAY_METHODS,
            ...OBJECT_METHODS,
          ]);
      }

      if (!prefix) {
        return methodsForType;
      }
      return methodsForType.filter((s) =>
        s.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );
    }

    const nodeResult = options.nodeResults.find(
      (r) =>
        r.node_label === nodeLabel ||
        (nodeLabel === "input" && r.node_type === "textInput"),
    );

    const node = options.nodes.find((n) => n.data.label === nodeLabel);
    const pinnedData = node?.data.pinnedData;

    const outputData = nodeResult?.output || pinnedData;

    const isTextInputNode = node?.type === "textInput";

    if (!outputData) {
      if (isTextInputNode && propertyPath.length === 0) {
        const textInputSuggestions: CompletionSuggestion[] = [
          {
            label: "text",
            insertText: "text",
            type: "property",
            detail: "string",
            description: "User input text",
            propertyType: "string",
          },
          {
            label: "body",
            insertText: "body",
            type: "property",
            detail: "object",
            description: "HTTP request body (API execution)",
            propertyType: "object",
          },
          {
            label: "headers",
            insertText: "headers",
            type: "property",
            detail: "object",
            description: "HTTP request headers (API execution)",
            propertyType: "object",
          },
          {
            label: "query",
            insertText: "query",
            type: "property",
            detail: "object",
            description: "URL query parameters (API execution)",
            propertyType: "object",
          },
        ];

        const inputFields = node.data.inputFields as
          | Array<{ key: string }>
          | undefined;
        if (inputFields && inputFields.length > 0) {
          for (const field of inputFields) {
            if (field.key !== "text") {
              textInputSuggestions.unshift({
                label: field.key,
                insertText: field.key,
                type: "property",
                detail: "string",
                description: `Input field: ${field.key}`,
                propertyType: "string",
              });
            }
          }
        }

        if (!prefix) {
          return textInputSuggestions;
        }
        return textInputSuggestions.filter((s) =>
          s.label.toLowerCase().startsWith(prefix.toLowerCase()),
        );
      }

      return [
        {
          label: "Run workflow first to see available properties",
          insertText: "",
          type: "hint",
          detail: "",
          hintAction: "run-workflow",
        },
      ];
    }

    const allSuggestions = extractObjectKeys(outputData, propertyPath);

    if (isTextInputNode && propertyPath.length === 0) {
      const hasBody = allSuggestions.some((s) => s.label === "body");
      const hasHeaders = allSuggestions.some((s) => s.label === "headers");
      const hasQuery = allSuggestions.some((s) => s.label === "query");

      if (!hasBody) {
        allSuggestions.push({
          label: "body",
          insertText: "body",
          type: "property",
          detail: "object",
          description: "HTTP request body (API execution)",
          propertyType: "object",
        });
      }
      if (!hasHeaders) {
        allSuggestions.push({
          label: "headers",
          insertText: "headers",
          type: "property",
          detail: "object",
          description: "HTTP request headers (API execution)",
          propertyType: "object",
        });
      }
      if (!hasQuery) {
        allSuggestions.push({
          label: "query",
          insertText: "query",
          type: "property",
          detail: "object",
          description: "URL query parameters (API execution)",
          propertyType: "object",
        });
      }
    }

    if (!prefix) {
      return allSuggestions;
    }

    return allSuggestions.filter((s) =>
      s.label.toLowerCase().startsWith(prefix.toLowerCase()),
    );
  }

  function getFunctionSuggestions(prefix: string): CompletionSuggestion[] {
    if (!prefix) return BUILTIN_FUNCTIONS;
    return BUILTIN_FUNCTIONS.filter((f) =>
      f.label.toLowerCase().startsWith(prefix.toLowerCase()),
    );
  }

  function getItemSuggestions(
    propertyPath: string[],
    prefix: string,
  ): CompletionSuggestion[] {
    if (propertyPath.length === 0 || propertyPath[0] === "") {
      const suggestions: CompletionSuggestion[] = [];

      const matchingItems = ITEM_SUGGESTIONS.filter((s) =>
        s.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );
      suggestions.push(...matchingItems);

      const matchingFunctions = FILTER_CONTEXT_FUNCTIONS.filter((s) =>
        s.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );
      suggestions.push(...matchingFunctions);

      return suggestions;
    }

    if (propertyPath[0] === "item" || propertyPath[0].startsWith("item")) {
      const matchingProperties = ITEM_PROPERTIES.filter((s) =>
        s.label.toLowerCase().startsWith(prefix.toLowerCase()),
      );
      return matchingProperties;
    }

    return ITEM_PROPERTIES.filter((s) =>
      s.label.toLowerCase().startsWith(prefix.toLowerCase()),
    );
  }

  function getSuggestions(
    text: string,
    cursorPos: number,
  ): CompletionSuggestion[] {
    const context = parseExpressionContext(text, cursorPos);

    if (!context) {
      return [];
    }

    if (context.triggerKind === "item") {
      return getItemSuggestions(context.propertyPath, context.prefix);
    }

    if (context.triggerKind === "node") {
      return getNodeSuggestions(context.prefix, context.isInsideFunctionArg);
    }

    if (context.triggerKind === "property" && context.nodeLabel) {
      return getPropertySuggestions(
        context.nodeLabel,
        context.propertyPath,
        context.prefix,
      );
    }

    return [];
  }

  function applyCompletion(
    text: string,
    cursorPos: number,
    suggestion: CompletionSuggestion,
  ): { newText: string; newCursorPos: number } {
    const context = parseExpressionContext(text, cursorPos);

    if (!context) {
      return { newText: text, newCursorPos: cursorPos };
    }

    const beforeExpression = text.slice(0, context.startOffset);
    const afterCursor = text.slice(cursorPos);

    const insertText = suggestion.insertText;

    if (context.triggerKind === "item") {
      const prefixStart = cursorPos - context.prefix.length;
      const beforePrefix = text.slice(0, prefixStart);
      const newText = beforePrefix + insertText + afterCursor;

      let newCursorPos = beforePrefix.length + insertText.length;
      if (
        suggestion.type === "function" &&
        (insertText.endsWith('")') || insertText.endsWith("()"))
      ) {
        newCursorPos = beforePrefix.length + insertText.length - 1;
        if (insertText.endsWith('")')) {
          newCursorPos = beforePrefix.length + insertText.length - 2;
        }
      }

      return { newText, newCursorPos };
    }

    if (context.triggerKind === "node") {
      // If inside function arg (like $array()), don't add $ prefix
      const fullExpression = context.isInsideFunctionArg ? insertText : `$${insertText}`;
      const newText = beforeExpression + fullExpression + afterCursor;

      let newCursorPos = beforeExpression.length + fullExpression.length;
      if (suggestion.type === "function" && insertText.endsWith("()")) {
        newCursorPos = beforeExpression.length + fullExpression.length - 1;
      }

      return { newText, newCursorPos };
    }

    if (context.triggerKind === "property" && context.nodeLabel) {
      // If inside function arg (like $array()), don't add $ prefix
      const prefix = context.isInsideFunctionArg ? "" : "$";
      const basePath =
        context.propertyPath.length > 0
          ? `${prefix}${context.nodeLabel}.${context.propertyPath.join(".")}.`
          : `${prefix}${context.nodeLabel}.`;

      const fullExpression = basePath + insertText;
      const newText = beforeExpression + fullExpression + afterCursor;

      let newCursorPos = beforeExpression.length + fullExpression.length;
      if (suggestion.type === "function" && insertText.endsWith("()")) {
        newCursorPos = beforeExpression.length + fullExpression.length - 1;
      }

      return { newText, newCursorPos };
    }

    return { newText: text, newCursorPos: cursorPos };
  }

  return {
    nodeLabels,
    parseExpressionContext,
    getSuggestions,
    getNodeSuggestions,
    getPropertySuggestions,
    getFunctionSuggestions,
    applyCompletion,
    extractObjectKeys,
  };
}
