<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";

import type { CredentialListItem } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import {
  credentialsApi,
  observabilityApi,
  voiceApi,
  type ObservabilityStatus,
  type VoiceInfo,
} from "@/services/api";
import {
  installPlugin,
  listPlugins,
  setPluginEnabled,
  uninstallPlugin,
} from "@/services/plugins";
import { useAuthStore } from "@/stores/auth";

import { clearPluginIconCache } from "@/components/Panels/PluginIcon.vue";

import type { PluginSummary } from "@/types/workflow";

type SettingsTab = "profile" | "security" | "voice" | "observability" | "plugins";

const props = defineProps<{
  open: boolean;
  initialTab?: SettingsTab;
}>();

const emit = defineEmits<{
  close: [];
}>();

const authStore = useAuthStore();
const router = useRouter();

const activeTab = ref<SettingsTab>("profile");

const observabilityStatus = ref<ObservabilityStatus | null>(null);
const loadingObservability = ref(false);

async function loadObservabilityStatus(): Promise<void> {
  loadingObservability.value = true;
  try {
    observabilityStatus.value = await observabilityApi.getStatus();
  } catch {
    observabilityStatus.value = null;
  } finally {
    loadingObservability.value = false;
  }
}

const pluginsEnabled = ref(false);
const installedPlugins = ref<PluginSummary[]>([]);
const loadingPlugins = ref(false);
const pluginError = ref<string | null>(null);
const pluginBusy = ref(false);

async function loadPlugins(): Promise<void> {
  loadingPlugins.value = true;
  pluginError.value = null;
  clearPluginIconCache();
  try {
    installedPlugins.value = await listPlugins();
    pluginsEnabled.value = true;
  } catch {
    // 404 => plugins disabled on this instance.
    pluginsEnabled.value = false;
    installedPlugins.value = [];
  } finally {
    loadingPlugins.value = false;
  }
}

function pluginErrorMessage(err: unknown): string {
  if (typeof err === "object" && err !== null && "response" in err) {
    const response = (err as { response?: { data?: { detail?: string } } }).response;
    if (response?.data?.detail) return response.data.detail;
  }
  return err instanceof Error ? err.message : "Plugin operation failed";
}

async function handleInstallFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  pluginBusy.value = true;
  pluginError.value = null;
  try {
    await installPlugin(file);
    await loadPlugins();
  } catch (err) {
    pluginError.value = pluginErrorMessage(err);
  } finally {
    pluginBusy.value = false;
    input.value = "";
  }
}

async function handleTogglePlugin(plugin: PluginSummary): Promise<void> {
  pluginBusy.value = true;
  pluginError.value = null;
  try {
    await setPluginEnabled(plugin.id, !plugin.enabled);
    await loadPlugins();
  } catch (err) {
    pluginError.value = pluginErrorMessage(err);
  } finally {
    pluginBusy.value = false;
  }
}

async function handleUninstallPlugin(plugin: PluginSummary): Promise<void> {
  pluginBusy.value = true;
  pluginError.value = null;
  try {
    await uninstallPlugin(plugin.id);
    await loadPlugins();
  } catch (err) {
    pluginError.value = pluginErrorMessage(err);
  } finally {
    pluginBusy.value = false;
  }
}

const savingProfile = ref(false);
const savingPassword = ref(false);

const name = ref("");
const userRules = ref("");

const elevenlabsCredentials = ref<CredentialListItem[]>([]);
const voices = ref<VoiceInfo[]>([]);
const selectedTtsCredentialId = ref<string>("");
const selectedVoiceId = ref<string>("");
const loadingVoices = ref(false);
const voiceError = ref<string | null>(null);
const savingVoice = ref(false);

const credentialOptions = computed(() => [
  { value: "", label: "Select a credential" },
  ...elevenlabsCredentials.value.map((c) => ({ value: c.id, label: c.name })),
]);
const voiceOptions = computed(() => [
  { value: "", label: "Select a voice" },
  ...voices.value.map((v) => ({ value: v.voice_id, label: v.name })),
]);

async function loadElevenLabsCredentials(): Promise<void> {
  elevenlabsCredentials.value = await credentialsApi.listByType("elevenlabs");
}

async function loadVoices(): Promise<void> {
  if (!selectedTtsCredentialId.value) {
    voices.value = [];
    return;
  }
  loadingVoices.value = true;
  voiceError.value = null;
  try {
    voices.value = await voiceApi.listVoices(selectedTtsCredentialId.value);
  } catch {
    voiceError.value = "Could not load voices. Check the credential.";
    voices.value = [];
  } finally {
    loadingVoices.value = false;
  }
}

watch(selectedTtsCredentialId, () => {
  void loadVoices();
});

function goToCredentialsTab(): void {
  emit("close");
  void router.push({ name: "dashboard", query: { tab: "credentials" } });
}

async function handleSaveVoice(): Promise<void> {
  savingVoice.value = true;
  try {
    await authStore.updateUser({
      tts_credential_id: selectedTtsCredentialId.value || null,
      tts_voice_id: selectedVoiceId.value || null,
    });
    emit("close");
  } finally {
    savingVoice.value = false;
  }
}

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
      activeTab.value = props.initialTab ?? "profile";
      currentPassword.value = "";
      newPassword.value = "";
      confirmNewPassword.value = "";
      passwordError.value = null;
      passwordSuccess.value = null;
      selectedTtsCredentialId.value = authStore.user.tts_credential_id ?? "";
      selectedVoiceId.value = authStore.user.tts_voice_id ?? "";
      void loadElevenLabsCredentials().then(loadVoices);
      if (activeTab.value === "observability") {
        void loadObservabilityStatus();
      }
      if (activeTab.value === "plugins") {
        void loadPlugins();
      }
    }
  },
  { immediate: true },
);

watch(activeTab, (tab) => {
  if (tab === "observability" && observabilityStatus.value === null) {
    void loadObservabilityStatus();
  }
  if (tab === "plugins") {
    void loadPlugins();
  }
});

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
    title="Settings"
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
        <button
          type="button"
          class="px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
          :class="activeTab === 'voice' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'voice'"
        >
          Voice
        </button>
        <button
          type="button"
          class="px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
          :class="activeTab === 'observability' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'observability'"
        >
          Observability
        </button>
        <button
          type="button"
          class="px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
          :class="activeTab === 'plugins' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'plugins'"
        >
          Plugins
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
        v-else-if="activeTab === 'security'"
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

      <div
        v-else-if="activeTab === 'voice'"
        class="space-y-5"
      >
        <div class="space-y-2">
          <Label>ElevenLabs Credential</Label>
          <p class="text-xs text-muted-foreground">
            Used to read messages aloud and power interactive voice mode in chat.
          </p>
          <Select
            v-model="selectedTtsCredentialId"
            :options="credentialOptions"
          />
          <Button
            variant="outline"
            type="button"
            class="mt-1"
            @click="goToCredentialsTab"
          >
            Add credential
          </Button>
        </div>

        <div class="space-y-2">
          <Label>Voice</Label>
          <Select
            v-model="selectedVoiceId"
            :options="voiceOptions"
            :disabled="!selectedTtsCredentialId || loadingVoices"
          />
          <p
            v-if="voiceError"
            class="text-xs text-destructive"
          >
            {{ voiceError }}
          </p>
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
            type="button"
            :loading="savingVoice"
            :disabled="!selectedTtsCredentialId || !selectedVoiceId"
            @click="handleSaveVoice"
          >
            Save Voice Settings
          </Button>
        </div>
      </div>

      <div
        v-else-if="activeTab === 'observability'"
        class="space-y-5"
      >
        <p class="text-xs text-muted-foreground">
          OpenTelemetry traces every workflow and node execution so you can inspect them in
          any OTLP-compatible backend (Jaeger, Grafana Tempo, Honeycomb, Datadog, and more).
          Configure it with the <code>HEYM_OTEL_*</code> environment variables; this panel is
          read-only.
        </p>

        <div
          v-if="loadingObservability"
          class="text-xs text-muted-foreground"
        >
          Loading status…
        </div>

        <div
          v-else-if="observabilityStatus"
          class="space-y-3"
        >
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium">Status</span>
            <span
              class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold"
              :class="observabilityStatus.enabled
                ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                : 'bg-muted text-muted-foreground'"
            >
              {{ observabilityStatus.enabled ? "Enabled" : "Disabled" }}
            </span>
          </div>

          <dl class="grid grid-cols-[max-content_1fr] items-baseline gap-x-4 gap-y-1.5 text-sm">
            <dt class="text-muted-foreground">
              Service name
            </dt>
            <dd class="font-mono text-xs break-all">
              {{ observabilityStatus.service_name }}
            </dd>

            <template v-if="observabilityStatus.enabled">
              <dt class="text-muted-foreground">
                OTLP endpoint
              </dt>
              <dd class="font-mono text-xs break-all">
                {{ observabilityStatus.endpoint || "(SDK default)" }}
              </dd>

              <dt class="text-muted-foreground">
                Sampler ratio
              </dt>
              <dd class="font-mono text-xs">
                {{ observabilityStatus.sampler_ratio }}
              </dd>

              <dt class="text-muted-foreground">
                Capture node I/O
              </dt>
              <dd class="font-mono text-xs">
                {{ observabilityStatus.capture_node_io ? "on" : "off" }}
              </dd>

              <dt class="text-muted-foreground">
                Instrumented
              </dt>
              <dd class="text-xs">
                {{ observabilityStatus.instrumented.join(", ") }}
              </dd>

              <dt class="text-muted-foreground">
                Spans
              </dt>
              <dd class="text-xs">
                {{ observabilityStatus.spans.join(", ") }}
              </dd>
            </template>
          </dl>

          <div
            v-if="!observabilityStatus.enabled"
            class="rounded-lg border border-border bg-muted/40 p-3 text-xs text-muted-foreground space-y-1"
          >
            <p class="font-medium text-foreground">
              Enable tracing
            </p>
            <p>Set these environment variables on the backend, then restart:</p>
            <pre class="mt-1 whitespace-pre-wrap font-mono leading-relaxed">HEYM_OTEL_ENABLED=true
HEYM_OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
HEYM_OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer &lt;token&gt;</pre>
          </div>
        </div>

        <div
          v-else
          class="text-xs text-destructive"
        >
          Could not load observability status.
        </div>

        <div class="flex justify-end gap-3 pt-2">
          <Button
            variant="outline"
            type="button"
            @click="emit('close')"
          >
            Close
          </Button>
        </div>
      </div>

      <div
        v-else-if="activeTab === 'plugins'"
        class="space-y-5"
      >
        <p class="text-xs text-muted-foreground">
          Plugins add custom nodes (actions and triggers) to this instance. Installing or
          removing a plugin runs server-side code, so it is restricted to operators listed in
          <code>HEYM_PLUGIN_ADMIN_EMAILS</code>.
        </p>

        <div
          v-if="loadingPlugins"
          class="text-xs text-muted-foreground"
        >
          Loading plugins…
        </div>

        <div
          v-else-if="!pluginsEnabled"
          class="rounded-lg border border-border bg-muted/40 p-3 text-xs text-muted-foreground space-y-1"
        >
          <p class="font-medium text-foreground">
            Plugins are disabled
          </p>
          <p>Set these environment variables on the backend, then restart:</p>
          <pre class="mt-1 whitespace-pre-wrap font-mono leading-relaxed">HEYM_PLUGINS_ENABLED=true
HEYM_PLUGIN_ADMIN_EMAILS=you@example.com</pre>
        </div>

        <template v-else>
          <div class="space-y-2">
            <Label for="plugin-zip">Install a plugin (.zip)</Label>
            <input
              id="plugin-zip"
              type="file"
              accept=".zip"
              :disabled="pluginBusy"
              class="block w-full text-sm text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
              @change="handleInstallFile"
            >
          </div>

          <p
            v-if="pluginError"
            class="text-xs text-destructive"
          >
            {{ pluginError }}
          </p>

          <div
            v-if="installedPlugins.length === 0"
            class="text-xs text-muted-foreground"
          >
            No plugins installed yet.
          </div>

          <ul
            v-else
            class="space-y-2"
          >
            <li
              v-for="plugin in installedPlugins"
              :key="plugin.id"
              class="flex items-center justify-between gap-3 rounded-lg border border-border bg-card/60 p-3"
            >
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium truncate">{{ plugin.name }}</span>
                  <span class="text-xs text-muted-foreground">v{{ plugin.version }}</span>
                </div>
                <p class="text-xs text-muted-foreground line-clamp-1">
                  {{ plugin.description }}
                </p>
                <div class="mt-1 flex flex-wrap gap-1">
                  <span
                    v-for="node in plugin.nodes"
                    :key="node.key"
                    class="text-[10px] rounded px-1.5 py-0.5 bg-muted text-muted-foreground"
                  >
                    {{ node.name }} · {{ node.kind }}
                  </span>
                </div>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <Button
                  variant="outline"
                  size="sm"
                  type="button"
                  :disabled="pluginBusy"
                  @click="handleTogglePlugin(plugin)"
                >
                  {{ plugin.enabled ? "Disable" : "Enable" }}
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  type="button"
                  :disabled="pluginBusy"
                  @click="handleUninstallPlugin(plugin)"
                >
                  Uninstall
                </Button>
              </div>
            </li>
          </ul>
        </template>

        <div class="flex justify-end gap-3 pt-2">
          <Button
            variant="outline"
            type="button"
            @click="emit('close')"
          >
            Close
          </Button>
        </div>
      </div>
    </div>
  </Dialog>
</template>
