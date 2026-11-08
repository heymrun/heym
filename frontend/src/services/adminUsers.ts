import api from "@/services/api";

import type { AdminUserAction, AdminUserList, AdminUserStatusFilter } from "@/types/adminUsers";

export async function listAdminUsers(params: {
  q: string;
  status: AdminUserStatusFilter;
  limit: number;
  offset: number;
}): Promise<AdminUserList> {
  const { data } = await api.get<AdminUserList>("/admin/users", { params });
  return data;
}

async function act(userId: string, path: string): Promise<AdminUserAction> {
  const { data } = await api.post<AdminUserAction>(
    `/admin/users/${encodeURIComponent(userId)}/${path}`,
  );
  return data;
}

export function deactivateUser(userId: string): Promise<AdminUserAction> {
  return act(userId, "deactivate");
}

export function reactivateUser(userId: string): Promise<AdminUserAction> {
  return act(userId, "reactivate");
}

export function signOutUser(userId: string): Promise<AdminUserAction> {
  return act(userId, "sign-out");
}

export function resetUserMfa(userId: string): Promise<AdminUserAction> {
  return act(userId, "mfa/reset");
}
