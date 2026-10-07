import { inject, type InjectionKey } from "vue";

import type { HITLDecisionPayload, HITLInbox } from "@/types/workflow";
import type { ClarifyDataTables } from "@/composables/clarifyDataTables";
import type { InteractiveVoice } from "@/composables/interactiveVoice";
import type { TextToSpeechPlayer } from "@/composables/textToSpeechPlayer";

/*
 * Ports: what a presentational component needs from the app that hosts it.
 *
 * Heym Work renders some of Heym's components inside its own app, where `@/services/api`, the
 * Pinia stores and the router are Work's or do not exist. Those components never import them.
 * They take data through props and get everything else from a port the host provides: Heym
 * installs its implementations in `main.ts` (`installHeymPorts`), Work installs its own.
 * `presentationalImports.test.ts` lists the components and fails when one imports them again.
 *
 * Each port is the thing the component used to import, so the code below the injection line
 * reads as before.
 */

/** The run a pending review came from. */
export interface HitlRunTarget {
  workflowId: string;
  executionId?: string;
}

/** The HITL carousel's pending reviews: Heym's `hitlApi` calls, and opening the run in the editor. */
export interface HitlPort {
  inbox: () => Promise<HITLInbox>;
  inboxDecide: (requestId: string, payload: HITLDecisionPayload) => Promise<unknown>;
  openRun: (target: HitlRunTarget) => void;
}

export const hitlPortKey: InjectionKey<HitlPort> = Symbol("hitlPort");

/**
 * Voice mode's speech out and speech in. Heym provides its composables; a host builds the same
 * pair over its own API with `createTextToSpeechPlayer` and `createInteractiveVoice`.
 */
export interface VoicePort {
  useTextToSpeech: () => TextToSpeechPlayer;
  useInteractiveVoice: (onUtterance: (text: string) => void) => InteractiveVoice;
}

export const voicePortKey: InjectionKey<VoicePort> = Symbol("voicePort");

/**
 * The data tables a clarify card shows and creates. Heym provides its composable; a host builds
 * the same state over its own API with `createClarifyDataTables`.
 */
export interface ClarifyPort {
  useClarifyDataTables: () => ClarifyDataTables;
}

export const clarifyPortKey: InjectionKey<ClarifyPort> = Symbol("clarifyPort");

/** Returns the host's implementation of a port; throws when the host did not provide one. */
export function usePort<T>(key: InjectionKey<T>): T {
  const port = inject(key, null);
  if (port === null) {
    throw new Error(
      `${key.description ?? "A port"} is not provided. The host app provides it (Heym: installHeymPorts() in main.ts).`,
    );
  }
  return port;
}
