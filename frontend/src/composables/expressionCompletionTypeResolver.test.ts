import { describe, expect, it } from "vitest";

import {
  inferChainedMethodReturnType,
  resolveDatePropertyPathType,
} from "./expressionCompletionTypeResolver";
import type { CompletionSuggestion } from "@/types/expression";

function buildSuggestion(overrides: Partial<CompletionSuggestion> = {}): CompletionSuggestion {
  return {
    label: "toISOString",
    insertText: "toISOString()",
    type: "function",
    ...overrides,
  };
}

describe("inferChainedMethodReturnType", () => {
  it("resolves a plain property access by label", () => {
    const suggestions = [buildSuggestion({ label: "year", propertyType: "number" })];

    expect(inferChainedMethodReturnType("year", suggestions)).toBe("number");
  });

  it("resolves a method call by stripping the parens and arguments", () => {
    const suggestions = [buildSuggestion({ label: "toISOString", propertyType: "string" })];

    expect(inferChainedMethodReturnType("toISOString()", suggestions)).toBe("string");
  });

  it("strips arguments from a call with parameters, not just an empty ()", () => {
    const suggestions = [buildSuggestion({ label: "plus", propertyType: "object" })];

    expect(inferChainedMethodReturnType("plus(1, 'day')", suggestions)).toBe("date");
  });

  it("returns null when no suggestion matches the method/property name", () => {
    const suggestions = [buildSuggestion({ label: "year", propertyType: "number" })];

    expect(inferChainedMethodReturnType("unknownMethod()", suggestions)).toBeNull();
  });

  it('treats an "object" propertyType as "date" (chainable date-builder methods)', () => {
    const suggestions = [buildSuggestion({ label: "plus", propertyType: "object" })];

    expect(inferChainedMethodReturnType("plus()", suggestions)).toBe("date");
  });

  it("returns null when the matched suggestion has no propertyType at all", () => {
    const suggestions = [buildSuggestion({ label: "describe", propertyType: undefined })];

    expect(inferChainedMethodReturnType("describe()", suggestions)).toBeNull();
  });
});

describe("resolveDatePropertyPathType", () => {
  it('returns "date" for an empty property path', () => {
    expect(resolveDatePropertyPathType([], [])).toBe("date");
  });

  it("stays on the date chain across object-returning methods, then resolves the final type", () => {
    const suggestions = [
      buildSuggestion({ label: "plus", propertyType: "object" }),
      buildSuggestion({ label: "toISOString", propertyType: "string" }),
    ];

    const result = resolveDatePropertyPathType(["plus()", "toISOString()"], suggestions);

    expect(result).toBe("string");
  });

  it("resolves a single non-object-returning method directly", () => {
    const suggestions = [buildSuggestion({ label: "year", propertyType: "number" })];

    expect(resolveDatePropertyPathType(["year"], suggestions)).toBe("number");
  });

  it("short-circuits once the chain leaves the date type, ignoring later parts entirely", () => {
    const suggestions = [buildSuggestion({ label: "year", propertyType: "number" })];

    // "doesNotExist" is NOT in `suggestions` at all - if the short-circuit in
    // resolveDatePropertyPathType didn't actually stop processing once
    // currentType left "date", this would fall through to
    // inferChainedMethodReturnType("doesNotExist", ...), find nothing, and
    // return "unknown" instead of "number".
    const result = resolveDatePropertyPathType(["year", "doesNotExist"], suggestions);

    expect(result).toBe("number");
  });

  it('returns "unknown" when a part in the chain does not match any suggestion', () => {
    const result = resolveDatePropertyPathType(["doesNotExist"], []);

    expect(result).toBe("unknown");
  });
});
