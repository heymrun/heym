import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  appendChatContext,
  CHAT_CONTEXT_DRAFT_EVENT,
  CHAT_CONTEXT_DRAFT_STORAGE_KEY,
  consumeChatContextDraft,
  extractChatContext,
  formatChatContextLabel,
  formatChatContextTitle,
  hasChatContextDraftPending,
  saveChatContextDraft,
  type ChatContextItem,
} from "@/lib/chatContext";

const WORKFLOW_ID = "9f1c2b7e-0d4a-4c1e-9b7a-1a2b3c4d5e6f";
const EXECUTION_ID = "3f2a91c4-77de-4b0a-8c1d-0e9f8a7b6c5d";

const workflowItem: ChatContextItem = {
  kind: "workflow",
  workflowId: WORKFLOW_ID,
  workflowName: "Lead details",
};
const executionItem: ChatContextItem = {
  kind: "execution",
  workflowId: WORKFLOW_ID,
  executionId: EXECUTION_ID,
};

describe("appendChatContext", () => {
  it("returns the text unchanged without items", () => {
    expect(appendChatContext("Why is it slow?", [])).toBe("Why is it slow?");
  });

  it("appends one line per item under the context header", () => {
    expect(appendChatContext("Why is it slow?", [workflowItem, executionItem])).toBe(
      [
        "Why is it slow?",
        "",
        "[HEYM CONTEXT]",
        `- Workflow: Lead details (workflow_id: ${WORKFLOW_ID})`,
        `- Execution: ${EXECUTION_ID} (workflow_id: ${WORKFLOW_ID})`,
      ].join("\n"),
    );
  });

  it("keeps the workflow id on the execution line when the workflow chip is removed", () => {
    expect(appendChatContext("What failed?", [executionItem])).toBe(
      `What failed?\n\n[HEYM CONTEXT]\n- Execution: ${EXECUTION_ID} (workflow_id: ${WORKFLOW_ID})`,
    );
  });

  it("collapses whitespace in workflow names so the block stays one line per item", () => {
    const content = appendChatContext("Q", [
      { ...workflowItem, workflowName: "  Lead\n details\t v2 " },
    ]);
    expect(content).toContain(`- Workflow: Lead details v2 (workflow_id: ${WORKFLOW_ID})`);
  });
});

describe("extractChatContext", () => {
  it("round-trips appended items", () => {
    const content = appendChatContext("Why is it slow?", [workflowItem, executionItem]);
    expect(extractChatContext(content)).toEqual({
      text: "Why is it slow?",
      items: [workflowItem, executionItem],
    });
  });

  it("reads the id from the last group when the name contains parentheses", () => {
    const named: ChatContextItem = {
      ...workflowItem,
      workflowName: "Leads (workflow_id: fake) copy",
    };
    expect(extractChatContext(appendChatContext("Q", [named])).items).toEqual([named]);
  });

  it("leaves content without a context block alone", () => {
    expect(extractChatContext("Plain question")).toEqual({ text: "Plain question", items: [] });
  });

  it("leaves a header without valid lines alone", () => {
    const content = "Q\n\n[HEYM CONTEXT]\n- Something else";
    expect(extractChatContext(content)).toEqual({ text: content, items: [] });
  });

  it("keeps content that follows the block", () => {
    const content = `${appendChatContext("Q", [executionItem])}\n\n[ATTACHED FILE: notes.txt]\nhello`;
    expect(extractChatContext(content)).toEqual({
      text: "Q\n\n[ATTACHED FILE: notes.txt]\nhello",
      items: [executionItem],
    });
  });
});

describe("chat context labels", () => {
  it("shows the workflow name and a short execution id", () => {
    expect(formatChatContextLabel(workflowItem)).toBe("Workflow: Lead details");
    expect(formatChatContextLabel(executionItem)).toBe("Execution: 3f2a91c4…");
  });

  it("puts the full values in the title", () => {
    expect(formatChatContextTitle(workflowItem)).toBe(`Lead details (${WORKFLOW_ID})`);
    expect(formatChatContextTitle(executionItem)).toBe(EXECUTION_ID);
  });
});

describe("chat context draft", () => {
  let storage: Map<string, string>;
  let dispatchEvent: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    storage = new Map();
    dispatchEvent = vi.fn();
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (key: string): string | null => storage.get(key) ?? null,
        setItem: (key: string, value: string): void => {
          storage.set(key, value);
        },
        removeItem: (key: string): void => {
          storage.delete(key);
        },
      },
      dispatchEvent,
    });
    vi.stubGlobal(
      "CustomEvent",
      class {
        type: string;
        constructor(type: string) {
          this.type = type;
        }
      },
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("saves, reports and consumes a draft once", () => {
    saveChatContextDraft([workflowItem, executionItem]);

    expect(dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: CHAT_CONTEXT_DRAFT_EVENT }),
    );
    expect(hasChatContextDraftPending()).toBe(true);
    expect(consumeChatContextDraft()).toEqual([workflowItem, executionItem]);
    expect(hasChatContextDraftPending()).toBe(false);
    expect(consumeChatContextDraft()).toEqual([]);
  });

  it("drops malformed storage", () => {
    storage.set(CHAT_CONTEXT_DRAFT_STORAGE_KEY, "{not json");
    expect(consumeChatContextDraft()).toEqual([]);

    storage.set(
      CHAT_CONTEXT_DRAFT_STORAGE_KEY,
      JSON.stringify([{ kind: "execution", workflowId: WORKFLOW_ID }, workflowItem, 42]),
    );
    expect(consumeChatContextDraft()).toEqual([workflowItem]);
    expect(storage.has(CHAT_CONTEXT_DRAFT_STORAGE_KEY)).toBe(false);
  });
});
