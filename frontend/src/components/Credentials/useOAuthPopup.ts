import { onBeforeUnmount, ref, type Ref } from "vue";

import type { Credential } from "@/types/credential";

import { credentialsApi } from "@/services/api";

const STATUS_POLL_MS = 2000;
const STATUS_POLL_LIMIT_MS = 10 * 60 * 1000;
const POPUP_CLOSED_POLL_MS = 500;

export interface OAuthPopupState {
  connecting: Ref<boolean>;
  connected: Ref<boolean>;
  connectedCredential: Ref<Credential | null>;
  error: Ref<string>;
}

export interface OAuthPopupConfig {
  windowName: string;
  features: string;
  successType: string;
  errorType: string;
  failureMessage: string;
  onConnected?: (credential: Credential) => void;
}

export interface OAuthPopup {
  /** The authorization page, shown as a link while the flow is open. */
  authUrl: Ref<string>;
  /** The credential this dialog session created, reused by a retry. */
  sessionCredentialId: Ref<string | null>;
  start: (
    prepare: () => Promise<string>,
    authorize: (credentialId: string) => Promise<{ auth_url: string }>,
  ) => Promise<void>;
  openAuthPage: () => void;
  reset: () => void;
}

export function isConnectedMaskedValue(maskedValue: string | null | undefined): boolean {
  return maskedValue === "connected" || !!maskedValue?.startsWith("connected (");
}

/**
 * One OAuth popup flow. The callback page posts to `window.opener`; when the page was
 * opened without one (blocked popup, copied link) the credential is polled instead.
 */
export function useOAuthPopup(state: OAuthPopupState, config: OAuthPopupConfig): OAuthPopup {
  const authUrl = ref("");
  const sessionCredentialId = ref<string | null>(null);
  let popup: Window | null = null;
  let credentialId = "";
  let finished = false;
  let checking = false;
  let statusDeadline = 0;
  let closedTimer: ReturnType<typeof setInterval> | null = null;
  let statusTimer: ReturnType<typeof setInterval> | null = null;

  function stopTimers(): void {
    if (closedTimer) clearInterval(closedTimer);
    if (statusTimer) clearInterval(statusTimer);
    closedTimer = null;
    statusTimer = null;
    window.removeEventListener("message", onMessage);
  }

  async function finishConnected(credential: Credential | null): Promise<void> {
    if (finished) return;
    finished = true;
    stopTimers();
    popup?.close();
    popup = null;
    authUrl.value = "";
    let connectedCredential = credential;
    if (!connectedCredential) {
      try {
        connectedCredential = await credentialsApi.get(credentialId);
      } catch {
        connectedCredential = null;
      }
    }
    state.connectedCredential.value = connectedCredential;
    state.connected.value = true;
    state.connecting.value = false;
    if (connectedCredential) config.onConnected?.(connectedCredential);
  }

  function finishFailed(message: string): void {
    if (finished) return;
    finished = true;
    stopTimers();
    state.connecting.value = false;
    state.error.value = message || config.failureMessage;
  }

  function onMessage(event: MessageEvent): void {
    if (event.origin !== window.location.origin || !popup || event.source !== popup) return;
    if (event.data?.type === config.successType && event.data.credentialId === credentialId) {
      void finishConnected(null);
    } else if (event.data?.type === config.errorType) {
      finishFailed(typeof event.data.message === "string" ? event.data.message : "");
    }
  }

  async function checkStatus(): Promise<void> {
    if (finished || checking) return;
    if (Date.now() > statusDeadline) {
      if (statusTimer) clearInterval(statusTimer);
      statusTimer = null;
      return;
    }
    checking = true;
    try {
      const credential = await credentialsApi.get(credentialId);
      if (isConnectedMaskedValue(credential.masked_value)) await finishConnected(credential);
    } catch {
      // A failed check is retried on the next tick.
    } finally {
      checking = false;
    }
  }

  function watchPopup(): void {
    if (closedTimer) clearInterval(closedTimer);
    closedTimer = setInterval(() => {
      if (popup && !popup.closed) return;
      if (closedTimer) clearInterval(closedTimer);
      closedTimer = null;
      // Keep `popup` for the source check: its success message can land after it closes.
      state.connecting.value = false;
    }, POPUP_CLOSED_POLL_MS);
  }

  function openAuthPage(): void {
    if (!authUrl.value || finished) return;
    popup = window.open(authUrl.value, config.windowName, config.features);
    if (!popup) return;
    state.connecting.value = true;
    watchPopup();
  }

  async function start(
    prepare: () => Promise<string>,
    authorize: (credentialId: string) => Promise<{ auth_url: string }>,
  ): Promise<void> {
    stopTimers();
    finished = false;
    state.connecting.value = true;
    state.error.value = "";
    const alreadyConnected = state.connected.value;
    try {
      credentialId = await prepare();
      const { auth_url: url } = await authorize(credentialId);
      authUrl.value = url;
      window.addEventListener("message", onMessage);
      // A reconnect starts from "connected", so only a new connection can be polled for.
      if (!alreadyConnected) {
        statusDeadline = Date.now() + STATUS_POLL_LIMIT_MS;
        statusTimer = setInterval(() => void checkStatus(), STATUS_POLL_MS);
      }
      state.connecting.value = false;
      openAuthPage();
    } catch (err) {
      finishFailed(err instanceof Error ? err.message : "");
    }
  }

  function reset(): void {
    stopTimers();
    popup = null;
    credentialId = "";
    finished = false;
    authUrl.value = "";
    sessionCredentialId.value = null;
  }

  onBeforeUnmount(stopTimers);

  return { authUrl, sessionCredentialId, start, openAuthPage, reset };
}
