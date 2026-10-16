export interface RawToolCall {
  id?: string;
  type?: string;
  function?: { name?: string; arguments?: string };
}

export interface RawMessage {
  role?: string;
  content?: unknown;
  tool_calls?: RawToolCall[];
  tool_call_id?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function textOf(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value
      .map((part) => (isRecord(part) && typeof part.text === "string" ? part.text : ""))
      .filter((part) => part !== "")
      .join("\n");
  }
  if (value == null) return "";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function jsonText(value: unknown): string {
  try {
    return JSON.stringify(value ?? {});
  } catch {
    return "{}";
  }
}

/**
 * Anthropic Messages requests keep `system` beside the messages, carry tool calls as
 * `tool_use` blocks and tool results as `tool_result` blocks inside a user message.
 */
function fromAnthropicMessages(request: Record<string, unknown>): RawMessage[] {
  const out: RawMessage[] = [];
  if (typeof request.system === "string" && request.system) {
    out.push({ role: "system", content: request.system });
  }
  const messages = Array.isArray(request.messages) ? request.messages : [];
  for (const message of messages) {
    if (!isRecord(message)) continue;
    const role = typeof message.role === "string" ? message.role : undefined;
    if (!Array.isArray(message.content)) {
      out.push({ role, content: message.content });
      continue;
    }
    const texts: string[] = [];
    const toolCalls: RawToolCall[] = [];
    const results: RawMessage[] = [];
    for (const block of message.content) {
      if (!isRecord(block)) continue;
      if (block.type === "text" && typeof block.text === "string") {
        texts.push(block.text);
      } else if (block.type === "image") {
        texts.push("[image]");
      } else if (block.type === "tool_use") {
        toolCalls.push({
          id: typeof block.id === "string" ? block.id : undefined,
          type: "function",
          function: {
            name: typeof block.name === "string" ? block.name : undefined,
            arguments: jsonText(block.input),
          },
        });
      } else if (block.type === "tool_result") {
        results.push({
          role: "tool",
          tool_call_id: typeof block.tool_use_id === "string" ? block.tool_use_id : undefined,
          content: textOf(block.content),
        });
      }
    }
    if (role === "assistant") {
      out.push({
        role,
        content: texts.join("\n"),
        ...(toolCalls.length > 0 ? { tool_calls: toolCalls } : {}),
      });
    } else {
      out.push(...results);
      if (texts.length > 0) out.push({ role, content: texts.join("\n") });
    }
  }
  return out;
}

/** Gemini keeps `system` beside `contents`; calls and results are `functionCall` and `functionResponse` parts. */
function fromGeminiContents(request: Record<string, unknown>): RawMessage[] {
  const out: RawMessage[] = [];
  if (typeof request.system === "string" && request.system) {
    out.push({ role: "system", content: request.system });
  }
  const contents = Array.isArray(request.contents) ? request.contents : [];
  for (const content of contents) {
    if (!isRecord(content)) continue;
    const isModel = content.role === "model";
    const texts: string[] = [];
    const toolCalls: RawToolCall[] = [];
    const results: RawMessage[] = [];
    for (const part of Array.isArray(content.parts) ? content.parts : []) {
      if (!isRecord(part)) continue;
      if (typeof part.text === "string" && part.thought !== true) {
        texts.push(part.text);
      } else if (isRecord(part.inlineData) || isRecord(part.fileData)) {
        texts.push("[image]");
      } else if (isRecord(part.functionCall)) {
        toolCalls.push({
          id: typeof part.functionCall.id === "string" ? part.functionCall.id : undefined,
          type: "function",
          function: {
            name: typeof part.functionCall.name === "string" ? part.functionCall.name : undefined,
            arguments: jsonText(part.functionCall.args),
          },
        });
      } else if (isRecord(part.functionResponse)) {
        const response = part.functionResponse.response;
        const onlyResult = isRecord(response) && typeof response.result === "string";
        results.push({
          role: "tool",
          tool_call_id: typeof part.functionResponse.id === "string" ? part.functionResponse.id : undefined,
          content: onlyResult ? (response as { result: string }).result : jsonText(response),
        });
      }
    }
    if (isModel) {
      out.push({
        role: "assistant",
        content: texts.join("\n"),
        ...(toolCalls.length > 0 ? { tool_calls: toolCalls } : {}),
      });
    } else {
      out.push(...results);
      if (texts.length > 0) out.push({ role: "user", content: texts.join("\n") });
    }
  }
  return out;
}

/** Responses requests are a flat list of items: messages, function calls and their outputs. */
function fromResponsesInput(request: Record<string, unknown>): RawMessage[] {
  const out: RawMessage[] = [];
  const items = Array.isArray(request.input) ? request.input : [];
  let openCalls: RawToolCall[] | null = null;
  for (const item of items) {
    if (!isRecord(item)) continue;
    if (item.type === "function_call") {
      const call: RawToolCall = {
        id: typeof item.call_id === "string" ? item.call_id : undefined,
        type: "function",
        function: {
          name: typeof item.name === "string" ? item.name : undefined,
          arguments: typeof item.arguments === "string" ? item.arguments : jsonText(item.arguments),
        },
      };
      if (openCalls === null) {
        openCalls = [call];
        out.push({ role: "assistant", content: "", tool_calls: openCalls });
      } else {
        openCalls.push(call);
      }
      continue;
    }
    openCalls = null;
    if (item.type === "function_call_output") {
      out.push({
        role: "tool",
        tool_call_id: typeof item.call_id === "string" ? item.call_id : undefined,
        content: textOf(item.output),
      });
    } else if (typeof item.role === "string") {
      out.push({ role: item.role, content: textOf(item.content) });
    }
  }
  return out;
}

/**
 * The conversation a trace recorded, in the chat shape the step builder reads, whichever
 * endpoint the call went to. Chat Completions requests already have it.
 */
export function readRequestMessages(
  requestType: string | null | undefined,
  request: Record<string, unknown>,
): RawMessage[] {
  if (requestType === "messages") return fromAnthropicMessages(request);
  if (requestType === "generateContent") return fromGeminiContents(request);
  if (requestType === "responses" || (!Array.isArray(request.messages) && Array.isArray(request.input))) {
    return fromResponsesInput(request);
  }
  return Array.isArray(request.messages) ? (request.messages as RawMessage[]) : [];
}
