import { heymClientHeaders } from "@/constants/httpIdentity";

export interface SkillBuilderConversationMessage {
  role: "user" | "assistant";
  content: string;
}

export interface SkillBuilderFile {
  path: string;
  content: string;
}

export interface SkillBuilderExistingSkill {
  name: string;
  files: SkillBuilderFile[];
}

export interface SkillBuilderRequest {
  credentialId: string;
  model: string;
  message: string;
  existingSkill?: SkillBuilderExistingSkill;
  conversationHistory?: SkillBuilderConversationMessage[];
}

interface SkillBuilderEventPayload {
  type: string;
  content?: string;
  files?: SkillBuilderFile[];
  message?: string;
}

export function skillBuilderStream(
  request: SkillBuilderRequest,
  onChunk: (text: string) => void,
  onFilesUpdate: (files: SkillBuilderFile[]) => void,
  onDone: () => void,
  onError: (error: Error) => void,
  signal?: AbortSignal,
): void {
  const apiUrl = import.meta.env.VITE_API_URL || "";

  fetch(`${apiUrl}/api/ai/skill-builder`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...heymClientHeaders,
    },
    body: JSON.stringify({
      credential_id: request.credentialId,
      model: request.model,
      message: request.message,
      existing_skill: request.existingSkill ?? null,
      conversation_history: request.conversationHistory ?? [],
    }),
    signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(
          (errorData as { detail?: string }).detail ||
            `HTTP error! status: ${response.status}`,
        );
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = JSON.parse(line.slice(6)) as SkillBuilderEventPayload;

          if (data.type === "text_chunk" && typeof data.content === "string") {
            onChunk(data.content);
          } else if (data.type === "skill_files_update" && Array.isArray(data.files)) {
            onFilesUpdate(data.files);
          } else if (data.type === "done") {
            onDone();
          } else if (data.type === "error") {
            throw new Error(data.message ?? "Unknown skill builder error");
          }
        }
      }
    })
    .catch((error: unknown) => {
      onError(error instanceof Error ? error : new Error("Skill builder request failed"));
    });
}
