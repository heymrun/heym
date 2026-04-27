export interface WebhookInputField {
  key: string;
  defaultValue?: string;
}

export interface ParsedWebhookJson {
  error: string | null;
  value: unknown;
}

export function buildLegacyWebhookBody(
  fields: WebhookInputField[],
  values: Record<string, string>,
  fallbackText: string,
): Record<string, string> {
  const inputs: Record<string, string> = {};

  for (const field of fields) {
    inputs[field.key] = values[field.key] || field.defaultValue || "";
  }

  if (Object.keys(inputs).length === 0 && fallbackText.trim()) {
    inputs.text = fallbackText.trim();
  }

  return inputs;
}

export function parseWebhookJson(input: string): ParsedWebhookJson {
  const source = input.trim() === "" ? "{}" : input;

  try {
    return {
      error: null,
      value: JSON.parse(source) as unknown,
    };
  } catch {
    return {
      error: "Invalid JSON body.",
      value: {},
    };
  }
}

export function stringifyWebhookJson(value: unknown): string {
  try {
    const serialized = JSON.stringify(value ?? {}, null, 2);
    return serialized === undefined ? "{}" : serialized;
  } catch {
    return "{}";
  }
}

export function getHistoryWebhookBody(
  inputs: Record<string, unknown>,
): unknown {
  return Object.prototype.hasOwnProperty.call(inputs, "body")
    ? inputs.body
    : inputs;
}
