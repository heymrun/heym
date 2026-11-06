import { computed, nextTick, ref, watch, type ComputedRef } from "vue";

import type { WorkflowNode } from "@/types/workflow";
import {
  getGoogleMeetFields,
  type GoogleMeetField,
  type GoogleMeetFieldKey,
} from "@/lib/googleMeetFields";

interface ExpandableField {
  openExpandDialog(): void;
  closeExpandDialog(): void;
}

interface GoogleMeetExpressionFields {
  fields: ComputedRef<GoogleMeetField[]>;
  register(key: GoogleMeetFieldKey, instance: unknown): void;
  closeAll(): void;
  openAt(index?: number): boolean;
  navigate(direction: "prev" | "next"): void;
  registerIndex(index: number): void;
}

/** Keep operation-specific form state outside the shared properties controller. */
export function useGoogleMeetExpressionFields(
  node: ComputedRef<WorkflowNode | null>,
): GoogleMeetExpressionFields {
  const references = new Map<GoogleMeetFieldKey, ExpandableField>();
  const currentIndex = ref(0);
  const fields = computed(() => node.value?.type === "googleMeet"
    ? getGoogleMeetFields(node.value.data.gmOperation)
    : []);

  function register(key: GoogleMeetFieldKey, instance: unknown): void {
    if (instance) references.set(key, instance as ExpandableField);
    else references.delete(key);
  }

  function closeAll(): void {
    for (const field of references.values()) field.closeExpandDialog();
  }

  function openAt(index = 0): boolean {
    const field = fields.value[index];
    const instance = field ? references.get(field.key) : undefined;
    if (!instance) return false;
    currentIndex.value = index;
    instance.openExpandDialog();
    return true;
  }

  function navigate(direction: "prev" | "next"): void {
    const index = currentIndex.value + (direction === "prev" ? -1 : 1);
    if (index < 0 || index >= fields.value.length) return;
    closeAll();
    nextTick(() => openAt(index));
  }

  function registerIndex(index: number): void {
    currentIndex.value = index;
  }

  watch(() => [node.value?.id, node.value?.data.gmOperation], () => {
    closeAll();
    currentIndex.value = 0;
  });

  return { fields, register, closeAll, openAt, navigate, registerIndex };
}
