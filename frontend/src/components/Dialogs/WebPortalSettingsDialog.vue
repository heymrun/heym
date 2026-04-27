<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Copy, ExternalLink, Eye, EyeOff, Globe, Plus, Settings, Trash2, Users, X } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { joinOriginAndPath } from "@/lib/appUrl";
import { portalApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

interface PortalUser {
  id: string;
  username: string;
  created_at: string;
}

interface PortalSettings {
  portal_enabled: boolean;
  portal_slug: string | null;
  portal_stream_enabled: boolean;
  portal_file_upload_enabled: boolean;
  portal_file_config: Record<string, { file_upload_enabled: boolean; allowed_types: string[]; max_size_mb: number }>;
  input_fields: Array<{ key: string; defaultValue?: string }>;
}

const workflowStore = useWorkflowStore();

const isOpen = ref(false);
const isLoading = ref(false);
const isSaving = ref(false);
const activeTab = ref<"general" | "auth" | "options">("general");

const settings = ref<PortalSettings>({
  portal_enabled: false,
  portal_slug: null,
  portal_stream_enabled: true,
  portal_file_upload_enabled: false,
  portal_file_config: {},
  input_fields: [],
});

const users = ref<PortalUser[]>([]);
const isLoadingUsers = ref(false);
const newUsername = ref("");
const newPassword = ref("");
const showPassword = ref(false);
const isAddingUser = ref(false);
const deletingUserId = ref<string | null>(null);
const error = ref("");
const copied = ref(false);

const portalUrl = computed(() => {
  const slug = settings.value.portal_slug;
  if (!slug) return "";
  return joinOriginAndPath(window.location.origin, `/chat/${slug}`);
});

const slugError = computed(() => {
  const slug = settings.value.portal_slug || "";
  if (!slug) return "";
  if (!/^[a-z0-9-]+$/.test(slug)) {
    return "Only lowercase letters, numbers and hyphens allowed";
  }
  return "";
});

watch(
  () => isOpen.value,
  async (open) => {
    if (open && workflowStore.currentWorkflow) {
      await loadSettings();
    }
  }
);

watch(activeTab, async (tab) => {
  if (tab === "auth" && users.value.length === 0) {
    await loadUsers();
  }
});

async function loadSettings(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  isLoading.value = true;
  error.value = "";
  try {
    const data = await portalApi.getSettings(workflowStore.currentWorkflow.id);
    settings.value = data;
  } catch (e) {
    error.value = "Failed to load portal settings";
  } finally {
    isLoading.value = false;
  }
}

async function loadUsers(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  isLoadingUsers.value = true;
  try {
    users.value = await portalApi.listUsers(workflowStore.currentWorkflow.id);
  } catch {
    users.value = [];
  } finally {
    isLoadingUsers.value = false;
  }
}

async function saveSettings(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  if (slugError.value) return;

  isSaving.value = true;
  error.value = "";
  try {
    const data = await portalApi.updateSettings(workflowStore.currentWorkflow.id, {
      portal_enabled: settings.value.portal_enabled,
      portal_slug: settings.value.portal_slug || undefined,
      portal_stream_enabled: settings.value.portal_stream_enabled,
      portal_file_upload_enabled: settings.value.portal_file_upload_enabled,
      portal_file_config: settings.value.portal_file_config,
    });
    settings.value = data;
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    error.value = err.response?.data?.detail || "Failed to save settings";
  } finally {
    isSaving.value = false;
  }
}

async function addUser(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  if (!newUsername.value.trim() || !newPassword.value) return;

  isAddingUser.value = true;
  error.value = "";
  try {
    const user = await portalApi.createUser(workflowStore.currentWorkflow.id, {
      username: newUsername.value.trim(),
      password: newPassword.value,
    });
    users.value.push(user);
    users.value.sort((a, b) => a.username.localeCompare(b.username));
    newUsername.value = "";
    newPassword.value = "";
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    error.value = err.response?.data?.detail || "Failed to add user";
  } finally {
    isAddingUser.value = false;
  }
}

async function deleteUser(userId: string): Promise<void> {
  if (!workflowStore.currentWorkflow) return;

  deletingUserId.value = userId;
  error.value = "";
  try {
    await portalApi.deleteUser(workflowStore.currentWorkflow.id, userId);
    users.value = users.value.filter((u) => u.id !== userId);
  } catch {
    error.value = "Failed to delete user";
  } finally {
    deletingUserId.value = null;
  }
}

async function copyUrl(): Promise<void> {
  await navigator.clipboard.writeText(portalUrl.value);
  copied.value = true;
  setTimeout(() => {
    copied.value = false;
  }, 2000);
}

function openPortal(): void {
  if (portalUrl.value) {
    window.open(portalUrl.value, "_blank");
  }
}

function openDialog(): void {
  isOpen.value = true;
  activeTab.value = "general";
  error.value = "";
  users.value = [];
}

function closeDialog(): void {
  isOpen.value = false;
}

defineExpose({ openDialog, closeDialog });
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <div
        class="absolute inset-0 bg-background/80 backdrop-blur-sm"
        @click="closeDialog"
      />

      <div class="relative bg-card border rounded-lg shadow-lg w-full max-w-xl max-h-[90vh] overflow-hidden overflow-x-hidden animate-in fade-in zoom-in-95">
        <div class="flex items-center justify-between p-4 border-b">
          <div class="flex items-center gap-3">
            <div class="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10">
              <Globe class="w-5 h-5 text-primary" />
            </div>
            <div>
              <h2 class="text-lg font-semibold">
                Web Portal
              </h2>
              <p class="text-sm text-muted-foreground">
                Configure public access to this workflow
              </p>
            </div>
          </div>
          <button
            class="p-2 rounded-md hover:bg-muted transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
            @click="closeDialog"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="flex border-b">
          <button
            class="flex-1 px-4 py-2.5 min-h-[44px] text-sm font-medium transition-colors"
            :class="activeTab === 'general' ? 'border-b-2 border-primary text-primary' : 'text-muted-foreground hover:text-foreground'"
            @click="activeTab = 'general'"
          >
            <Settings class="w-4 h-4 inline-block mr-1.5 -mt-0.5" />
            General
          </button>
          <button
            class="flex-1 px-4 py-2.5 min-h-[44px] text-sm font-medium transition-colors"
            :class="activeTab === 'auth' ? 'border-b-2 border-primary text-primary' : 'text-muted-foreground hover:text-foreground'"
            @click="activeTab = 'auth'"
          >
            <Users class="w-4 h-4 inline-block mr-1.5 -mt-0.5" />
            Users
          </button>
          <button
            class="flex-1 px-4 py-2.5 text-sm font-medium transition-colors"
            :class="activeTab === 'options' ? 'border-b-2 border-primary text-primary' : 'text-muted-foreground hover:text-foreground'"
            @click="activeTab = 'options'"
          >
            <Settings class="w-4 h-4 inline-block mr-1.5 -mt-0.5" />
            Options
          </button>
        </div>

        <div class="p-4 overflow-y-auto max-h-[60vh]">
          <div
            v-if="isLoading"
            class="flex items-center justify-center py-8"
          >
            <div class="animate-pulse text-muted-foreground">
              Loading...
            </div>
          </div>

          <template v-else>
            <div
              v-if="activeTab === 'general'"
              class="space-y-4"
            >
              <div class="flex items-center justify-between p-3 rounded-lg bg-muted/50">
                <div>
                  <Label class="text-sm font-medium">Enable Portal</Label>
                  <p class="text-xs text-muted-foreground mt-0.5">
                    Make this workflow accessible via public URL
                  </p>
                </div>
                <button
                  class="relative w-11 h-6 rounded-full transition-colors"
                  :class="settings.portal_enabled ? 'bg-primary' : 'bg-muted-foreground/30'"
                  @click="settings.portal_enabled = !settings.portal_enabled"
                >
                  <span
                    class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow-sm"
                    :class="settings.portal_enabled ? 'translate-x-5' : 'translate-x-0'"
                  />
                </button>
              </div>

              <div class="space-y-2">
                <Label>Portal URL Slug</Label>
                <div class="flex gap-2">
                  <div class="flex-1 relative">
                    <span class="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                      /chat/
                    </span>
                    <Input
                      :model-value="settings.portal_slug ?? ''"
                      class="pl-14"
                      placeholder="my-workflow"
                      @update:model-value="(v: string) => settings.portal_slug = v || null"
                    />
                  </div>
                </div>
                <p
                  v-if="slugError"
                  class="text-xs text-destructive"
                >
                  {{ slugError }}
                </p>
              </div>

              <div
                v-if="settings.portal_enabled && settings.portal_slug"
                class="p-3 rounded-lg bg-muted/50 space-y-2"
              >
                <Label class="text-xs text-muted-foreground">Portal URL</Label>
                <div class="flex items-center gap-2">
                  <Input
                    :model-value="portalUrl"
                    readonly
                    class="text-sm font-mono"
                  />
                  <Button
                    variant="outline"
                    size="icon"
                    @click="copyUrl"
                  >
                    <Copy class="w-4 h-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="icon"
                    @click="openPortal"
                  >
                    <ExternalLink class="w-4 h-4" />
                  </Button>
                </div>
                <p
                  v-if="copied"
                  class="text-xs text-primary"
                >
                  Copied to clipboard!
                </p>
              </div>
            </div>

            <div
              v-if="activeTab === 'auth'"
              class="space-y-4"
            >
              <div class="p-3 rounded-lg bg-muted/30 text-sm text-muted-foreground">
                <p>Add users to require authentication. If no users are added, the portal will be publicly accessible.</p>
              </div>

              <div class="space-y-2">
                <Label>Add User</Label>
                <div class="flex gap-2">
                  <Input
                    v-model="newUsername"
                    placeholder="Username"
                    class="flex-1"
                  />
                  <div class="relative flex-1">
                    <Input
                      v-model="newPassword"
                      :type="showPassword ? 'text' : 'password'"
                      placeholder="Password"
                      class="pr-10"
                    />
                    <button
                      class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground"
                      @click="showPassword = !showPassword"
                    >
                      <Eye
                        v-if="!showPassword"
                        class="w-4 h-4"
                      />
                      <EyeOff
                        v-else
                        class="w-4 h-4"
                      />
                    </button>
                  </div>
                  <Button
                    :loading="isAddingUser"
                    :disabled="!newUsername.trim() || !newPassword"
                    @click="addUser"
                  >
                    <Plus class="w-4 h-4" />
                  </Button>
                </div>
              </div>

              <div class="space-y-2">
                <Label>Users ({{ users.length }})</Label>
                <div
                  v-if="isLoadingUsers"
                  class="text-sm text-muted-foreground p-4 text-center"
                >
                  Loading users...
                </div>
                <div
                  v-else-if="users.length === 0"
                  class="text-sm text-muted-foreground p-4 text-center border rounded-md border-dashed"
                >
                  No users added. Portal is publicly accessible.
                </div>
                <div
                  v-else
                  class="space-y-1"
                >
                  <div
                    v-for="user in users"
                    :key="user.id"
                    class="flex items-center justify-between p-2 rounded-md bg-muted/30 hover:bg-muted/50"
                  >
                    <div>
                      <span class="text-sm font-medium">{{ user.username }}</span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="text-destructive hover:text-destructive"
                      :loading="deletingUserId === user.id"
                      @click="deleteUser(user.id)"
                    >
                      <Trash2 class="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </div>
            </div>

            <div
              v-if="activeTab === 'options'"
              class="space-y-4"
            >
              <div class="flex items-center justify-between p-3 rounded-lg bg-muted/50">
                <div>
                  <Label class="text-sm font-medium">Stream Mode</Label>
                  <p class="text-xs text-muted-foreground mt-0.5">
                    Show real-time progress as each node executes
                  </p>
                </div>
                <button
                  class="relative w-11 h-6 rounded-full transition-colors"
                  :class="settings.portal_stream_enabled ? 'bg-primary' : 'bg-muted-foreground/30'"
                  @click="settings.portal_stream_enabled = !settings.portal_stream_enabled"
                >
                  <span
                    class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow-sm"
                    :class="settings.portal_stream_enabled ? 'translate-x-5' : 'translate-x-0'"
                  />
                </button>
              </div>

              <div class="flex items-center justify-between p-3 rounded-lg bg-muted/50">
                <div>
                  <Label class="text-sm font-medium">File Upload</Label>
                  <p class="text-xs text-muted-foreground mt-0.5">
                    Allow users to upload files (text/images)
                  </p>
                </div>
                <button
                  class="relative w-11 h-6 rounded-full transition-colors"
                  :class="settings.portal_file_upload_enabled ? 'bg-primary' : 'bg-muted-foreground/30'"
                  @click="settings.portal_file_upload_enabled = !settings.portal_file_upload_enabled"
                >
                  <span
                    class="absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow-sm"
                    :class="settings.portal_file_upload_enabled ? 'translate-x-5' : 'translate-x-0'"
                  />
                </button>
              </div>

              <div
                v-if="settings.input_fields.length > 0"
                class="space-y-2"
              >
                <Label>Input Fields</Label>
                <div class="space-y-1">
                  <div
                    v-for="field in settings.input_fields"
                    :key="field.key"
                    class="flex items-center justify-between p-2 rounded-md bg-muted/30"
                  >
                    <span class="text-sm font-mono">{{ field.key }}</span>
                    <span
                      v-if="field.defaultValue"
                      class="text-xs text-muted-foreground"
                    >
                      default: {{ field.defaultValue }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <p
            v-if="error"
            class="text-sm text-destructive mt-4"
          >
            {{ error }}
          </p>
        </div>

        <div class="flex justify-end gap-3 p-4 border-t bg-muted/30">
          <Button
            variant="outline"
            @click="closeDialog"
          >
            Cancel
          </Button>
          <Button
            :loading="isSaving"
            :disabled="!!slugError"
            @click="saveSettings"
          >
            Save Changes
          </Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
