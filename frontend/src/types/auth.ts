export interface User {
  id: string;
  email: string;
  name: string;
  user_rules: string | null;
  created_at: string;
}

export interface UserUpdateRequest {
  name?: string;
  user_rules?: string;
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