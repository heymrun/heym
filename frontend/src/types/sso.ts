export interface SsoStatus {
  enabled: boolean;
  button_label: string;
  password_login_enabled: boolean;
}

export interface SsoSettings {
  enabled: boolean;
  issuer: string;
  client_id: string;
  client_secret_set: boolean;
  scopes: string;
  button_label: string;
  auto_provision_users: boolean;
  allowed_email_domains: string;
  password_login_disabled: boolean;
  last_test_ok: boolean;
  last_test_at: string | null;
  redirect_uri: string;
  break_glass_ready: boolean;
}

export interface SsoSettingsUpdate {
  enabled?: boolean;
  issuer?: string;
  client_id?: string;
  client_secret?: string;
  scopes?: string;
  button_label?: string;
  auto_provision_users?: boolean;
  allowed_email_domains?: string;
  password_login_disabled?: boolean;
}

export interface SsoTestResult {
  ok: boolean;
  issuer: string | null;
  authorization_endpoint: string | null;
  token_endpoint: string | null;
  jwks_uri: string | null;
  userinfo_endpoint: string | null;
  error: string | null;
}
