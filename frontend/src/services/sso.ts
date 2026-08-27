import api from "@/services/api";

import type { SsoSettings, SsoSettingsUpdate, SsoStatus, SsoTestResult } from "@/types/sso";

export async function getSsoStatus(): Promise<SsoStatus> {
  const { data } = await api.get<SsoStatus>("/auth/sso/status");
  return data;
}

export async function getAdminSsoConfig(): Promise<SsoSettings> {
  const { data } = await api.get<SsoSettings>("/admin/sso");
  return data;
}

export async function saveAdminSsoConfig(update: SsoSettingsUpdate): Promise<SsoSettings> {
  const { data } = await api.put<SsoSettings>("/admin/sso", update);
  return data;
}

export async function testSsoConnection(issuer?: string): Promise<SsoTestResult> {
  const { data } = await api.post<SsoTestResult>("/admin/sso/test", { issuer: issuer ?? null });
  return data;
}
