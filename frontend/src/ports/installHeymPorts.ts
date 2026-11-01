import type { App } from "vue";
import type { Router } from "vue-router";
import axios from "axios";

import { useClarifyDataTables } from "@/composables/useClarifyDataTables";
import { useInteractiveVoice } from "@/composables/useInteractiveVoice";
import { useTextToSpeech } from "@/composables/useTextToSpeech";
import {
  chatFilesPortKey,
  clarifyPortKey,
  credentialsPortKey,
  hitlPortKey,
  voicePortKey,
  type ChatUploadedFile,
} from "@/ports";
import { credentialsApi, filesApi, hitlApi } from "@/services/api";

async function uploadChatFile(file: File): Promise<ChatUploadedFile> {
  try {
    const stored = await filesApi.upload(file, false, "chat");
    return {
      id: stored.id,
      name: stored.filename,
      mime: stored.mime_type,
      size: stored.size_bytes,
    };
  } catch (error: unknown) {
    const detail = axios.isAxiosError(error)
      ? (error.response?.data as { detail?: unknown } | undefined)?.detail
      : undefined;
    throw new Error(typeof detail === "string" && detail ? detail : "Could not upload the file to Drive");
  }
}

/** Provides Heym's implementation of every port to the components of `app`. */
export function installHeymPorts(app: App, router: Router): void {
  app.provide(hitlPortKey, {
    inbox: (filter) => hitlApi.inbox(filter),
    inboxDecide: (requestId, payload) => hitlApi.inboxDecide(requestId, payload),
    openRun: ({ workflowId, executionId }) => {
      const params: { id: string; executionId?: string } = { id: workflowId };
      if (executionId) params.executionId = executionId;
      void router.push({ name: "editor", params });
    },
  });
  app.provide(voicePortKey, { useTextToSpeech, useInteractiveVoice });
  app.provide(clarifyPortKey, { useClarifyDataTables });
  app.provide(credentialsPortKey, credentialsApi);
  app.provide(chatFilesPortKey, { upload: uploadChatFile });
}
