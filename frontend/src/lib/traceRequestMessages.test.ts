import { describe, expect, it } from "vitest";

import { readRequestMessages } from "@/lib/traceRequestMessages";
import { buildTraceSteps } from "@/lib/traceSteps";
import type { LLMTraceDetail } from "@/types/trace";

function makeTrace(
  requestType: string,
  request: Record<string, unknown>,
  response: Record<string, unknown> = { text: "done", elapsed_ms: 10 },
): LLMTraceDetail {
  return {
    id: "trace-1",
    created_at: "2026-10-16T00:00:00Z",
    source: "workflow",
    request_type: requestType,
    provider: "Custom",
    model: "m",
    credential_id: null,
    credential_name: null,
    workflow_id: null,
    workflow_name: null,
    node_id: "agent-1",
    node_label: "Agent",
    status: "success",
    elapsed_ms: 10,
    prompt_tokens: 1,
    completion_tokens: 1,
    total_tokens: 2,
    cost_usd: null,
    is_priced: false,
    request,
    response,
    error: null,
  };
}

const MESSAGES_REQUEST = {
  system: "be brief",
  messages: [
    { role: "user", content: "Domain: talanoa.email" },
    {
      role: "assistant",
      content: [
        { type: "thinking", thinking: "", signature: "sig" },
        { type: "text", text: "Checking." },
        { type: "tool_use", id: "tu_1", name: "load", input: { url: "https://talanoa.email" } },
        { type: "tool_use", id: "tu_2", name: "load", input: { url: "https://talanoa.email/terms" } },
      ],
    },
    {
      role: "user",
      content: [
        { type: "tool_result", tool_use_id: "tu_1", content: "home page" },
        { type: "tool_result", tool_use_id: "tu_2", content: "terms page" },
      ],
    },
  ],
};

const RESPONSES_REQUEST = {
  input: [
    { type: "message", role: "system", content: "be brief" },
    { type: "message", role: "user", content: "Domain: talanoa.email" },
    { type: "reasoning", id: "rs_1", summary: [], encrypted_content: "blob" },
    { type: "function_call", call_id: "c1", name: "load", arguments: '{"url":"a"}' },
    { type: "function_call", call_id: "c2", name: "load", arguments: '{"url":"b"}' },
    { type: "function_call_output", call_id: "c1", output: "page a" },
    { type: "function_call_output", call_id: "c2", output: "page b" },
  ],
  tools: [],
};

describe("readRequestMessages", () => {
  it("leaves chat completions messages untouched", () => {
    const messages = [{ role: "user", content: "hi" }];
    expect(readRequestMessages("chat.completions", { messages })).toBe(messages);
  });

  it("turns the system field into a system message", () => {
    const messages = readRequestMessages("messages", MESSAGES_REQUEST);
    expect(messages[0]).toEqual({ role: "system", content: "be brief" });
  });

  it("reads tool_use blocks as tool calls and drops thinking blocks", () => {
    const messages = readRequestMessages("messages", MESSAGES_REQUEST);
    const assistant = messages.find((m) => m.role === "assistant");
    expect(assistant?.content).toBe("Checking.");
    expect(assistant?.tool_calls).toEqual([
      {
        id: "tu_1",
        type: "function",
        function: { name: "load", arguments: '{"url":"https://talanoa.email"}' },
      },
      {
        id: "tu_2",
        type: "function",
        function: { name: "load", arguments: '{"url":"https://talanoa.email/terms"}' },
      },
    ]);
  });

  it("reads tool_result blocks as tool messages, not as an empty user turn", () => {
    const messages = readRequestMessages("messages", MESSAGES_REQUEST);
    expect(messages.filter((m) => m.role === "tool")).toEqual([
      { role: "tool", tool_call_id: "tu_1", content: "home page" },
      { role: "tool", tool_call_id: "tu_2", content: "terms page" },
    ]);
    expect(messages.filter((m) => m.role === "user")).toHaveLength(1);
  });

  it("keeps text that sits next to tool results as a user message", () => {
    const messages = readRequestMessages("messages", {
      messages: [
        {
          role: "user",
          content: [
            { type: "tool_result", tool_use_id: "tu_1", content: "ok" },
            { type: "text", text: "and now continue" },
          ],
        },
      ],
    });
    expect(messages.map((m) => m.role)).toEqual(["tool", "user"]);
    expect(messages[1].content).toBe("and now continue");
  });

  it("reads responses input items, grouping consecutive calls into one assistant turn", () => {
    const messages = readRequestMessages("responses", RESPONSES_REQUEST);
    expect(messages.map((m) => m.role)).toEqual(["system", "user", "assistant", "tool", "tool"]);
    expect(messages[2].tool_calls?.map((tc) => tc.id)).toEqual(["c1", "c2"]);
    expect(messages[3]).toEqual({ role: "tool", tool_call_id: "c1", content: "page a" });
  });

  it("reads output_text parts of responses messages", () => {
    const messages = readRequestMessages("responses", {
      input: [{ type: "message", role: "assistant", content: [{ type: "output_text", text: "hi" }] }],
    });
    expect(messages).toEqual([{ role: "assistant", content: "hi" }]);
  });

  it("falls back to whatever messages the request carries", () => {
    expect(readRequestMessages("responses", {})).toEqual([]);
  });
});

describe("buildTraceSteps for the messages and responses transports", () => {
  it("shows tool calls with their results and no empty user rows for Claude traces", () => {
    const steps = buildTraceSteps(makeTrace("messages", MESSAGES_REQUEST));
    expect(steps.map((s) => s.kind)).toEqual([
      "system",
      "user",
      "assistant",
      "tool",
      "tool",
      "answer",
    ]);
    const tools = steps.filter((s) => s.kind === "tool");
    expect(tools[0].resultText).toBe("home page");
    expect(tools[1].resultText).toBe("terms page");
    expect(steps.every((s) => s.kind !== "user" || s.summary !== "")).toBe(true);
  });

  it("shows a conversation for responses traces instead of a raw request dump", () => {
    const steps = buildTraceSteps(makeTrace("responses", RESPONSES_REQUEST));
    expect(steps.map((s) => s.kind)).toEqual([
      "system",
      "user",
      "tool",
      "tool",
      "answer",
    ]);
    expect(steps.filter((s) => s.kind === "tool").map((s) => s.resultText)).toEqual([
      "page a",
      "page b",
    ]);
  });
});


describe("auto fixed JSON replies in the steps view", () => {
  const REPAIR_PROMPT =
    "Your previous reply could not be used: 'name' is a required property. Reply again with only the corrected JSON object.";

  function repairedTrace(): LLMTraceDetail {
    return makeTrace(
      "chat.completions",
      {
        messages: [
          { role: "user", content: "Anna is 31" },
          { role: "assistant", content: "Sure, here it is" },
          { role: "user", content: REPAIR_PROMPT },
        ],
      },
      { text: '{"name":"Anna"}', elapsed_ms: 10, json_repairs: ["'name' is a required property"] },
    );
  }

  it("badges the answer with how many times the reply was fixed", () => {
    const answer = buildTraceSteps(repairedTrace()).find((step) => step.kind === "answer");
    expect(answer?.badges?.map((badge) => badge.label)).toContain("JSON auto-fixed ×1");
  });

  it("keeps the rejection reasons in the answer's event JSON", () => {
    const answer = buildTraceSteps(repairedTrace()).find((step) => step.kind === "answer");
    expect((answer?.json as { json_repairs?: string[] }).json_repairs).toEqual([
      "'name' is a required property",
    ]);
  });

  it("names the repair request as an auto fix instead of a plain user turn", () => {
    const steps = buildTraceSteps(repairedTrace());
    const repair = steps.find((step) => step.summary.startsWith("Your previous reply"));
    expect(repair?.roleLabel).toBe("User · auto fix");
    expect(repair?.badges?.map((badge) => badge.label)).toContain("Auto fix");
    expect(steps[0].roleLabel).toBe("User");
  });

  it("adds nothing for a reply that needed no fixing", () => {
    const steps = buildTraceSteps(makeTrace("chat.completions", { messages: [{ role: "user", content: "hi" }] }));
    expect(steps.find((step) => step.kind === "answer")?.badges).toBeUndefined();
  });
});


const GEMINI_REQUEST = {
  system: "be brief",
  contents: [
    { role: "user", parts: [{ text: "Domain: talanoa.email" }] },
    {
      role: "model",
      parts: [
        { text: "Checking.", thought: false },
        { thoughtSignature: "sig", functionCall: { id: "c1", name: "load", args: { url: "a" } } },
        { functionCall: { id: "c2", name: "load", args: { url: "b" } } },
      ],
    },
    {
      role: "user",
      parts: [
        { functionResponse: { id: "c1", name: "load", response: { result: "page a" } } },
        { functionResponse: { id: "c2", name: "load", response: { status: "success", n: 2 } } },
      ],
    },
  ],
  tools: [],
};

describe("gemini generateContent traces", () => {
  it("turns system and model turns into chat messages", () => {
    const messages = readRequestMessages("generateContent", GEMINI_REQUEST);
    expect(messages[0]).toEqual({ role: "system", content: "be brief" });
    const assistant = messages.find((m) => m.role === "assistant");
    expect(assistant?.content).toBe("Checking.");
    expect(assistant?.tool_calls).toEqual([
      { id: "c1", type: "function", function: { name: "load", arguments: '{"url":"a"}' } },
      { id: "c2", type: "function", function: { name: "load", arguments: '{"url":"b"}' } },
    ]);
  });

  it("reads function responses as tool messages, not as an empty user turn", () => {
    const messages = readRequestMessages("generateContent", GEMINI_REQUEST);
    expect(messages.filter((m) => m.role === "tool")).toEqual([
      { role: "tool", tool_call_id: "c1", content: "page a" },
      { role: "tool", tool_call_id: "c2", content: '{"status":"success","n":2}' },
    ]);
    expect(messages.filter((m) => m.role === "user")).toHaveLength(1);
  });

  it("marks images and keeps thought summaries out of the text", () => {
    const messages = readRequestMessages("generateContent", {
      contents: [
        {
          role: "user",
          parts: [{ text: "what is this" }, { inlineData: { mimeType: "image/png", data: "[base64]" } }],
        },
        { role: "model", parts: [{ text: "internal", thought: true }, { text: "Coral" }] },
      ],
    });
    expect(messages[0].content).toBe("what is this\n[image]");
    expect(messages[1].content).toBe("Coral");
  });

  it("gives the steps view a conversation with tool results", () => {
    const steps = buildTraceSteps(makeTrace("generateContent", GEMINI_REQUEST));
    expect(steps.map((s) => s.kind)).toEqual(["system", "user", "assistant", "tool", "tool", "answer"]);
    expect(steps.filter((s) => s.kind === "tool").map((s) => s.resultText)).toEqual([
      "page a",
      '{"status":"success","n":2}',
    ]);
  });
});
