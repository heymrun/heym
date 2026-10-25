import { onBeforeUnmount, watch, type Ref } from "vue";

import {
  emptyFollowSignals,
  followedSignals,
  localFollowSignals,
} from "@/features/collab/followSignals";

export interface EditorFollowRefs {
  leftPanelOpen: Ref<boolean>;
  rightPanelOpen: Ref<boolean>;
  historyOpen: Ref<boolean>;
  /** Dialogs and side panels a follower opens too, each with its own access. */
  dialogs: Record<string, EditorDialog>;
}

export interface EditorDialog {
  open: Readonly<Ref<boolean>>;
  set(open: boolean): void;
}

/** Reports EditorView's panel and dialog state to followers, and mirrors a leader's. */
export function useEditorFollowSignals(refs: EditorFollowRefs): void {
  watch(
    refs.leftPanelOpen,
    (open) => {
      localFollowSignals.leftPanelOpen = open;
    },
    { immediate: true },
  );
  watch(
    refs.rightPanelOpen,
    (open) => {
      localFollowSignals.panelOpen = open;
    },
    { immediate: true },
  );
  watch(
    refs.historyOpen,
    (open) => {
      localFollowSignals.historyOpen = open;
    },
    { immediate: true },
  );
  watch(
    () => Object.entries(refs.dialogs).filter(([, dialog]) => dialog.open.value).map(([name]) => name),
    (names) => {
      localFollowSignals.dialogs = names;
    },
    { immediate: true },
  );
  watch(
    followedSignals,
    (signals) => {
      if (!signals) return;
      if (refs.leftPanelOpen.value !== signals.leftPanelOpen) {
        refs.leftPanelOpen.value = signals.leftPanelOpen;
      }
      if (refs.rightPanelOpen.value !== signals.panelOpen) {
        refs.rightPanelOpen.value = signals.panelOpen;
      }
      if (refs.historyOpen.value !== signals.historyOpen) {
        refs.historyOpen.value = signals.historyOpen;
      }
      for (const [name, dialog] of Object.entries(refs.dialogs)) {
        const wanted = signals.dialogs.includes(name);
        if (dialog.open.value !== wanted) dialog.set(wanted);
      }
    },
    { deep: true },
  );
  onBeforeUnmount(() => {
    Object.assign(localFollowSignals, emptyFollowSignals());
  });
}
