export interface User {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  user_rules: string | null;
  tts_credential_id: string | null;
  tts_voice_id: string | null;
  preferred_credential_id: string | null;
  preferred_model: string | null;
  created_at: string;
}

export interface UserUpdateRequest {
  name?: string;
  user_rules?: string;
  tts_credential_id?: string | null;
  tts_voice_id?: string | null;
  preferred_credential_id?: string | null;
  preferred_model?: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  name: string;
}

export interface PasswordChangeRequest {
  currentPassword: string;
  newPassword: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface MfaSetup {
  setup_token: string;
  secret: string;
  otpauth_uri: string;
  qr_code: string;
}

export interface MfaChallenge {
  purpose: "verify" | "enroll";
  challenge_token: string;
  setup: MfaSetup | null;
}

export interface LoginResponse {
  access_token: string | null;
  refresh_token: string | null;
  token_type: string;
  mfa: MfaChallenge | null;
  recovery_codes: string[] | null;
}

export interface MfaStatus {
  enabled: boolean;
  required: boolean;
  available: boolean;
  enabled_at: string | null;
  recovery_codes_remaining: number;
}
