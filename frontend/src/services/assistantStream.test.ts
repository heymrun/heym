import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssistantToolEndEvent, AssistantToolStartEvent } from "@/services/api";

import { aiApi } from "@/services/api";

function sseResponse(events: Record<string, unknown>[]): Response {
  const body = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("aiApi.assistantStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends yolo_mode and reports tool steps to the handlers", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      sseResponse([
        {
          type: "tool_start",
          id: "call-1",
          name: "execute_workflow",
          label: 'Running workflow "Lookup"...',
          args: { workflow_id: "wf-1" },
        },
        {
          type: "tool_end",
          id: "call-1",
          response_summary: "Status: success",
          elapsed_ms: 12,
          status: "success",
        },
        { type: "content", text: "Done" },
        { type: "done" },
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const starts: AssistantToolStartEvent[] = [];
    const ends: AssistantToolEndEvent[] = [];
    const content: string[] = [];

    await new Promise<void>((resolve, reject) => {
      aiApi.assistantStream(
        { credentialId: "cred", model: "model", message: "hi", yoloMode: true },
        (text) => content.push(text),
        resolve,
        reject,
        undefined,
        {
          onToolStart: (event) => starts.push(event),
          onToolEnd: (event) => ends.push(event),
        },
      );
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body)) as Record<string, unknown>;
    expect(body.yolo_mode).toBe(true);
    expect(starts).toEqual([
      {
        id: "call-1",
        name: "execute_workflow",
        label: 'Running workflow "Lookup"...',
        args: { workflow_id: "wf-1" },
      },
    ]);
    expect(ends).toEqual([
      { id: "call-1", response_summary: "Status: success", elapsed_ms: 12, status: "success" },
    ]);
    expect(content).toEqual(["Done"]);
  });

  it("leaves yolo_mode out of a normal request", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      sseResponse([{ type: "done" }]),
    );
    vi.stubGlobal("fetch", fetchMock);

    await new Promise<void>((resolve, reject) => {
      aiApi.assistantStream(
        { credentialId: "cred", model: "model", message: "hi" },
        () => undefined,
        resolve,
        reject,
      );
    });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body)) as Record<string, unknown>;
    expect(body).not.toHaveProperty("yolo_mode");
  });
});
