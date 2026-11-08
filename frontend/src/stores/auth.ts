import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  clearGlobalVariablesCache,
  refreshGlobalVariablesCache,
} from "@/composables/useExpressionCompletion";
import { authApi } from "@/services/api";
import type {
  LoginRequest,
  MfaChallenge,
  PasswordChangeRequest,
  RegisterRequest,
  User,
  UserUpdateRequest,
} from "@/types/auth";

export const useAuthStore = defineStore("auth", () => {
  const user = ref<User | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const initialized = ref(false);

  // Authentication state is derived from the presence of the user object
  // (populated by /api/auth/me using the HttpOnly cookie) rather than a
  // token in localStorage — the token lives exclusively in the HttpOnly
  // cookie that JavaScript cannot read.
  const isAuthenticated = computed(() => !!user.value);

  // Returns the second step when the password alone does not finish the sign-in.
  async function login(data: LoginRequest): Promise<MfaChallenge | null> {
    loading.value = true;
    error.value = null;

    try {
      const result = await authApi.login(data);
      if (result.mfa) return result.mfa;
      await fetchUser();
      refreshGlobalVariablesCache();
      return null;
    } catch (err) {
      if (err instanceof Error) {
        error.value = err.message;
      }
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function register(data: RegisterRequest): Promise<MfaChallenge | null> {
    loading.value = true;
    error.value = null;

    try {
      const result = await authApi.register(data);
      if (result.mfa) return result.mfa;
      await fetchUser();
      refreshGlobalVariablesCache();
      return null;
    } catch (err) {
      if (err instanceof Error) {
        error.value = err.message;
      }
      throw err;
    } finally {
      loading.value = false;
    }
  }

  // Finishes a challenged sign-in. Returns recovery codes when it enrolled a new authenticator.
  async function completeMfa(
    challenge: MfaChallenge,
    code: string,
  ): Promise<string[] | null> {
    const result = await authApi.completeMfa({
      challenge_token: challenge.challenge_token,
      code,
      setup_token: challenge.setup?.setup_token ?? null,
    });
    await fetchUser();
    refreshGlobalVariablesCache();
    return result.recovery_codes;
  }

  async function fetchUser(): Promise<void> {
    try {
      user.value = await authApi.getMe();
    } catch {
      user.value = null;
    } finally {
      initialized.value = true;
    }
  }

  async function updateUser(data: UserUpdateRequest): Promise<void> {
    loading.value = true;
    error.value = null;

    try {
      user.value = await authApi.updateMe(data);
    } catch (err) {
      if (err instanceof Error) {
        error.value = err.message;
      }
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function changePassword(data: PasswordChangeRequest): Promise<void> {
    loading.value = true;
    error.value = null;

    try {
      await authApi.changePassword(data);
    } catch (err) {
      if (err instanceof Error) {
        error.value = err.message;
      }
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout();
    } catch {
      // Best-effort
    }
    user.value = null;
    clearGlobalVariablesCache();
  }

  return {
    user,
    loading,
    error,
    initialized,
    isAuthenticated,
    login,
    register,
    completeMfa,
    fetchUser,
    updateUser,
    changePassword,
    logout,
  };
});
