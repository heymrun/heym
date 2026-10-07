import { createApp, type App } from "vue";
import type { Router } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import { useClarifyDataTables } from "@/composables/useClarifyDataTables";
import { useInteractiveVoice } from "@/composables/useInteractiveVoice";
import { useTextToSpeech } from "@/composables/useTextToSpeech";
import { clarifyPortKey, credentialsPortKey, hitlPortKey, usePort, voicePortKey } from "@/ports";
import { installHeymPorts } from "@/ports/installHeymPorts";
import { credentialsApi, hitlApi } from "@/services/api";

vi.mock("@/services/api", () => ({
  credentialsApi: { get: vi.fn(), create: vi.fn(), update: vi.fn() },
  hitlApi: {
    inbox: vi.fn(async () => ({ items: [], pending_total: 0 })),
    inboxDecide: vi.fn(async () => ({ request_id: "r-1", status: "accepted" })),
  },
}));

function heymApp(): { app: App; push: ReturnType<typeof vi.fn> } {
  const push = vi.fn(async () => undefined);
  const app = createApp({});
  installHeymPorts(app, { push } as unknown as Router);
  return { app, push };
}

describe("installHeymPorts", () => {
  it("serves the HITL carousel from Heym's inbox API", async () => {
    const { app } = heymApp();
    const hitl = app.runWithContext(() => usePort(hitlPortKey));

    await hitl.inbox();
    await hitl.inboxDecide("r-1", { action: "edit", edited_text: "Ship it" });

    expect(hitlApi.inbox).toHaveBeenCalledOnce();
    expect(hitlApi.inboxDecide).toHaveBeenCalledWith("r-1", {
      action: "edit",
      edited_text: "Ship it",
    });
  });

  it("opens a review's run in the editor, at the execution when there is one", () => {
    const { app, push } = heymApp();
    const hitl = app.runWithContext(() => usePort(hitlPortKey));

    hitl.openRun({ workflowId: "wf-1", executionId: "ex-1" });
    hitl.openRun({ workflowId: "wf-2" });

    expect(push).toHaveBeenNthCalledWith(1, {
      name: "editor",
      params: { id: "wf-1", executionId: "ex-1" },
    });
    expect(push).toHaveBeenNthCalledWith(2, { name: "editor", params: { id: "wf-2" } });
  });

  it("gives voice mode Heym's voice composables", () => {
    const { app } = heymApp();

    expect(app.runWithContext(() => usePort(voicePortKey))).toEqual({
      useTextToSpeech,
      useInteractiveVoice,
    });
  });

  it("gives clarify cards Heym's data table composable", () => {
    const { app } = heymApp();

    expect(app.runWithContext(() => usePort(clarifyPortKey))).toEqual({ useClarifyDataTables });
  });

  it("gives the credential dialog Heym's credentials API", () => {
    const { app } = heymApp();

    expect(app.runWithContext(() => usePort(credentialsPortKey))).toBe(credentialsApi);
  });
});
