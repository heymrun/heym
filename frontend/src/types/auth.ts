export interface User {
  id: string;
  email: string;
  name: string;
  user_rules: string | null;
  tts_credential_id: string | null;
  tts_voice_id: string | null;
  created_at: string;
}

export interface UserUpdateRequest {
  name?: string;
  user_rules?: string;
  tts_credential_id?: string | null;
  tts_voice_id?: string | null;
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