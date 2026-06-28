import { onUnmounted, ref, type Ref } from "vue";

export const AUTO_REFRESH_MIN_SECONDS = 10;
export const AUTO_REFRESH_MAX_SECONDS = 3600;
export const HISTORY_AUTO_REFRESH_MIN_SECONDS = 1;

export interface AutoRefreshBounds {
  minSeconds?: number;
  maxSeconds?: number;
}

export function validateAutoRefreshSeconds(
  seconds: number,
  bounds: AutoRefreshBounds = {},
): string | null {
  const minSeconds = bounds.minSeconds ?? AUTO_REFRESH_MIN_SECONDS;
  const maxSeconds = bounds.maxSeconds ?? AUTO_REFRESH_MAX_SECONDS;

  if (!Number.isFinite(seconds) || !Number.isInteger(seconds)) {
    return "Enter a whole number of seconds";
  }
  if (seconds < minSeconds) {
    return `Minimum interval is ${minSeconds}s`;
  }
  if (seconds > maxSeconds) {
    return `Maximum interval is ${maxSeconds}s`;
  }
  return null;
}

export function formatCountdown(seconds: number, compact = false): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (compact && mins === 0) {
    return `${secs}s`;
  }
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

interface UseAutoRefreshResult {
  secondsRemaining: Ref<number | null>;
  validationError: Ref<string | null>;
  setIntervalMs: (ms: number | null) => void;
  stop: () => void;
}

export function useAutoRefresh(
  onTick: () => void,
  bounds: AutoRefreshBounds = {},
): UseAutoRefreshResult {
  const secondsRemaining = ref<number | null>(null);
  const validationError = ref<string | null>(null);
  let refreshTimer: ReturnType<typeof setInterval> | null = null;
  let countdownTimer: ReturnType<typeof setInterval> | null = null;
  let activeIntervalMs: number | null = null;

  function clearTimers(): void {
    if (refreshTimer !== null) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
    if (countdownTimer !== null) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
    activeIntervalMs = null;
  }

  function resetCountdown(): void {
    if (activeIntervalMs === null) {
      secondsRemaining.value = null;
      return;
    }
    secondsRemaining.value = Math.ceil(activeIntervalMs / 1000);
  }

  function setIntervalMs(ms: number | null): void {
    clearTimers();
    validationError.value = null;

    if (ms === null || ms <= 0) {
      secondsRemaining.value = null;
      return;
    }

    const seconds = Math.round(ms / 1000);
    const error = validateAutoRefreshSeconds(seconds, bounds);
    if (error !== null) {
      validationError.value = error;
      secondsRemaining.value = null;
      return;
    }

    activeIntervalMs = seconds * 1000;
    resetCountdown();

    countdownTimer = setInterval(() => {
      if (secondsRemaining.value === null) {
        return;
      }
      if (secondsRemaining.value <= 1) {
        secondsRemaining.value = Math.ceil(activeIntervalMs! / 1000);
        return;
      }
      secondsRemaining.value -= 1;
    }, 1000);

    refreshTimer = setInterval(() => {
      onTick();
      resetCountdown();
    }, activeIntervalMs);
  }

  function stop(): void {
    clearTimers();
    secondsRemaining.value = null;
    validationError.value = null;
  }

  onUnmounted(stop);

  return {
    secondsRemaining,
    validationError,
    setIntervalMs,
    stop,
  };
}
