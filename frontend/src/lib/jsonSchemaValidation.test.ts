import { describe, expect, it } from "vitest";
import {
  MAX_SCHEMA_NODES,
  MAX_SCHEMA_PATTERN_LENGTH,
  MAX_SCHEMA_BYTES,
  validateJsonOutputSchema,
  findWorkflowSchemaError,
  validateOutputContract,
} from "./jsonSchemaValidation";

describe("validateOutputContract", () => {
  it("rejects unknown schema keywords", () => {
    expect(validateOutputContract('{"type":"object","foo":true}')).toContain(
      "unsupported keyword",
    );
  });

  it("rejects schema keywords that the backend does not accept", () => {
    expect(validateOutputContract('{"type":"object","definitions":{}}')).toContain(
      "unsupported keyword",
    );
    expect(validateOutputContract('{"type":"string","nullable":true}')).toContain(
      "unsupported keyword",
    );
  });

  it("rejects backend-equivalent schema complexity limits", () => {
    expect(validateOutputContract(JSON.stringify({
      type: "string",
      pattern: "x".repeat(MAX_SCHEMA_PATTERN_LENGTH + 1),
    }))).toContain("pattern length");
    expect(validateOutputContract(JSON.stringify({
      type: "object",
      anyOf: Array.from({ length: MAX_SCHEMA_NODES }, () => ({ type: "string" })),
    }))).toContain("schema node count");
  });

  it("finds invalid schemas before a workflow save", () => {
    expect(findWorkflowSchemaError([
      {
        id: "node-1",
        data: { label: "Output", outputContract: '{"type":"object","foo":true}' },
      },
    ])).toContain("unsupported keyword");
  });

  it("rejects schemas with an invalid JSON Schema type", () => {
    expect(validateOutputContract('{"type":"not-a-json-type"}')).toContain(
      "Invalid JSON Schema",
    );
  });

  it("accepts a valid output contract envelope", () => {
    expect(validateOutputContract('{"schema":{"type":"string"}}')).toBeNull();
  });

  it("accepts the common email format", () => {
    expect(
      validateJsonOutputSchema(
        '{"type":"object","properties":{"email":{"type":"string","format":"email"}},"required":["email"]}',
      ),
    ).toBeNull();
  });

  it("does not unwrap a schema sibling", () => {
    expect(
      validateOutputContract(
        '{"type":"object","properties":{"schema":{"type":"string"}}}',
      ),
    ).toBeNull();
  });

  it("rejects envelopes for provider-facing JSON output schemas", () => {
    expect(validateJsonOutputSchema('{"name":"output","schema":{"type":"string"}}'))
      .toContain("envelope");
  });

  it("rejects external refs, excessive depth, and oversized schemas", () => {
    expect(validateJsonOutputSchema('{"$dynamicRef":"https://example.com/schema"}'))
      .toContain("local");
    let deep: Record<string, unknown> = { type: "string" };
    for (let index = 0; index < 34; index += 1) {
      deep = { allOf: [deep] };
    }
    expect(validateJsonOutputSchema(JSON.stringify(deep))).toContain("nesting");
    expect(validateJsonOutputSchema(`"${"x".repeat(MAX_SCHEMA_BYTES)}"`)).toContain("byte");
  });

  it("rejects unknown formats", () => {
    expect(validateJsonOutputSchema(
      '{"type":"object","properties":{"value":{"type":"string","format":"custom-heym"}},"required":["value"]}',
    )).toContain("format");
  });

  it("rejects formats outside the backend allowlist", () => {
    for (const format of ["int32", "int64", "float", "double", "byte", "binary", "password"]) {
      expect(validateOutputContract(JSON.stringify({ type: "string", format }))).toContain(
        "unsupported format",
      );
    }
  });

  it("rejects oversized patternProperties regex keys", () => {
    expect(validateOutputContract(JSON.stringify({
      type: "object",
      patternProperties: { ["a".repeat(2049)]: { type: "string" } },
    }))).toContain("patternProperties key length");
  });

  it("rejects absolute schema ids", () => {
    expect(validateOutputContract('{"$id":"https://example.com/schema.json"}')).toContain(
      "local $id",
    );
  });

  it("rejects provider schemas that are not strict objects", () => {
    expect(validateJsonOutputSchema('{"type":"array"}')).toContain("root");
    expect(validateJsonOutputSchema(
      '{"type":"object","properties":{"value":{"type":"string"}},"required":[]}',
    )).toContain("required");
    expect(validateJsonOutputSchema(
      '{"type":"object","properties":{"value":{"type":"string"}},"required":["value","value"]}',
    )).toContain("required");
    expect(validateJsonOutputSchema(
      '{"type":"object","properties":{"value":{"type":"string"}},"required":["value"],"additionalProperties":true}',
    )).toContain("additionalProperties");
  });
});
