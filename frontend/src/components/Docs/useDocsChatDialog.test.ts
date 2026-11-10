import { nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDocsChatDialog } from "@/components/Docs/useDocsChatDialog";
import { aiApi } from "@/services/api";

vi.mock("vue", async (importOriginal) => ({
  ...await importOriginal<typeof import("vue")>(),
  onUnmounted: vi.fn(),
}));
vi.mock("@/composables/useAiDefaults", () => ({ useAiDefaults: vi.fn(() => ({})) }));
vi.mock("@/services/api", () => ({
  aiApi: { dashboardChatStream: vi.fn() },
  credentialsApi: { getModels: vi.fn(async () => []) },
}));

describe("documentation chat conversation identity", () => {
  beforeEach(() => vi.clearAllMocks());

  it("preserves the session for followups and rotates it when cleared", async () => {
    const chat = useDocsChatDialog({ open: false, docPath: "nodes/llm" }, vi.fn());
    chat.selectedCredentialId.value = "credential";
    await nextTick();
    chat.selectedModel.value = "model";
    chat.inputText.value = "Explain this node";
    chat.handleSubmit();
    const stream = vi.mocked(aiApi.dashboardChatStream);
    const first = stream.mock.calls[0];
    expect(first[0].conversationId).toBeTruthy();
    expect(first[0].chatSurface).toBe("documentation");
    expect(first[0].userRules).toContain("/docs/nodes/llm");
    first[2]();
    await nextTick();
    chat.inputText.value = "Give an example";
    chat.handleSubmit();
    expect(stream.mock.calls[1][0].conversationId).toBe(first[0].conversationId);
    chat.clearChat();
    chat.inputText.value = "New question";
    chat.handleSubmit();
    expect(stream.mock.calls[2][0].conversationId).not.toBe(first[0].conversationId);
    chat.handleClose();
  });
});
