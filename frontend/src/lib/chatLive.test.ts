import { describe, expect, it } from "vitest";

import type { ToolCall } from "@/types/chat";
import { applyChatLiveEvent, visibleDraft } from "@/lib/chatLive";

const running: ToolCall = { id: "call_1", name: "execute_workflow", label: "Running", args: {}, status: "running" };

describe("applyChatLiveEvent", () => {
  it("appends drafts of one round and starts over on the next", () => {
    let state = { draft: "", draftRound: 0, progress: null as string | null, toolCalls: [running] };
    state = applyChatLiveEvent(state, { type: "draft", round: 1, text: "Let me " });
    state = applyChatLiveEvent(state, { type: "draft", round: 1, text: "check." });
    expect(state.draft).toBe("Let me check.");
    state = applyChatLiveEvent(state, { type: "draft", round: 2, text: "You have" });
    expect(state.draft).toBe("You have");
    expect(state.draftRound).toBe(2);
  });

  it("keeps the progress line and puts tool progress on its step", () => {
    let state = { draft: "", draftRound: 0, progress: null as string | null, toolCalls: [running] };
    state = applyChatLiveEvent(state, { type: "progress", round: 1, message: 'Writing "Digest"' });
    state = applyChatLiveEvent(state, { type: "tool_progress", id: "call_1", message: "Running node Fetch" });
    expect(state.progress).toBe('Writing "Digest"');
    expect(state.toolCalls[0].progress).toBe("Running node Fetch");
  });
});

describe("visibleDraft", () => {
  it("cuts a questions block that is still being written", () => {
    expect(visibleDraft('A few questions:\n\n```heym-clarify\n{"questions": [')).toBe("A few questions:");
    expect(visibleDraft("Plain text")).toBe("Plain text");
  });
});
