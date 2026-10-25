import { computed, onBeforeUnmount, reactive, watch, watchEffect, type ComputedRef, type Ref } from "vue";

import type { MetaDraft } from "@/features/collab/types";
import type { CollabContext } from "@/features/collab/useCanvasCollab";

// Long enough for collaborators to load the saved value, so the old one never flashes back.
const SAVED_HOLD_MS = 2000;

type MetaField = keyof MetaDraft;

export interface MetaFieldEdit {
  editing: Ref<boolean>;
  value: Ref<string>;
  /** The stored value, which an edit that was kept matches as soon as it is committed. */
  saved: () => string;
}

export interface WorkflowMetaSync {
  /** A collaborator's draft of the field, null when nobody else is typing it. */
  peerName: ComputedRef<string | null>;
  peerDescription: ComputedRef<string | null>;
  peerColor: ComputedRef<string | null>;
}

/** Shares this tab's name and description edits as they are typed, and shows others' edits. */
export function useWorkflowMetaSync(
  collab: CollabContext,
  fields: Record<MetaField, MetaFieldEdit>,
): WorkflowMetaSync {
  const held = reactive<MetaDraft>({});
  const timers = new Map<MetaField, ReturnType<typeof setTimeout>>();

  for (const field of ["name", "description"] as const) {
    const edit = fields[field];
    watch(edit.editing, (editing, wasEditing) => {
      const value = edit.value.value.trim();
      // Escape leaves the stored value alone, so a cancelled draft is not held.
      if (editing || !wasEditing || edit.saved() !== value) return;
      held[field] = value;
      clearTimeout(timers.get(field));
      timers.set(field, setTimeout(() => delete held[field], SAVED_HOLD_MS));
    });
  }
  onBeforeUnmount(() => {
    timers.forEach((timer) => clearTimeout(timer));
    collab.setMetaDraft(null);
  });

  watchEffect(() => {
    const draft: MetaDraft = { ...held };
    if (fields.name.editing.value) draft.name = fields.name.value.value;
    if (fields.description.editing.value) draft.description = fields.description.value.value;
    collab.setMetaDraft(Object.keys(draft).length > 0 ? draft : null);
  });

  const peer = collab.peerMeta;
  return {
    peerName: computed(() =>
      fields.name.editing.value ? null : (peer.value?.name ?? null),
    ),
    peerDescription: computed(() =>
      fields.description.editing.value ? null : (peer.value?.description ?? null),
    ),
    peerColor: computed(() => peer.value?.color ?? null),
  };
}
