import { computed, ref } from "vue";
import { defineStore } from "pinia";

import {
  clearGlobalVariablesCache,
  refreshGlobalVariablesCache,
} from "@/composables/useExpressionCompletion";
import { authApi } from "@/services/api";
import type { LoginRequest, PasswordChangeRequest, RegisterRequest, User, UserUpdateRequest } from "@/types/auth";

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

  async function login(data: LoginRequest): Promise<void> {
    loading.value = true;
    error.value = null;

    try {
      await authApi.login(data);
      await fetchUser();
      refreshGlobalVariablesCache();
    } catch (err) {
      if (err instanceof Error) {
        error.value = err.message;
      }
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function register(data: RegisterRequest): Promise<void> {
    loading.value = true;
    error.value = null;

    try {
      await authApi.register(data);
      await fetchUser();
      refreshGlobalVariablesCache();
    } catch (err) {
      if (err instanceof Error) {
        error.value = err.message;
      }
      throw err;
    } finally {
      loading.value = false;
    }
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
    fetchUser,
    updateUser,
    changePassword,
    logout,
  };
});
