import { ref } from "vue";

export type ToastType = "success" | "error" | "info";

interface ToastState {
  message: string;
  type: ToastType;
  visible: boolean;
}

// Module-level singleton so any component can trigger a toast
const toastMessage = ref("");
const toastType = ref<ToastType>("success");
const toastVisible = ref(false);
let hideTimer: ReturnType<typeof setTimeout> | null = null;

export function useToast() {
  function showToast(message: string, type: ToastType = "success", duration = 4000): void {
    if (hideTimer) clearTimeout(hideTimer);
    toastMessage.value = message;
    toastType.value = type;
    toastVisible.value = true;
    hideTimer = setTimeout(() => {
      toastVisible.value = false;
    }, duration);
  }

  function hideToast(): void {
    if (hideTimer) clearTimeout(hideTimer);
    toastVisible.value = false;
  }

  return {
    toastMessage,
    toastType,
    toastVisible,
    showToast,
    hideToast,
  };
}

export type { ToastState };
