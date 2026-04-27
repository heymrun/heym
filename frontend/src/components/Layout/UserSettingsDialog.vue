<script setup lang="ts">
import { ref, watch } from "vue";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { useAuthStore } from "@/stores/auth";

const props = defineProps<{
  open: boolean;
}>();

const emit = defineEmits<{
  close: [];
}>();

const authStore = useAuthStore();

const activeTab = ref<"profile" | "security">("profile");

const savingProfile = ref(false);
const savingPassword = ref(false);

const name = ref("");
const userRules = ref("");

const currentPassword = ref("");
const newPassword = ref("");
const confirmNewPassword = ref("");
const passwordError = ref<string | null>(null);
const passwordSuccess = ref<string | null>(null);

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen && authStore.user) {
      name.value = authStore.user.name;
      userRules.value = authStore.user.user_rules || "";
      activeTab.value = "profile";
      currentPassword.value = "";
      newPassword.value = "";
      confirmNewPassword.value = "";
      passwordError.value = null;
      passwordSuccess.value = null;
    }
  },
  { immediate: true },
);

async function handleSaveProfile(): Promise<void> {
  if (!name.value.trim()) return;

  savingProfile.value = true;
  try {
    await authStore.updateUser({
      name: name.value.trim(),
      user_rules: userRules.value.trim() || undefined,
    });
    emit("close");
  } finally {
    savingProfile.value = false;
  }
}

async function handleChangePassword(): Promise<void> {
  passwordError.value = null;
  passwordSuccess.value = null;

  const trimmedCurrent = currentPassword.value.trim();
  const trimmedNew = newPassword.value.trim();
  const trimmedConfirm = confirmNewPassword.value.trim();

  if (!trimmedCurrent || !trimmedNew || !trimmedConfirm) {
    passwordError.value = "All password fields are required.";
    return;
  }

  if (trimmedNew.length < 8) {
    passwordError.value = "New password must be at least 8 characters.";
    return;
  }

  if (!/[A-Z]/.test(trimmedNew)) {
    passwordError.value = "New password must contain at least one uppercase letter.";
    return;
  }

  if (!/[a-z]/.test(trimmedNew)) {
    passwordError.value = "New password must contain at least one lowercase letter.";
    return;
  }

  if (!/[0-9]/.test(trimmedNew)) {
    passwordError.value = "New password must contain at least one digit.";
    return;
  }

  if (trimmedNew !== trimmedConfirm) {
    passwordError.value = "New password and confirmation do not match.";
    return;
  }

  if (trimmedNew === trimmedCurrent) {
    passwordError.value = "New password must be different from current password.";
    return;
  }

  savingPassword.value = true;
  try {
    await authStore.changePassword({
      currentPassword: trimmedCurrent,
      newPassword: trimmedNew,
    });
    currentPassword.value = "";
    newPassword.value = "";
    confirmNewPassword.value = "";
    passwordSuccess.value = "Password updated successfully.";
  } catch {
    passwordError.value = authStore.error || "Failed to change password. Please try again.";
  } finally {
    savingPassword.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="props.open"
    title="User Settings"
    @close="emit('close')"
  >
    <div class="space-y-5 -mt-3">
      <div class="flex border-b border-border pb-1">
        <button
          type="button"
          class="px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
          :class="activeTab === 'profile' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'profile'"
        >
          Profile
        </button>
        <button
          type="button"
          class="px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
          :class="activeTab === 'security' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'security'"
        >
          Security
        </button>
      </div>

      <form
        v-if="activeTab === 'profile'"
        class="space-y-5"
        @submit.prevent="handleSaveProfile"
      >
        <div class="space-y-2">
          <Label for="user-name">Name</Label>
          <Input
            id="user-name"
            v-model="name"
            placeholder="Your name"
            required
          />
        </div>

        <div class="space-y-2">
          <Label for="user-rules">User Rules</Label>
          <p class="text-xs text-muted-foreground">
            Custom instructions included in every AI request (workflow builder and dashboard
            chat). Use this to define your preferences, coding style, or specific requirements.
          </p>
          <Textarea
            id="user-rules"
            v-model="userRules"
            placeholder="e.g., Always use Turkish for labels, prefer concise responses, include error handling in all workflows..."
            :rows="6"
          />
        </div>

        <div class="flex justify-end gap-3 pt-2">
          <Button
            variant="outline"
            type="button"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            :loading="savingProfile"
            :disabled="!name.trim()"
          >
            Save Changes
          </Button>
        </div>
      </form>

      <form
        v-else
        class="space-y-5"
        @submit.prevent="handleChangePassword"
      >
        <div class="space-y-2">
          <Label for="current-password">Current Password</Label>
          <Input
            id="current-password"
            v-model="currentPassword"
            type="password"
            autocomplete="current-password"
            required
          />
        </div>

        <div class="space-y-2">
          <Label for="new-password">New Password</Label>
          <Input
            id="new-password"
            v-model="newPassword"
            type="password"
            autocomplete="new-password"
            required
          />
          <p class="text-xs text-muted-foreground">
            Minimum 6 characters. Use a strong, unique password for better security.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="confirm-new-password">Confirm New Password</Label>
          <Input
            id="confirm-new-password"
            v-model="confirmNewPassword"
            type="password"
            autocomplete="new-password"
            required
          />
        </div>

        <div
          v-if="passwordError"
          class="text-xs text-destructive"
        >
          {{ passwordError }}
        </div>
        <div
          v-if="passwordSuccess"
          class="text-xs text-emerald-500"
        >
          {{ passwordSuccess }}
        </div>

        <div class="flex justify-end gap-3 pt-2">
          <Button
            variant="outline"
            type="button"
            @click="emit('close')"
          >
            Close
          </Button>
          <Button
            type="submit"
            :loading="savingPassword"
          >
            Update Password
          </Button>
        </div>
      </form>
    </div>
  </Dialog>
</template>
