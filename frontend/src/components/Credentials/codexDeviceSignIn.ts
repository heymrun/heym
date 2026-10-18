import { ref, type Ref } from "vue";

import type { CodexDeviceSignInPoll, CodexDeviceSignInStart } from "@/types/credential";

export type CodexDeviceSignInPhase = "idle" | "starting" | "waiting";

export interface CodexSignInResult {
  config: Record<string, unknown>;
  accountId: string;
}

export interface CodexDeviceSignInDeps {
  start: () => Promise<CodexDeviceSignInStart>;
  poll: (state: string) => Promise<CodexDeviceSignInPoll>;
  onSignedIn: (result: CodexSignInResult) => void;
  /** Opens the OpenAI page; the returned window is closed once the sign-in finishes. */
  openWindow: (url: string) => Window | null;
  now?: () => number;
}

export interface CodexDeviceSignIn {
  phase: Ref<CodexDeviceSignInPhase>;
  userCode: Ref<string>;
  verificationUrl: Ref<string>;
  error: Ref<string>;
  begin: () => Promise<void>;
  openVerificationPage: () => void;
  cancel: () => void;
  dispose: () => void;
}

const DEFAULT_INTERVAL_SECONDS = 5;
const FALLBACK_LIFETIME_MS = 15 * 60 * 1000;
// Network blips and 5xx answers are retried; a 4xx (expired, denied, wrong user) is final.
const MAX_TRANSIENT_FAILURES = 3;

export function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" && detail.trim() ? detail : fallback;
}

function errorStatus(err: unknown): number | undefined {
  const status = (err as { response?: { status?: unknown } })?.response?.status;
  return typeof status === "number" ? status : undefined;
}

/**
 * ChatGPT device code sign-in for a Codex credential. `begin` fetches a code, then polls the
 * server every `interval` seconds until the user approves it on OpenAI's page; the finished
 * token config goes to `onSignedIn` and the OpenAI window is closed. Nothing is pasted back.
 */
export function createCodexDeviceSignIn(deps: CodexDeviceSignInDeps): CodexDeviceSignIn {
  const now = deps.now ?? Date.now;
  const phase = ref<CodexDeviceSignInPhase>("idle");
  const userCode = ref("");
  const verificationUrl = ref("");
  const error = ref("");
  let state = "";
  let intervalMs = DEFAULT_INTERVAL_SECONDS * 1000;
  let expiresAt = 0;
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let popup: Window | null = null;
  // Bumped on every restart, cancel and dispose so a reply from an older attempt is ignored.
  let session = 0;

  function stopTimer(): void {
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function closePopup(): void {
    try {
      popup?.close();
    } catch {
      // The window may already be gone.
    }
    popup = null;
  }

  function reset(): void {
    stopTimer();
    session += 1;
    state = "";
    userCode.value = "";
    verificationUrl.value = "";
    phase.value = "idle";
  }

  function fail(message: string): void {
    closePopup();
    reset();
    error.value = message;
  }

  function schedule(current: number): void {
    stopTimer();
    timer = setTimeout(() => void pollOnce(current), intervalMs);
  }

  async function pollOnce(current: number): Promise<void> {
    timer = null;
    if (current !== session) return;
    if (now() >= expiresAt) {
      fail("The code expired. Start the sign-in again.");
      return;
    }
    let result: CodexDeviceSignInPoll;
    try {
      result = await deps.poll(state);
    } catch (err) {
      if (current !== session) return;
      failures += 1;
      const status = errorStatus(err);
      if ((status !== undefined && status < 500) || failures >= MAX_TRANSIENT_FAILURES) {
        fail(errorDetail(err, "ChatGPT sign-in failed. Start the sign-in again."));
        return;
      }
      schedule(current);
      return;
    }
    if (current !== session) return;
    failures = 0;
    if (result.status === "complete" && result.config) {
      closePopup();
      reset();
      deps.onSignedIn({ config: result.config, accountId: result.account_id });
      return;
    }
    schedule(current);
  }

  async function begin(): Promise<void> {
    closePopup();
    reset();
    error.value = "";
    failures = 0;
    phase.value = "starting";
    const current = session;
    try {
      const started = await deps.start();
      if (current !== session) return;
      state = started.state;
      userCode.value = started.user_code;
      verificationUrl.value = started.verification_url;
      intervalMs = Math.max(1, started.interval || DEFAULT_INTERVAL_SECONDS) * 1000;
      const parsed = Date.parse(started.expires_at);
      expiresAt = Number.isNaN(parsed) ? now() + FALLBACK_LIFETIME_MS : parsed;
      phase.value = "waiting";
      schedule(current);
    } catch (err) {
      if (current !== session) return;
      fail(errorDetail(err, "Could not start ChatGPT sign-in. Try again."));
    }
  }

  function openVerificationPage(): void {
    if (!verificationUrl.value) return;
    popup = deps.openWindow(verificationUrl.value) ?? popup;
  }

  function cancel(): void {
    closePopup();
    reset();
    error.value = "";
  }

  function dispose(): void {
    stopTimer();
    session += 1;
  }

  return { phase, userCode, verificationUrl, error, begin, openVerificationPage, cancel, dispose };
}
