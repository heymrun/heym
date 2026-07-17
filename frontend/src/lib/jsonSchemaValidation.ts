import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import vocabulary from "./jsonSchemaVocabulary.json";

const ajv = new Ajv2020({ allErrors: false, strict: true });
addFormats(ajv);
export const MAX_SCHEMA_BYTES = 128 * 1024;
export const MAX_SCHEMA_DEPTH = 32;
export const MAX_SCHEMA_NODES = 4096;
export const MAX_SCHEMA_PATTERN_LENGTH = 2048;
const REF_KEYWORDS = new Set(["$ref", "$dynamicRef", "$recursiveRef"]);
const ENVELOPE_KEYS = new Set(["name", "schema", "strict", "description"]);
const SUPPORTED_FORMATS = new Set(vocabulary.formats);
const SUPPORTED_SCHEMA_KEYWORDS = new Set(vocabulary.keywords);
const SCHEMA_MAP_KEYWORDS = new Set(vocabulary.mapKeywords);
const SCHEMA_CHILD_KEYWORDS = new Set(vocabulary.childKeywords);
const SCHEMA_LIST_KEYWORDS = new Set(vocabulary.listKeywords);

export interface JsonSchemaValidationOptions {
  allowEnvelope?: boolean;
  fieldName?: string;
  providerStrict?: boolean;
}

export interface WorkflowSchemaNode {
  id?: string;
  data?: {
    label?: string;
    outputContract?: string;
    jsonOutputSchema?: string;
    jsonOutputEnabled?: boolean;
  };
}

function isSchemaObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isEnvelope(value: Record<string, unknown>): boolean {
  return Object.prototype.hasOwnProperty.call(value, "schema")
    && Object.keys(value).every((key) => ENVELOPE_KEYS.has(key));
}

function isLocalSchemaId(value: unknown): boolean {
  if (typeof value !== "string" || value.startsWith("//")) return false;
  const scheme = value.match(/^[A-Za-z][A-Za-z0-9+.-]*:/)?.[0].slice(0, -1);
  return !scheme || scheme === "urn";
}

function validateSafety(
  value: unknown,
  depth: number,
  fieldName: string,
  state: { nodes: number },
): string | null {
  state.nodes += 1;
  if (state.nodes > MAX_SCHEMA_NODES) {
    return `${fieldName} exceeds the maximum schema node count.`;
  }
  if (depth > MAX_SCHEMA_DEPTH) {
    return `${fieldName} exceeds the maximum nesting depth.`;
  }
  if (Array.isArray(value)) {
    for (const child of value) {
      const error = validateSafety(child, depth + 1, fieldName, state);
      if (error) return error;
    }
    return null;
  }
  if (!isSchemaObject(value)) return null;

  const pattern = value.pattern;
  if (typeof pattern === "string" && pattern.length > MAX_SCHEMA_PATTERN_LENGTH) {
    return `${fieldName} pattern length exceeds the maximum pattern length.`;
  }

  for (const keyword of REF_KEYWORDS) {
    if (!Object.prototype.hasOwnProperty.call(value, keyword)) continue;
    const ref = value[keyword];
    if (typeof ref !== "string") {
      return `${fieldName} ${keyword} must be a string.`;
    }
    if (!ref.startsWith("#")) {
      return `${fieldName} may only use local ${keyword} values.`;
    }
  }
  for (const child of Object.values(value)) {
    const error = validateSafety(child, depth + 1, fieldName, state);
    if (error) return error;
  }
  return null;
}

function validateSchemaKeywords(value: unknown, fieldName: string): string | null {
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const error = validateSchemaKeywords(value[index], `${fieldName}[${index}]`);
      if (error) return error;
    }
    return null;
  }
  if (!isSchemaObject(value)) return null;
  if (Object.prototype.hasOwnProperty.call(value, "$id") && !isLocalSchemaId(value.$id)) {
    return `${fieldName} may only use local $id values.`;
  }
  if (Object.prototype.hasOwnProperty.call(value, "format")) {
    if (typeof value.format !== "string" || !SUPPORTED_FORMATS.has(value.format)) {
      return `${fieldName} contains unsupported format '${String(value.format)}'.`;
    }
  }
  for (const [keyword, child] of Object.entries(value)) {
    if (!SUPPORTED_SCHEMA_KEYWORDS.has(keyword)) {
      return `${fieldName} contains unsupported keyword '${keyword}'.`;
    }
    if (SCHEMA_MAP_KEYWORDS.has(keyword) && isSchemaObject(child)) {
      for (const [name, schema] of Object.entries(child)) {
        if (keyword === "patternProperties" && name.length > MAX_SCHEMA_PATTERN_LENGTH) {
          return `${fieldName} patternProperties key length exceeds the maximum pattern length.`;
        }
        const error = validateSchemaKeywords(schema, `${fieldName}.${keyword}.${name}`);
        if (error) return error;
      }
    } else if (SCHEMA_CHILD_KEYWORDS.has(keyword)) {
      const error = validateSchemaKeywords(child, `${fieldName}.${keyword}`);
      if (error) return error;
    } else if (SCHEMA_LIST_KEYWORDS.has(keyword) && Array.isArray(child)) {
      for (let index = 0; index < child.length; index += 1) {
        const error = validateSchemaKeywords(child[index], `${fieldName}.${keyword}[${index}]`);
        if (error) return error;
      }
    }
  }
  return null;
}

function validateProviderConstraints(value: unknown, path = "root"): string | null {
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const error = validateProviderConstraints(value[index], path + "[" + index + "]");
      if (error) return error;
    }
    return null;
  }
  if (!isSchemaObject(value)) return null;

  const properties = value.properties;
  if (value.type === "object" || isSchemaObject(properties)) {
    if (properties !== undefined && !isSchemaObject(properties)) {
      return "JSON output schema properties at " + path + " must be an object.";
    }
    if (value.additionalProperties !== undefined && value.additionalProperties !== false) {
      return "JSON output schema additionalProperties at " + path + " must be false or omitted.";
    }
    const propertyNames = Object.keys(isSchemaObject(properties) ? properties : {});
    const required = value.required;
    if (!Array.isArray(required) || new Set(required).size !== required.length
      || required.length !== propertyNames.length
      || required.some((name) => typeof name !== "string" || !propertyNames.includes(name))) {
      return "JSON output schema at " + path + " must list every property in required.";
    }
  }

  for (const [key, child] of Object.entries(value)) {
    const error = validateProviderConstraints(child, path + "." + key);
    if (error) return error;
  }
  return null;
}

/** Validate a JSON Schema string; return a user-facing error or null. */
export function validateJsonSchema(
  value: string,
  options: JsonSchemaValidationOptions = {},
): string | null {
  const {
    allowEnvelope = false,
    fieldName = "JSON Schema",
    providerStrict = false,
  } = options;
  if (new TextEncoder().encode(value).byteLength > MAX_SCHEMA_BYTES) {
    return `${fieldName} exceeds the ${MAX_SCHEMA_BYTES} byte limit.`;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return `${fieldName} must contain valid JSON.`;
  }
  if (!isSchemaObject(parsed)) {
    return `${fieldName} must be a JSON object.`;
  }

  let schema: unknown = parsed;
  if (isEnvelope(parsed)) {
    if (!allowEnvelope) {
      return `${fieldName} envelope is not supported.`;
    }
    if (!isSchemaObject(parsed.schema)) {
      return `${fieldName} envelope 'schema' must be a JSON object.`;
    }
    schema = parsed.schema;
  }

  const keywordError = validateSchemaKeywords(schema, fieldName);
  if (keywordError) return keywordError;
  const safetyError = validateSafety(schema, 0, fieldName, { nodes: 0 });
  if (safetyError) return safetyError;
  if (providerStrict) {
    if (!isSchemaObject(schema) || schema.type !== "object") {
      return fieldName + " root must be an object for strict output.";
    }
    const providerError = validateProviderConstraints(schema);
    if (providerError) return providerError;
  }

  try {
    ajv.compile(schema as Record<string, unknown>);
    return null;
  } catch (error: unknown) {
    return `Invalid JSON Schema: ${error instanceof Error ? error.message : "unknown error"}`;
  }
}

/** Validate an output contract, which supports the legacy envelope format. */
export function validateOutputContract(value: string): string | null {
  return validateJsonSchema(value, { allowEnvelope: true, fieldName: "Contract" });
}

/** Validate a provider-facing structured-output schema without an envelope. */
export function validateJsonOutputSchema(value: string): string | null {
  return validateJsonSchema(value, {
    fieldName: "JSON output schema",
    providerStrict: true,
  });
}

/** Return the first schema error that would make a workflow save invalid. */
export function findWorkflowSchemaError(
  nodes: readonly WorkflowSchemaNode[],
): string | null {
  for (const node of nodes) {
    const label = node.data?.label || node.id || "node";
    const outputContract = node.data?.outputContract?.trim();
    if (outputContract) {
      const error = validateOutputContract(outputContract);
      if (error) return `Output contract for '${label}': ${error}`;
    }
    const jsonOutputSchema = node.data?.jsonOutputSchema?.trim();
    if (jsonOutputSchema) {
      const error = node.data?.jsonOutputEnabled
        ? validateJsonOutputSchema(jsonOutputSchema)
        : validateJsonSchema(jsonOutputSchema, { fieldName: "JSON output schema" });
      if (error) return `JSON output schema for '${label}': ${error}`;
    }
  }
  return null;
}
