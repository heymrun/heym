export type SignInMethod = "password" | "sso";

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  created_at: string;
  last_login_at: string | null;
  is_active: boolean;
  deactivated_at: string | null;
  is_admin: boolean;
  sign_in_methods: SignInMethod[];
  mfa_enabled: boolean;
}

export interface AdminUserList {
  items: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminUserAction {
  user: AdminUser;
  workflows_changed: number;
}

export type AdminUserStatusFilter = "all" | "active" | "deactivated";

export type UserAdminAction = "deactivate" | "reactivate" | "sign-out" | "reset-mfa";
