import { nextTick, ref, type Ref } from "vue";

interface ExpandableField {
  openExpandDialog(localIndex?: number): void;
  closeExpandDialog(): void;
}

/** Expression-capable Code node fields, in the order the panel renders them. */
export const CODE_EXPRESSION_FIELD_KEYS = ["codeParameters", "codeFiles"] as const;

export interface CodeExpressionFields {
  filesRef: Ref<ExpandableField | null>;
  currentIndex: Ref<number>;
  total: number;
  openAt(index: number): void;
  closeAll(): void;
  navigate(direction: "prev" | "next"): void;
  registerIndex(index: number): void;
}

/** 1/n navigation of the expression dialog across Parameters and Files. */
export function useCodeExpressionFields(
  parametersRef: Ref<ExpandableField | null>,
): CodeExpressionFields {
  const filesRef = ref<ExpandableField | null>(null);
  const currentIndex = ref(0);
  const fieldRefs = [parametersRef, filesRef];

  function openAt(index: number): void {
    const target = fieldRefs[index]?.value;
    if (!target) {
      return;
    }
    currentIndex.value = index;
    target.openExpandDialog();
  }

  function closeAll(): void {
    for (const fieldRef of fieldRefs) {
      fieldRef.value?.closeExpandDialog();
    }
  }

  function navigate(direction: "prev" | "next"): void {
    const next = direction === "prev" ? currentIndex.value - 1 : currentIndex.value + 1;
    if (next < 0 || next >= fieldRefs.length) {
      return;
    }
    closeAll();
    currentIndex.value = next;
    nextTick(() => openAt(next));
  }

  function registerIndex(index: number): void {
    currentIndex.value = index;
  }

  return {
    filesRef,
    currentIndex,
    total: fieldRefs.length,
    openAt,
    closeAll,
    navigate,
    registerIndex,
  };
}
