import api from "@/services/api";

import type { MfaSetup, MfaStatus } from "@/types/auth";

export async function getMfaStatus(): Promise<MfaStatus> {
  const { data } = await api.get<MfaStatus>("/auth/mfa");
  return data;
}

export async function startMfaSetup(password: string, code: string | null): Promise<MfaSetup> {
  const { data } = await api.post<MfaSetup>("/auth/mfa/setup", { password, code });
  return data;
}

export async function confirmMfaSetup(setupToken: string, code: string): Promise<string[]> {
  const { data } = await api.post<{ recovery_codes: string[] }>("/auth/mfa/enable", {
    setup_token: setupToken,
    code,
  });
  return data.recovery_codes;
}

export async function regenerateRecoveryCodes(code: string): Promise<string[]> {
  const { data } = await api.post<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes", {
    code,
  });
  return data.recovery_codes;
}

export async function revokeOtherSessions(): Promise<void> {
  await api.post("/auth/sessions/revoke-others");
}

export function apiErrorDetail(err: unknown, fallback: string): string {
  if (typeof err === "object" && err !== null && "response" in err) {
    const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}
