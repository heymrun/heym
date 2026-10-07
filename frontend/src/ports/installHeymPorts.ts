import type { App } from "vue";
import type { Router } from "vue-router";

import { useClarifyDataTables } from "@/composables/useClarifyDataTables";
import { useInteractiveVoice } from "@/composables/useInteractiveVoice";
import { useTextToSpeech } from "@/composables/useTextToSpeech";
import { clarifyPortKey, hitlPortKey, voicePortKey } from "@/ports";
import { hitlApi } from "@/services/api";

/** Provides Heym's implementation of every port to the components of `app`. */
export function installHeymPorts(app: App, router: Router): void {
  app.provide(hitlPortKey, {
    inbox: () => hitlApi.inbox(),
    inboxDecide: (requestId, payload) => hitlApi.inboxDecide(requestId, payload),
    openRun: ({ workflowId, executionId }) => {
      const params: { id: string; executionId?: string } = { id: workflowId };
      if (executionId) params.executionId = executionId;
      void router.push({ name: "editor", params });
    },
  });
  app.provide(voicePortKey, { useTextToSpeech, useInteractiveVoice });
  app.provide(clarifyPortKey, { useClarifyDataTables });
}
