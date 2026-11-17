import { computed, nextTick, ref, watch, type ComputedRef } from "vue";

import type { NodeData, NodeType, WorkflowNode } from "@/types/workflow";

interface ExpandableField {
  openExpandDialog(): void;
  closeExpandDialog(): void;
}

export interface OperationExpressionFields<K extends string, F extends { key: K }> {
  fields: ComputedRef<F[]>;
  register(key: K, instance: unknown): void;
  closeAll(): void;
  openAt(index?: number): boolean;
  navigate(direction: "prev" | "next"): void;
  registerIndex(index: number): void;
}

/** Expression dialog `1/n` navigation over one node type's operation-specific fields. */
export function useOperationExpressionFields<K extends string, F extends { key: K }>(
  node: ComputedRef<WorkflowNode | null>,
  nodeType: NodeType,
  getFields: (data: NodeData) => F[],
  operationOf: (data: NodeData) => unknown,
): OperationExpressionFields<K, F> {
  const references = new Map<K, ExpandableField>();
  const currentIndex = ref(0);
  const fields = computed(() => node.value?.type === nodeType ? getFields(node.value.data) : []);

  function register(key: K, instance: unknown): void {
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

  watch(() => [node.value?.id, node.value ? operationOf(node.value.data) : undefined], () => {
    closeAll();
    currentIndex.value = 0;
  });

  return { fields, register, closeAll, openAt, navigate, registerIndex };
}
