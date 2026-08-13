<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useMediaQuery } from "@vueuse/core";
import { Brain, Database, Globe, Key, MessageSquare, Plus, Search, Share2, Shield, Terminal, Trash2, Users, X } from "lucide-vue-next";

import type { Credential, CredentialListItem, CredentialShare, CredentialType } from "@/types/credential";
import type { Team, TeamShare } from "@/types/team";

import CredentialDialog from "@/components/Credentials/CredentialDialog.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { refreshCredentialsCache } from "@/composables/useExpressionCompletion";
import { cn, formatDate } from "@/lib/utils";
import { credentialsApi, teamsApi } from "@/services/api";
import { CREDENTIAL_TYPE_LABELS } from "@/types/credential";

const credentials = ref<CredentialListItem[]>([]);
const loading = ref(true);
const showDialog = ref(false);
const editingCredential = ref<Credential | null>(null);

const credentialSearchQuery = ref("");
const credentialSearchInput = ref<HTMLInputElement | null>(null);
const isMobile = useMediaQuery("(max-width: 767px)");

const normalizedCredentialSearchQuery = computed((): string =>
  credentialSearchQuery.value.trim().toLowerCase(),
);
const isCredentialSearchActive = computed((): boolean => normalizedCredentialSearchQuery.value.length > 0);

function matchesCredentialSearch(credential: CredentialListItem, normalizedQuery: string): boolean {
  if (normalizedQuery.length === 0) {
    return true;
  }

  return `${credential.name} ${CREDENTIAL_TYPE_LABELS[credential.type]}`.toLowerCase().includes(normalizedQuery);
}

const filteredCredentials = computed<CredentialListItem[]>(() => {
  if (!isCredentialSearchActive.value) {
    return credentials.value;
  }

  return credentials.value.filter((credential) =>
    matchesCredentialSearch(credential, normalizedCredentialSearchQuery.value),
  );
});

const credentialSearchMatchCount = computed((): number => {
  if (!isCredentialSearchActive.value) {
    return credentials.value.length;
  }

  return filteredCredentials.value.length;
});

const credentialCountLabel = computed((): string => {
  if (!isCredentialSearchActive.value) {
    return String(credentials.value.length);
  }

  return `${credentialSearchMatchCount.value}/${credentials.value.length}`;
});

const isMac = computed((): boolean => {
  if (typeof navigator === "undefined") {
    return false;
  }

  return navigator.platform.toLowerCase().startsWith("mac") || navigator.userAgent.includes("Mac");
});

const searchShortcutLabel = computed((): string => {
  if (isMobile.value) return "";
  return isMac.value ? "⌘F" : "Ctrl+F";
});

const searchPlaceholder = computed((): string => {
  const label = searchShortcutLabel.value;
  return label ? `Search credentials (${label})` : "Search credentials";
});

function clearCredentialSearch(): void {
  credentialSearchQuery.value = "";
  credentialSearchInput.value?.blur();
}

function clearCredentialSearchAndKeepFocus(): void {
  credentialSearchQuery.value = "";
  credentialSearchInput.value?.focus();
}

function focusCredentialSearch(): void {
  requestAnimationFrame(() => {
    credentialSearchInput.value?.focus();
    credentialSearchInput.value?.select();
  });
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!target) return false;
  const element = target as HTMLElement;
  return (
    element.tagName === "INPUT" ||
    element.tagName === "TEXTAREA" ||
    element.isContentEditable ||
    element.closest("input, textarea, [contenteditable]") !== null
  );
}

function handleCredentialKeyDown(event: KeyboardEvent): void {
  if (showDialog.value || showShareDialog.value) return;

  const isTyping = isTypingTarget(event.target);
  const isMeta = event.metaKey || event.ctrlKey;
  const key = event.key.toLowerCase();

  if (
    key === "escape" &&
    isCredentialSearchActive.value &&
    (!isTyping || event.target === credentialSearchInput.value)
  ) {
    event.preventDefault();
    clearCredentialSearch();
    return;
  }

  if (
    isMeta &&
    key === "f" &&
    (!isTyping || event.target === credentialSearchInput.value)
  ) {
    event.preventDefault();
    focusCredentialSearch();
  }
}

const showShareDialog = ref(false);
const sharingCredential = ref<CredentialListItem | null>(null);
const credentialShares = ref<CredentialShare[]>([]);
const credentialTeamShares = ref<TeamShare[]>([]);
const teams = ref<Team[]>([]);
const shareEmail = ref("");
const shareTeamId = ref("");
const sharingLoading = ref(false);
const shareError = ref("");

onMounted(async () => {
  await loadCredentials();
  window.addEventListener("keydown", handleCredentialKeyDown);
  const unsub = onDismissOverlays(() => {
    showDialog.value = false;
    showShareDialog.value = false;
    clearCredentialSearch();
  });
  onUnmounted(() => {
    window.removeEventListener("keydown", handleCredentialKeyDown);
    unsub();
  });
});

async function loadCredentials(): Promise<void> {
  loading.value = true;
  try {
    credentials.value = await credentialsApi.list();
  } finally {
    loading.value = false;
  }
}

function getTypeIcon(type: CredentialType): typeof Brain {
  switch (type) {
    case "openai":
      return Brain;
    case "codex":
      return Terminal;
    case "google":
      return Brain;
    case "github":
    case "jira":
    case "linear":
    case "sentry":
      return Key;
    case "custom":
      return Globe;
    case "bearer":
      return Shield;
    case "header":
      return Key;
    case "telegram":
      return MessageSquare;
    case "discord":
    case "discord_trigger":
      return MessageSquare;
    case "slack":
      return MessageSquare;
    case "supabase":
    case "notion":
      return Database;
    default:
      return Key;
  }
}

function getTypeColor(type: CredentialType): string {
  switch (type) {
    case "openai":
      return "bg-green-500/10 text-green-500";
    case "codex":
      return "bg-teal-500/10 text-teal-600 dark:text-teal-400";
    case "google":
      return "bg-blue-500/10 text-blue-500";
    case "github":
      return "bg-slate-500/10 text-slate-500";
    case "jira":
      return "bg-blue-500/10 text-blue-500";
    case "linear":
      return "bg-violet-500/10 text-violet-500";
    case "sentry":
      return "bg-rose-500/10 text-rose-500";
    case "custom":
      return "bg-purple-500/10 text-purple-500";
    case "bearer":
      return "bg-cyan-500/10 text-cyan-500";
    case "header":
      return "bg-amber-500/10 text-amber-500";
    case "telegram":
      return "bg-sky-500/10 text-sky-500";
    case "discord":
    case "discord_trigger":
      return "bg-indigo-500/10 text-indigo-500";
    case "slack":
      return "bg-emerald-500/10 text-emerald-500";
    case "supabase":
      return "bg-lime-500/10 text-lime-600";
    case "notion":
      return "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function openCreateDialog(): void {
  editingCredential.value = null;
  showDialog.value = true;
  pushOverlayState();
}

async function openEditDialog(credential: CredentialListItem): Promise<void> {
  const full = await credentialsApi.get(credential.id);
  editingCredential.value = full;
  showDialog.value = true;
  pushOverlayState();
}

async function deleteCredential(id: string, event: Event): Promise<void> {
  event.stopPropagation();
  if (!confirm("Are you sure you want to delete this credential?")) return;

  await credentialsApi.delete(id);
  credentials.value = credentials.value.filter((c) => c.id !== id);
  refreshCredentialsCache();
}

function handleSaved(credential: Credential): void {
  const index = credentials.value.findIndex((c) => c.id === credential.id);
  if (index >= 0) {
    credentials.value[index] = {
      id: credential.id,
      name: credential.name,
      type: credential.type,
      masked_value: credential.masked_value,
      created_at: credential.created_at,
      header_key: credential.header_key,
    };
  } else {
    credentials.value.unshift({
      id: credential.id,
      name: credential.name,
      type: credential.type,
      masked_value: credential.masked_value,
      created_at: credential.created_at,
      header_key: credential.header_key,
    });
  }
  refreshCredentialsCache();
}

async function openShareDialog(credential: CredentialListItem, event: Event): Promise<void> {
  event.stopPropagation();
  sharingCredential.value = credential;
  shareEmail.value = "";
  shareTeamId.value = "";
  shareError.value = "";
  sharingLoading.value = true;
  showShareDialog.value = true;
  pushOverlayState();
  try {
    const [userShares, teamShares, teamList] = await Promise.all([
      credentialsApi.listShares(credential.id),
      credentialsApi.listTeamShares(credential.id),
      teamsApi.list(),
    ]);
    credentialShares.value = userShares;
    credentialTeamShares.value = teamShares;
    teams.value = teamList;
  } catch {
    credentialShares.value = [];
    credentialTeamShares.value = [];
    teams.value = [];
  } finally {
    sharingLoading.value = false;
  }
}

async function addCredentialShare(): Promise<void> {
  if (!sharingCredential.value || !shareEmail.value.trim()) return;
  shareError.value = "";
  sharingLoading.value = true;
  try {
    const share = await credentialsApi.addShare(sharingCredential.value.id, shareEmail.value.trim());
    if (!credentialShares.value.find((s) => s.id === share.id)) {
      credentialShares.value.push(share);
    }
    shareEmail.value = "";
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    shareError.value = err.response?.data?.detail || "Failed to share credential";
  } finally {
    sharingLoading.value = false;
  }
}

async function removeCredentialShare(userId: string): Promise<void> {
  if (!sharingCredential.value) return;
  try {
    await credentialsApi.removeShare(sharingCredential.value.id, userId);
    credentialShares.value = credentialShares.value.filter((s) => s.user_id !== userId);
  } catch {
    shareError.value = "Failed to remove share";
  }
}

const teamOptions = computed(() => {
  const shared = new Set(credentialTeamShares.value.map((s) => s.team_id));
  return [
    { value: "", label: "Select a team" },
    ...teams.value
      .filter((t) => !shared.has(t.id))
      .map((t) => ({ value: t.id, label: t.name })),
  ];
});

async function addCredentialTeamShare(): Promise<void> {
  if (!sharingCredential.value || !shareTeamId.value) return;
  shareError.value = "";
  sharingLoading.value = true;
  try {
    const share = await credentialsApi.addTeamShare(sharingCredential.value.id, shareTeamId.value);
    credentialTeamShares.value = [...credentialTeamShares.value, share];
    shareTeamId.value = "";
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    shareError.value = err.response?.data?.detail || "Failed to share with team";
  } finally {
    sharingLoading.value = false;
  }
}

async function removeCredentialTeamShare(teamId: string): Promise<void> {
  if (!sharingCredential.value) return;
  try {
    await credentialsApi.removeTeamShare(sharingCredential.value.id, teamId);
    credentialTeamShares.value = credentialTeamShares.value.filter((s) => s.team_id !== teamId);
  } catch {
    shareError.value = "Failed to remove team share";
  }
}
</script>

<template>
  <div class="overflow-x-hidden">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
      <div>
        <div class="flex items-center gap-3">
          <h2 class="text-2xl md:text-3xl font-bold tracking-tight">
            Credentials
          </h2>
          <span
            v-if="!loading && credentials.length > 0"
            class="inline-flex items-center px-2 py-px rounded-full text-xs font-medium bg-primary/10 text-primary ring-1 ring-inset ring-primary/20 mt-0.5 dark:bg-primary/15 dark:text-accent-foreground dark:ring-primary/35"
          >
            {{ credentialCountLabel }}
          </span>
        </div>
        <p class="text-muted-foreground mt-1">
          Manage API keys and authentication credentials
        </p>
      </div>
      <div class="flex flex-col sm:flex-row sm:items-center justify-end gap-2 sm:gap-3">
        <div
          v-if="!loading && credentials.length > 0"
          class="relative w-full sm:w-72 md:w-80"
        >
          <Search class="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            id="credential-search"
            ref="credentialSearchInput"
            v-model="credentialSearchQuery"
            type="text"
            autocomplete="off"
            class="h-11 min-h-[44px] md:h-9 w-full rounded-xl border border-border bg-background px-9 py-2 text-sm shadow-sm transition-all duration-200 placeholder:text-muted-foreground/60 hover:border-border/80 focus-visible:outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/15"
            :placeholder="searchPlaceholder"
            @keydown.esc.prevent.stop="clearCredentialSearch"
          >
          <button
            v-if="isCredentialSearchActive"
            type="button"
            title="Clear search"
            class="absolute right-1.5 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
            @click="clearCredentialSearchAndKeepFocus"
          >
            <X class="h-4 w-4" />
          </button>
        </div>
        <Button
          variant="gradient"
          @click="openCreateDialog"
        >
          <Plus class="w-4 h-4" />
          New Credential
        </Button>
      </div>
    </div>

    <div
      v-if="loading"
      class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
    >
      <Card
        v-for="i in 3"
        :key="i"
        class="p-6"
      >
        <div class="flex items-start gap-3 mb-4">
          <div class="w-11 h-11 rounded-xl bg-muted animate-pulse" />
          <div class="flex-1">
            <div class="h-5 bg-muted rounded-lg w-2/3 mb-2 animate-pulse" />
            <div class="h-3 bg-muted rounded w-1/3 animate-pulse" />
          </div>
        </div>
        <div class="h-4 bg-muted rounded w-full mb-2 animate-pulse" />
        <div class="h-4 bg-muted rounded w-1/2 animate-pulse" />
      </Card>
    </div>

    <div
      v-else-if="credentials.length === 0"
      class="text-center py-16"
    >
      <div class="empty-state-icon flex items-center justify-center w-20 h-20 rounded-2xl mx-auto mb-6">
        <Key class="w-10 h-10 text-primary" />
      </div>
      <h3 class="text-xl font-semibold mb-2">
        No credentials yet
      </h3>
      <p class="text-muted-foreground mb-6 max-w-sm mx-auto">
        Add your first credential to connect to AI providers
      </p>
      <Button
        variant="gradient"
        @click="openCreateDialog"
      >
        <Plus class="w-4 h-4" />
        Add Credential
      </Button>
    </div>

    <div
      v-else-if="isCredentialSearchActive && credentialSearchMatchCount === 0"
      class="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/70 bg-muted/10 px-4 py-16 text-center"
    >
      <Search class="mb-3 h-8 w-8 text-muted-foreground/60" />
      <p class="text-sm font-medium text-foreground">
        No credentials found
      </p>
      <p class="mt-1 max-w-md text-xs text-muted-foreground">
        Try a different name or type.
      </p>
    </div>

    <div
      v-else
      class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
    >
      <Card
        v-for="(credential, index) in filteredCredentials"
        :key="credential.id"
        :data-testid="`credential-card-${credential.id}`"
        :class="cn(
          'credential-card p-5 cursor-pointer group',
          credential.is_shared && 'shared-card'
        )"
        :style="{ animationDelay: `${index * 50}ms` }"
        @click="!credential.is_shared && openEditDialog(credential)"
      >
        <div class="flex items-start justify-between mb-3">
          <div class="flex items-center gap-3">
            <div
              :class="[
                'credential-icon flex items-center justify-center w-11 h-11 rounded-xl transition-all',
                getTypeColor(credential.type)
              ]"
            >
              <component
                :is="getTypeIcon(credential.type)"
                class="w-5 h-5"
              />
            </div>
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <h3 class="font-semibold text-base group-hover:text-primary transition-colors">
                  {{ credential.name }}
                </h3>
                <span
                  v-if="credential.is_shared"
                  class="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-accent-blue/10 text-accent-blue"
                >
                  <Users class="w-3 h-3" />
                  Shared
                </span>
              </div>
              <p class="text-xs text-muted-foreground">
                {{ CREDENTIAL_TYPE_LABELS[credential.type] }}
              </p>
            </div>
          </div>
          <div
            v-if="!credential.is_shared"
            class="flex items-center gap-0.5"
          >
            <Button
              variant="ghost"
              size="icon"
              class="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-primary h-8 w-8"
              title="Share credential"
              @click="openShareDialog(credential, $event)"
            >
              <Share2 class="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              :data-testid="`credential-delete-${credential.id}`"
              class="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive h-8 w-8"
              title="Delete credential"
              @click="deleteCredential(credential.id, $event)"
            >
              <Trash2 class="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div class="space-y-2">
          <div
            v-if="credential.masked_value"
            class="text-xs font-mono text-muted-foreground bg-muted/30 px-3 py-1.5 rounded-lg border border-border/30"
          >
            {{ credential.masked_value }}
          </div>
          <div class="text-xs text-muted-foreground">
            <span v-if="credential.is_shared && credential.shared_by">
              Shared by {{ credential.shared_by }}
            </span>
            <span v-else>
              Created {{ formatDate(credential.created_at) }}
            </span>
          </div>
        </div>

        <div class="mt-3 pt-3 border-t border-border/30">
          <p class="text-xs text-muted-foreground font-mono">
            $credentials.{{ credential.name }}
          </p>
        </div>
      </Card>
    </div>

    <CredentialDialog
      :open="showDialog"
      :credential="editingCredential"
      @close="showDialog = false"
      @saved="handleSaved"
    />

    <Dialog
      :open="showShareDialog"
      title="Share Credential"
      @close="showShareDialog = false"
    >
      <div class="space-y-4">
        <p class="text-sm text-muted-foreground">
          Share <strong>{{ sharingCredential?.name }}</strong> with other users.
          They will be able to use this credential in their workflows.
        </p>

        <div class="space-y-3">
          <div>
            <Label class="text-xs">Share with user</Label>
            <div class="flex gap-2 mt-1">
              <Input
                v-model="shareEmail"
                type="email"
                placeholder="user@example.com"
                class="flex-1"
                @keyup.enter="addCredentialShare"
              />
              <Button
                :disabled="!shareEmail.trim() || sharingLoading"
                @click="addCredentialShare"
              >
                Share
              </Button>
            </div>
          </div>
          <div>
            <Label class="text-xs">Share with team</Label>
            <div class="flex gap-2 mt-1">
              <Select
                v-model="shareTeamId"
                :options="teamOptions"
                class="flex-1"
              />
              <Button
                :disabled="!shareTeamId || sharingLoading"
                @click="addCredentialTeamShare"
              >
                <Users class="w-4 h-4" />
                Add
              </Button>
            </div>
          </div>
        </div>

        <p
          v-if="shareError"
          class="text-sm text-destructive"
        >
          {{ shareError }}
        </p>

        <div class="space-y-2">
          <Label>Shared with users:</Label>
          <div
            v-if="credentialShares.length > 0"
            class="space-y-2 max-h-32 overflow-y-auto"
          >
            <div
              v-for="share in credentialShares"
              :key="share.id"
              class="flex items-center justify-between p-2 rounded bg-muted/50"
            >
              <div>
                <p class="text-sm font-medium">
                  {{ share.name }}
                </p>
                <p class="text-xs text-muted-foreground">
                  {{ share.email }}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="removeCredentialShare(share.user_id)"
              >
                <X class="w-4 h-4" />
              </Button>
            </div>
          </div>
          <p
            v-else-if="!sharingLoading"
            class="text-sm text-muted-foreground"
          >
            No users
          </p>
        </div>
        <div class="space-y-2">
          <Label>Shared with teams:</Label>
          <div
            v-if="credentialTeamShares.length > 0"
            class="space-y-2 max-h-32 overflow-y-auto"
          >
            <div
              v-for="share in credentialTeamShares"
              :key="share.id"
              class="flex items-center justify-between p-2 rounded bg-muted/50"
            >
              <p class="text-sm font-medium">
                {{ share.team_name }}
              </p>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="removeCredentialTeamShare(share.team_id)"
              >
                <X class="w-4 h-4" />
              </Button>
            </div>
          </div>
          <p
            v-else-if="!sharingLoading"
            class="text-sm text-muted-foreground"
          >
            No teams
          </p>
        </div>
      </div>
    </Dialog>
  </div>
</template>

<style scoped>
.empty-state-icon {
  background: linear-gradient(
    135deg,
    hsl(var(--primary) / 0.15) 0%,
    hsl(var(--accent-blue) / 0.1) 100%
  );
  box-shadow:
    0 2px 8px hsl(var(--primary) / 0.1),
    inset 0 1px 0 hsl(0 0% 100% / 0.1);
}

.credential-card {
  animation: fade-in 0.3s ease-out both;
}

.credential-icon {
  transition: all 0.3s ease;
}

.credential-card:hover .credential-icon {
  transform: scale(1.05);
}

.shared-card {
  border-left: 3px solid hsl(var(--accent-blue));
}

@keyframes fade-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
