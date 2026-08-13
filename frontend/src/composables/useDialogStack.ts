import { ref } from "vue";

/** Ids of the currently open dialogs, bottom-most first. */
const dialogStack = ref<symbol[]>([]);


function syncBodyScrollLock(): void {
  document.body.style.overflow = dialogStack.value.length > 0 ? "hidden" : "";
}

export function addToDialogStack(dialogId: symbol): void {
  dialogStack.value = [...dialogStack.value.filter((id) => id !== dialogId), dialogId];
  syncBodyScrollLock();
}

export function removeFromDialogStack(dialogId: symbol): void {
  dialogStack.value = dialogStack.value.filter((id) => id !== dialogId);
  syncBodyScrollLock();
}

export function isTopmostDialog(dialogId: symbol): boolean {
  const stack = dialogStack.value;
  return stack[stack.length - 1] === dialogId;
}

export function isBottommostDialog(dialogId: symbol): boolean {
  return dialogStack.value[0] === dialogId;
}

export function dialogStackPosition(dialogId: symbol): number {
  return Math.max(dialogStack.value.indexOf(dialogId), 0);
}

export function hasOpenDialog(): boolean {
  return dialogStack.value.length > 0;
}
