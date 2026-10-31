import type { ChatLiveEvent, ToolCall } from "@/types/chat";

/** What a running chat turn shows before its answer: the text being written and a progress line. */
export interface ChatLiveState {
  draft: string;
  draftRound: number;
  progress: string | null;
  toolCalls: ToolCall[];
}

/** The live state after one `draft`, `progress` or `tool_progress` event. */
export function applyChatLiveEvent<T extends ChatLiveState>(state: T, event: ChatLiveEvent): T {
  if (event.type === "draft") {
    // Each model round writes a new draft; text from an earlier round was its narration.
    const draft = event.round === state.draftRound ? state.draft + event.text : event.text;
    return { ...state, draft, draftRound: event.round };
  }
  if (event.type === "progress") {
    return { ...state, progress: event.message };
  }
  return {
    ...state,
    toolCalls: state.toolCalls.map((call) =>
      call.id === event.id ? { ...call, progress: event.message } : call,
    ),
  };
}

/** The draft as shown: a questions block becomes its card once the turn ends, so it is cut. */
export function visibleDraft(draft: string): string {
  const at = draft.indexOf("```heym-clarify");
  return (at >= 0 ? draft.slice(0, at) : draft).trimEnd();
}
