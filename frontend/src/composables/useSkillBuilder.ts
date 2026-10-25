import { ref } from "vue";

import type {
  SkillBuilderConversationMessage,
  SkillBuilderAttachment,
  SkillBuilderExistingSkill,
  SkillBuilderFile,
} from "@/services/skillBuilderApi";
import { skillBuilderStream } from "@/services/skillBuilderApi";
import { randomUUID } from "@/lib/uuid";

export interface SkillBuilderChatMessage {
  role: "user" | "assistant";
  content: string;
}

export function useSkillBuilder() {
  const messages = ref<SkillBuilderChatMessage[]>([]);
  const currentFiles = ref<SkillBuilderFile[]>([]);
  const isStreaming = ref(false);
  const error = ref<string | null>(null);
  const hasFilesUpdate = ref(false);
  const abortController = ref<AbortController | null>(null);
  const conversationHistory = ref<SkillBuilderConversationMessage[]>([]);
  const conversationId = ref(randomUUID());

  function reset(): void {
    abortController.value?.abort();
    abortController.value = null;
    messages.value = [];
    currentFiles.value = [];
    isStreaming.value = false;
    error.value = null;
    hasFilesUpdate.value = false;
    conversationHistory.value = [];
    conversationId.value = randomUUID();
  }

  function initialize(greeting: string, previewFiles: SkillBuilderFile[] = []): void {
    messages.value = [{ role: "assistant", content: greeting }];
    currentFiles.value = previewFiles;
  }

  function sendMessage(
    text: string,
    credentialId: string,
    model: string,
    existingSkill?: SkillBuilderExistingSkill,
    attachments: SkillBuilderAttachment[] = [],
  ): void {
    const trimmed = text.trim();
    if (!trimmed || isStreaming.value) {
      return;
    }

    messages.value = [
      ...messages.value,
      { role: "user", content: trimmed },
      { role: "assistant", content: "" },
    ];
    const assistantIndex = messages.value.length - 1;
    let assistantContent = "";

    isStreaming.value = true;
    error.value = null;
    abortController.value = new AbortController();

    skillBuilderStream(
      {
        credentialId,
        model,
        message: trimmed,
        attachments,
        existingSkill,
        conversationHistory: conversationHistory.value,
        conversationId: conversationId.value,
      },
      (chunk) => {
        assistantContent += chunk;
        messages.value[assistantIndex] = {
          ...messages.value[assistantIndex],
          content: assistantContent,
        };
      },
      (files) => {
        currentFiles.value = files;
        hasFilesUpdate.value = true;
      },
      () => {
        if (!assistantContent && hasFilesUpdate.value) {
          assistantContent = "Updated the skill files.";
          messages.value[assistantIndex] = {
            ...messages.value[assistantIndex],
            content: assistantContent,
          };
        }

        conversationHistory.value = [
          ...conversationHistory.value,
          { role: "user", content: trimmed },
          { role: "assistant", content: assistantContent },
        ];
        isStreaming.value = false;
        abortController.value = null;
      },
      (streamError) => {
        if (streamError.name === "AbortError") {
          isStreaming.value = false;
          abortController.value = null;
          return;
        }

        error.value = streamError.message;
        isStreaming.value = false;
        abortController.value = null;

        if (!assistantContent) {
          messages.value.splice(assistantIndex, 1);
        }
      },
      abortController.value.signal,
    );
  }

  return {
    currentFiles,
    error,
    hasFilesUpdate,
    initialize,
    isStreaming,
    messages,
    reset,
    sendMessage,
  };
}
