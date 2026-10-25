import { computed, ref, watch, type ComputedRef, type Ref } from "vue";

import type { FlowViewport, FollowState } from "@/features/collab/types";
import type { CollabPeer, Presence } from "@/features/collab/usePresence";
import type { useWorkflowStore } from "@/stores/workflow";
import {
  followedPerson,
  followedSignals,
  followedTranscript,
} from "@/features/collab/followSignals";

type WorkflowStore = ReturnType<typeof useWorkflowStore>;
const PANEL_TABS = ["properties", "config"] as const;
// The history row of a run that just finished can land a moment after the leader sees it.
const HISTORY_ATTEMPTS = 4;
const HISTORY_RETRY_MS = 750;

export interface Follow {
  followingSid: Ref<string | null>;
  leader: ComputedRef<CollabPeer | null>;
  start(sid: string): void;
  stop(): void;
}

export interface FollowDeps {
  store: WorkflowStore;
  presence: Presence;
  applyViewport: (viewport: FlowViewport) => void;
}

export function createFollow({ store, presence, applyViewport }: FollowDeps): Follow {
  const followingSid = ref<string | null>(null);
  const leader = computed<CollabPeer | null>(() =>
    followingSid.value ? (presence.peers.get(followingSid.value) ?? null) : null,
  );

  function stop(): void {
    followingSid.value = null;
    followedSignals.value = null;
    followedPerson.value = null;
    followedTranscript.value = [];
  }

  function start(sid: string): void {
    followingSid.value = sid;
  }

  // A finished run the leader shows, loaded through this tab's own History access.
  let loadingExecutionId: string | null = null;

  async function showExecution(executionId: string): Promise<void> {
    if (loadingExecutionId === executionId) return;
    loadingExecutionId = executionId;
    try {
      for (let attempt = 0; attempt < HISTORY_ATTEMPTS && followingSid.value; attempt += 1) {
        const entry = await store.fetchExecutionHistoryEntry(executionId, attempt > 0);
        if (entry) {
          if (followingSid.value) store.applyExecutionHistoryEntry(entry);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, HISTORY_RETRY_MS));
      }
    } finally {
      loadingExecutionId = null;
    }
  }

  function mirror(state: FollowState): void {
    followedSignals.value = {
      leftPanelOpen: state.leftPanelOpen,
      panelOpen: state.panelOpen,
      expression: state.expression,
      debugOpen: state.debugOpen,
      historyOpen: state.historyOpen,
      historyExecutionId: state.historyExecutionId,
      dialogs: state.dialogs,
      assistant: state.assistant,
    };
    const identity = leader.value?.identity;
    if (identity && followedPerson.value?.userId !== identity.userId) {
      followedPerson.value = { userId: identity.userId, name: identity.name };
    }
    if (state.runInputs) {
      const { text, values, json } = state.runInputs;
      if (store.runInputText !== text) store.runInputText = text;
      if (JSON.stringify(store.runInputValues) !== JSON.stringify(values)) {
        store.runInputValues = { ...values };
      }
      if (store.runInputJson !== json) store.runInputJson = json;
    }
    if (state.viewport) applyViewport(state.viewport);
    const known =
      state.selectedNodeId === null ||
      store.nodes.some((node) => node.id === state.selectedNodeId);
    if (known && state.selectedNodeId !== store.selectedNodeId) {
      store.selectNode(state.selectedNodeId);
    }
    const tab = PANEL_TABS.find((candidate) => candidate === state.panelTab);
    if (tab && tab !== store.propertiesPanelTab) store.propertiesPanelTab = tab;
    if (state.runningExecutionId && state.runningExecutionId !== store.currentExecutionId) {
      void store.observeExecution(state.runningExecutionId);
    } else if (
      state.shownExecutionId &&
      !store.isExecuting &&
      state.shownExecutionId !== store.executionResult?.execution_history_id &&
      state.shownExecutionId !== store.currentExecutionId
    ) {
      void showExecution(state.shownExecutionId);
    }
  }

  watch(leader, (peer) => {
    if (followingSid.value && !peer) stop();
  });
  watch(
    () => leader.value?.state?.follow ?? null,
    (state) => {
      if (state) mirror(state);
    },
    { deep: true },
  );

  return { followingSid, leader, start, stop };
}
