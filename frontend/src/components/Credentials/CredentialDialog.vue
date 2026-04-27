<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Eye, EyeOff } from "lucide-vue-next";

import type {
  Credential,
  CredentialConfig,
  CredentialType,
} from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { credentialsApi } from "@/services/api";
import {
  CREDENTIAL_TYPE_DESCRIPTIONS,
  CREDENTIAL_TYPE_LABELS,
} from "@/types/credential";

interface Props {
  open: boolean;
  credential?: Credential | null;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  close: [];
  saved: [credential: Credential];
}>();

const isEditing = computed(() => !!props.credential);

const name = ref("");
const type = ref<CredentialType>("openai");
const apiKey = ref("");
const baseUrl = ref("");
const bearerToken = ref("");
const headerKey = ref("");
const headerValue = ref("");
const telegramBotToken = ref("");
const telegramSecretToken = ref("");
const webhookUrl = ref("");
const signingSecret = ref("");
const imapHost = ref("");
const imapPort = ref("993");
const imapUsername = ref("");
const imapPassword = ref("");
const imapMailbox = ref("INBOX");
const imapUseSsl = ref(true);
const smtpServer = ref("");
const smtpPort = ref("587");
const smtpEmail = ref("");
const smtpPassword = ref("");
const redisHost = ref("");
const redisPort = ref("6379");
const redisPassword = ref("");
const redisDb = ref("0");
const qdrantHost = ref("");
const qdrantPort = ref("6333");
const qdrantApiKey = ref("");
const qdrantOpenaiApiKey = ref("");
const gristApiKey = ref("");
const gristServerUrl = ref("");
const rabbitmqHost = ref("");
const rabbitmqPort = ref("5672");
const rabbitmqUsername = ref("");
const rabbitmqPassword = ref("");
const rabbitmqVhost = ref("/");
const cohereApiKey = ref("");
const flaresolverrUrl = ref("");
const gsClientId = ref("");
const gsClientSecret = ref("");
const gsOAuthConnected = ref(false);
const gsOAuthConnecting = ref(false);
// Holds the credential fetched after a successful OAuth flow in this session
const gsConnectedCredential = ref<import("@/types/credential").Credential | null>(null);
const bqClientId = ref("");
const bqClientSecret = ref("");
const bqOAuthConnected = ref(false);
const bqOAuthConnecting = ref(false);
const bqConnectedCredential = ref<import("@/types/credential").Credential | null>(null);
const showApiKey = ref(false);
const saving = ref(false);
const error = ref("");

const typeOptions = [
  { value: "openai", label: CREDENTIAL_TYPE_LABELS.openai },
  { value: "google", label: CREDENTIAL_TYPE_LABELS.google },
  { value: "custom", label: CREDENTIAL_TYPE_LABELS.custom },
  { value: "bearer", label: CREDENTIAL_TYPE_LABELS.bearer },
  { value: "header", label: CREDENTIAL_TYPE_LABELS.header },
  { value: "telegram", label: CREDENTIAL_TYPE_LABELS.telegram },
  { value: "slack", label: CREDENTIAL_TYPE_LABELS.slack },
  { value: "slack_trigger", label: CREDENTIAL_TYPE_LABELS.slack_trigger },
  { value: "imap", label: CREDENTIAL_TYPE_LABELS.imap },
  { value: "smtp", label: CREDENTIAL_TYPE_LABELS.smtp },
  { value: "redis", label: CREDENTIAL_TYPE_LABELS.redis },
  { value: "qdrant", label: CREDENTIAL_TYPE_LABELS.qdrant },
  { value: "grist", label: CREDENTIAL_TYPE_LABELS.grist },
  { value: "rabbitmq", label: CREDENTIAL_TYPE_LABELS.rabbitmq },
  { value: "cohere", label: CREDENTIAL_TYPE_LABELS.cohere },
  { value: "flaresolverr", label: CREDENTIAL_TYPE_LABELS.flaresolverr },
  { value: "google_sheets", label: CREDENTIAL_TYPE_LABELS.google_sheets },
  { value: "bigquery", label: CREDENTIAL_TYPE_LABELS.bigquery },
];

watch(
  () => props.open,
  (open) => {
    if (open) {
      if (props.credential) {
        name.value = props.credential.name;
        type.value = props.credential.type;
        apiKey.value = "";
        baseUrl.value = "";
        bearerToken.value = "";
        headerKey.value = props.credential.header_key || "";
        headerValue.value = "";
        telegramBotToken.value = "";
        telegramSecretToken.value = "";
        webhookUrl.value = "";
        signingSecret.value = "";
        imapHost.value = "";
        imapPort.value = "993";
        imapUsername.value = "";
        imapPassword.value = "";
        imapMailbox.value = "INBOX";
        imapUseSsl.value = true;
        smtpServer.value = "";
        smtpPort.value = "587";
        smtpEmail.value = "";
        smtpPassword.value = "";
        redisHost.value = "";
        redisPort.value = "6379";
        redisPassword.value = "";
        redisDb.value = "0";
        qdrantHost.value = "";
        qdrantPort.value = "6333";
        qdrantApiKey.value = "";
        qdrantOpenaiApiKey.value = "";
        gristApiKey.value = "";
        gristServerUrl.value = "";
        rabbitmqHost.value = "";
        rabbitmqPort.value = "5672";
        rabbitmqUsername.value = "";
        rabbitmqPassword.value = "";
        rabbitmqVhost.value = "/";
        cohereApiKey.value = "";
        flaresolverrUrl.value = "";
        gsClientId.value = "";
        gsClientSecret.value = "";
        // Detect connected state from masked_value set by the backend
        gsOAuthConnected.value = props.credential.masked_value === "connected";
        gsConnectedCredential.value = null;
        bqClientId.value = "";
        bqClientSecret.value = "";
        bqOAuthConnected.value = props.credential.masked_value === "connected" && props.credential.type === "bigquery";
        bqConnectedCredential.value = null;
      } else {
        name.value = "";
        type.value = "openai";
        apiKey.value = "";
        baseUrl.value = "";
        bearerToken.value = "";
        headerKey.value = "";
        headerValue.value = "";
        telegramBotToken.value = "";
        telegramSecretToken.value = "";
        webhookUrl.value = "";
        signingSecret.value = "";
        imapHost.value = "";
        imapPort.value = "993";
        imapUsername.value = "";
        imapPassword.value = "";
        imapMailbox.value = "INBOX";
        imapUseSsl.value = true;
        smtpServer.value = "";
        smtpPort.value = "587";
        smtpEmail.value = "";
        smtpPassword.value = "";
        redisHost.value = "";
        redisPort.value = "6379";
        redisPassword.value = "";
        redisDb.value = "0";
        qdrantHost.value = "";
        qdrantPort.value = "6333";
        qdrantApiKey.value = "";
        qdrantOpenaiApiKey.value = "";
        gristApiKey.value = "";
        gristServerUrl.value = "";
        rabbitmqHost.value = "";
        rabbitmqPort.value = "5672";
        rabbitmqUsername.value = "";
        rabbitmqPassword.value = "";
        rabbitmqVhost.value = "/";
        cohereApiKey.value = "";
        flaresolverrUrl.value = "";
        gsClientId.value = "";
        gsClientSecret.value = "";
        gsOAuthConnected.value = false;
        gsConnectedCredential.value = null;
        bqClientId.value = "";
        bqClientSecret.value = "";
        bqOAuthConnected.value = false;
        bqConnectedCredential.value = null;
      }
      showApiKey.value = false;
      error.value = "";
    }
  }
);

const isValid = computed(() => {
  if (!name.value.trim()) return false;

  if (type.value === "openai" || type.value === "google") {
    return !!apiKey.value.trim() || isEditing.value;
  } else if (type.value === "custom") {
    return (!!apiKey.value.trim() && !!baseUrl.value.trim()) || isEditing.value;
  } else if (type.value === "bearer") {
    return !!bearerToken.value.trim() || isEditing.value;
  } else if (type.value === "header") {
    return (!!headerKey.value.trim() && !!headerValue.value.trim()) || isEditing.value;
  } else if (type.value === "telegram") {
    return !!telegramBotToken.value.trim() || isEditing.value;
  } else if (type.value === "slack") {
    return !!webhookUrl.value.trim() || isEditing.value;
  } else if (type.value === "slack_trigger") {
    return !!signingSecret.value.trim() || isEditing.value;
  } else if (type.value === "imap") {
    return (
      !!imapHost.value.trim() &&
      !!imapPort.value.trim() &&
      !!imapUsername.value.trim() &&
      !!imapPassword.value.trim()
    ) || isEditing.value;
  } else if (type.value === "smtp") {
    return (
      !!smtpServer.value.trim() &&
      !!smtpPort.value.trim() &&
      !!smtpEmail.value.trim() &&
      !!smtpPassword.value.trim()
    ) || isEditing.value;
  } else if (type.value === "redis") {
    return (
      !!redisHost.value.trim() &&
      !!redisPort.value.trim()
    ) || isEditing.value;
  } else if (type.value === "qdrant") {
    return (
      !!qdrantHost.value.trim() &&
      !!qdrantPort.value.trim() &&
      !!qdrantOpenaiApiKey.value.trim()
    ) || isEditing.value;
  } else if (type.value === "grist") {
    return (
      !!gristApiKey.value.trim() &&
      !!gristServerUrl.value.trim()
    ) || isEditing.value;
  } else if (type.value === "rabbitmq") {
    return (
      !!rabbitmqHost.value.trim() &&
      !!rabbitmqUsername.value.trim() &&
      !!rabbitmqPassword.value.trim()
    ) || isEditing.value;
  } else if (type.value === "cohere") {
    return !!cohereApiKey.value.trim() || isEditing.value;
  } else if (type.value === "flaresolverr") {
    return !!flaresolverrUrl.value.trim() || isEditing.value;
  } else if (type.value === "google_sheets") {
    // Valid only when OAuth was completed (new) or when editing an existing credential
    return gsOAuthConnected.value || isEditing.value;
  } else if (type.value === "bigquery") {
    return bqOAuthConnected.value || isEditing.value;
  }
  return false;
});

function buildConfig(): CredentialConfig {
  if (type.value === "openai") {
    return { api_key: apiKey.value };
  } else if (type.value === "google") {
    return { api_key: apiKey.value };
  } else if (type.value === "custom") {
    return { base_url: baseUrl.value, api_key: apiKey.value };
  } else if (type.value === "bearer") {
    return { bearer_token: bearerToken.value };
  } else if (type.value === "header") {
    return { header_key: headerKey.value, header_value: headerValue.value };
  } else if (type.value === "telegram") {
    return {
      bot_token: telegramBotToken.value.trim(),
      secret_token: telegramSecretToken.value.trim() || undefined,
    };
  } else if (type.value === "imap") {
    return {
      imap_host: imapHost.value.trim(),
      imap_port: imapPort.value.trim(),
      imap_username: imapUsername.value.trim(),
      imap_password: imapPassword.value,
      imap_mailbox: imapMailbox.value.trim() || "INBOX",
      imap_use_ssl: imapUseSsl.value,
    };
  } else if (type.value === "smtp") {
    return {
      smtp_server: smtpServer.value,
      smtp_port: smtpPort.value,
      smtp_email: smtpEmail.value,
      smtp_password: smtpPassword.value,
    };
  } else if (type.value === "redis") {
    return {
      redis_host: redisHost.value,
      redis_port: redisPort.value,
      redis_password: redisPassword.value,
      redis_db: redisDb.value,
    };
  } else if (type.value === "qdrant") {
    return {
      qdrant_host: qdrantHost.value,
      qdrant_port: qdrantPort.value,
      qdrant_api_key: qdrantApiKey.value,
      openai_api_key: qdrantOpenaiApiKey.value,
    };
  } else if (type.value === "grist") {
    return {
      api_key: gristApiKey.value,
      server_url: gristServerUrl.value,
    };
  } else if (type.value === "rabbitmq") {
    return {
      rabbitmq_host: rabbitmqHost.value,
      rabbitmq_port: rabbitmqPort.value,
      rabbitmq_username: rabbitmqUsername.value,
      rabbitmq_password: rabbitmqPassword.value,
      rabbitmq_vhost: rabbitmqVhost.value,
    };
  } else if (type.value === "cohere") {
    return { api_key: cohereApiKey.value };
  } else if (type.value === "slack_trigger") {
    return { signing_secret: signingSecret.value };
  } else if (type.value === "flaresolverr") {
    return { flaresolverr_url: flaresolverrUrl.value };
  } else if (type.value === "google_sheets") {
    return {
      client_id: gsClientId.value.trim(),
      client_secret: gsClientSecret.value.trim(),
    };
  } else if (type.value === "bigquery") {
    return {
      client_id: bqClientId.value.trim(),
      client_secret: bqClientSecret.value.trim(),
    };
  } else {
    return { webhook_url: webhookUrl.value };
  }
}

async function startGoogleSheetsOAuth(): Promise<void> {
  if (!gsClientId.value.trim() || !gsClientSecret.value.trim()) {
    error.value = "Enter Client ID and Client Secret before connecting.";
    return;
  }
  if (!name.value.trim()) {
    error.value = "Enter a name for this credential before connecting.";
    return;
  }

  gsOAuthConnecting.value = true;
  error.value = "";

  try {
    // Save or update the credential first so the backend has client_id / client_secret
    let credId: string;
    if (isEditing.value && props.credential) {
      await credentialsApi.update(props.credential.id, {
        name: name.value,
        config: buildConfig(),
      });
      credId = props.credential.id;
    } else {
      const saved = await credentialsApi.create({
        name: name.value,
        type: "google_sheets",
        config: buildConfig(),
      });
      credId = saved.id;
    }

    const { auth_url } = await credentialsApi.googleSheetsOAuthAuthorize(credId);

    const popup = window.open(auth_url, "google-oauth", "width=520,height=620");

    let pollClosed: ReturnType<typeof setInterval>;

    const onMessage = (evt: MessageEvent): void => {
      if (evt.data?.type === "google-oauth-success" && evt.data.credentialId === credId) {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
        popup?.close();
        // Fetch the fully-updated credential (with tokens) — stay open so user sees "Connected"
        credentialsApi.get(credId).then((cred) => {
          gsConnectedCredential.value = cred;
          gsOAuthConnected.value = true;
          gsOAuthConnecting.value = false;
        }).catch(() => {
          gsOAuthConnected.value = true;
          gsOAuthConnecting.value = false;
        });
      } else if (evt.data?.type === "google-oauth-error") {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
        gsOAuthConnecting.value = false;
        error.value = evt.data.message || "OAuth authorization failed";
      }
    };
    window.addEventListener("message", onMessage);

    // Detect popup closed without completing
    pollClosed = setInterval(() => {
      if (popup?.closed) {
        clearInterval(pollClosed);
        window.removeEventListener("message", onMessage);
        gsOAuthConnecting.value = false;
      }
    }, 500);
  } catch (err) {
    gsOAuthConnecting.value = false;
    error.value = err instanceof Error ? err.message : "OAuth authorization failed";
  }
}

async function startBigQueryOAuth(): Promise<void> {
  if (!bqClientId.value.trim() || !bqClientSecret.value.trim()) {
    error.value = "Enter Client ID and Client Secret before connecting.";
    return;
  }
  if (!name.value.trim()) {
    error.value = "Enter a name for this credential before connecting.";
    return;
  }

  bqOAuthConnecting.value = true;
  error.value = "";

  try {
    let credId: string;
    if (isEditing.value && props.credential) {
      await credentialsApi.update(props.credential.id, {
        name: name.value,
        config: buildConfig(),
      });
      credId = props.credential.id;
    } else {
      const saved = await credentialsApi.create({
        name: name.value,
        type: "bigquery",
        config: buildConfig(),
      });
      credId = saved.id;
    }

    const { auth_url } = await credentialsApi.bigQueryOAuthAuthorize(credId);
    const popup = window.open(auth_url, "bq-oauth", "width=520,height=620");

    let pollClosed: ReturnType<typeof setInterval>;

    const onMessage = (evt: MessageEvent): void => {
      if (evt.data?.type === "google-oauth-success" && evt.data.credentialId === credId) {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
        popup?.close();
        credentialsApi.get(credId).then((cred) => {
          bqConnectedCredential.value = cred;
          bqOAuthConnected.value = true;
          bqOAuthConnecting.value = false;
        }).catch(() => {
          bqOAuthConnected.value = true;
          bqOAuthConnecting.value = false;
        });
      } else if (evt.data?.type === "google-oauth-error") {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
        bqOAuthConnecting.value = false;
        error.value = evt.data.message || "OAuth authorization failed";
      }
    };
    window.addEventListener("message", onMessage);

    pollClosed = setInterval(() => {
      if (popup?.closed) {
        clearInterval(pollClosed);
        window.removeEventListener("message", onMessage);
        bqOAuthConnecting.value = false;
      }
    }, 500);
  } catch (err) {
    bqOAuthConnecting.value = false;
    error.value = err instanceof Error ? err.message : "OAuth authorization failed";
  }
}

async function handleSave(): Promise<void> {
  if (!isValid.value) return;

  saving.value = true;
  error.value = "";

  try {
    let saved: Credential;

    if (isEditing.value && props.credential) {
      const updateData: { name?: string; config?: CredentialConfig } = {};

      if (name.value !== props.credential.name) {
        updateData.name = name.value;
      }

      const headerKeyChanged = headerKey.value.trim() !== (props.credential.header_key || "");
      // google_sheets and bigquery configs are managed entirely by the OAuth callback — never overwrite here
      const hasConfigChange =
        type.value !== "google_sheets" &&
        type.value !== "bigquery" &&
        (apiKey.value.trim() ||
          baseUrl.value.trim() ||
          bearerToken.value.trim() ||
          headerKeyChanged ||
          headerValue.value.trim() ||
          telegramBotToken.value.trim() ||
          telegramSecretToken.value.trim() ||
          webhookUrl.value.trim() ||
          signingSecret.value.trim() ||
          imapHost.value.trim() ||
          imapPort.value.trim() ||
          imapUsername.value.trim() ||
          imapPassword.value.trim() ||
          (imapMailbox.value.trim() && imapMailbox.value.trim() !== "INBOX") ||
          !imapUseSsl.value ||
          smtpServer.value.trim() ||
          smtpPort.value.trim() ||
          smtpEmail.value.trim() ||
          smtpPassword.value.trim() ||
          redisHost.value.trim() ||
          redisPort.value.trim() ||
          redisPassword.value.trim() ||
          redisDb.value.trim() ||
          qdrantHost.value.trim() ||
          qdrantPort.value.trim() ||
          qdrantApiKey.value.trim() ||
          qdrantOpenaiApiKey.value.trim() ||
          gristApiKey.value.trim() ||
          gristServerUrl.value.trim() ||
          rabbitmqHost.value.trim() ||
          rabbitmqPort.value.trim() ||
          rabbitmqUsername.value.trim() ||
          rabbitmqPassword.value.trim() ||
          rabbitmqVhost.value.trim() ||
          cohereApiKey.value.trim() ||
          flaresolverrUrl.value.trim());

      if (hasConfigChange) {
        updateData.config = buildConfig();
      }

      if (Object.keys(updateData).length > 0) {
        saved = await credentialsApi.update(props.credential.id, updateData);
      } else {
        saved = props.credential;
      }
    } else if (type.value === "google_sheets" && gsConnectedCredential.value) {
      // Credential was already created and tokens stored by the OAuth callback
      saved = gsConnectedCredential.value;
    } else if (type.value === "bigquery" && bqConnectedCredential.value) {
      saved = bqConnectedCredential.value;
    } else {
      saved = await credentialsApi.create({
        name: name.value,
        type: type.value,
        config: buildConfig(),
      });
    }

    emit("saved", saved);
    emit("close");
  } catch (err) {
    if (err instanceof Error) {
      error.value = err.message;
    } else {
      error.value = "Failed to save credential";
    }
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="open"
    :title="isEditing ? 'Edit Credential' : 'New Credential'"
    @close="emit('close')"
  >
    <form
      class="space-y-4"
      @submit.prevent="handleSave"
    >
      <div class="space-y-2">
        <Label for="cred-name">Name</Label>
        <Input
          id="cred-name"
          v-model="name"
          placeholder="my-api-key"
          :disabled="saving"
        />
        <p class="text-xs text-muted-foreground">
          Access via: <code class="bg-muted px-1 rounded">${{ `credentials.${name || 'name'}` }}</code>
        </p>
      </div>

      <div
        v-if="!isEditing"
        class="space-y-2"
      >
        <Label for="cred-type">Type</Label>
        <Select
          id="cred-type"
          v-model="type"
          :options="typeOptions"
          :disabled="saving"
        />
        <p class="text-xs text-muted-foreground">
          {{ CREDENTIAL_TYPE_DESCRIPTIONS[type] }}
        </p>
      </div>

      <div
        v-if="type === 'openai' || type === 'google'"
        class="space-y-2"
      >
        <Label for="cred-api-key">API Key</Label>
        <div class="relative">
          <Input
            id="cred-api-key"
            v-model="apiKey"
            :type="showApiKey ? 'text' : 'password'"
            :placeholder="isEditing ? '••••••• (re-enter to update)' : 'sk-...'"
            :disabled="saving"
            class="pr-10"
          />
          <button
            type="button"
            class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            @click="showApiKey = !showApiKey"
          >
            <EyeOff
              v-if="showApiKey"
              class="w-4 h-4"
            />
            <Eye
              v-else
              class="w-4 h-4"
            />
          </button>
        </div>
      </div>

      <template v-if="type === 'custom'">
        <div class="space-y-2">
          <Label for="cred-base-url">Base URL</Label>
          <Input
            id="cred-base-url"
            v-model="baseUrl"
            placeholder="https://api.example.com"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            OpenAI-compatible API endpoint
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-custom-key">API Key</Label>
          <div class="relative">
            <Input
              id="cred-custom-key"
              v-model="apiKey"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'your-api-key'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
        </div>
      </template>

      <div
        v-if="type === 'bearer'"
        class="space-y-2"
      >
        <Label for="cred-bearer-token">Bearer Token</Label>
        <div class="relative">
          <Input
            id="cred-bearer-token"
            v-model="bearerToken"
            :type="showApiKey ? 'text' : 'password'"
            :placeholder="isEditing ? '••••••• (re-enter to update)' : 'your-token-here'"
            :disabled="saving"
            class="pr-10"
          />
          <button
            type="button"
            class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            @click="showApiKey = !showApiKey"
          >
            <EyeOff
              v-if="showApiKey"
              class="w-4 h-4"
            />
            <Eye
              v-else
              class="w-4 h-4"
            />
          </button>
        </div>
        <p class="text-xs text-muted-foreground">
          Token will be sent as: Authorization: Bearer &lt;token&gt;
        </p>
      </div>

      <template v-if="type === 'header'">
        <div class="space-y-2">
          <Label for="cred-header-key">Header Key</Label>
          <Input
            id="cred-header-key"
            v-model="headerKey"
            placeholder="X-API-Key"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            HTTP header name (e.g., X-API-Key, X-Custom-Header)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-header-value">Header Value</Label>
          <div class="relative">
            <Input
              id="cred-header-value"
              v-model="headerValue"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'your-value-here'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            Header value as-is (sent exactly as entered)
          </p>
        </div>
      </template>

      <template v-if="type === 'telegram'">
        <div class="space-y-2">
          <Label for="cred-telegram-bot-token">Bot Token</Label>
          <div class="relative">
            <Input
              id="cred-telegram-bot-token"
              v-model="telegramBotToken"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : '123456789:AA...'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            Bot token from BotFather. Used for both webhook triggers and outbound messages.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-telegram-secret-token">Webhook Secret Token</Label>
          <Input
            id="cred-telegram-secret-token"
            v-model="telegramSecretToken"
            :placeholder="isEditing ? '(optional: re-enter to update)' : 'Optional extra verification secret'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Optional. If set, Telegram must send the same secret in the webhook header before Heym accepts the trigger.
          </p>
        </div>
      </template>

      <template v-if="type === 'slack'">
        <div class="space-y-2">
          <Label for="cred-slack-webhook">Webhook URL</Label>
          <Input
            id="cred-slack-webhook"
            v-model="webhookUrl"
            placeholder="https://hooks.slack.com/services/..."
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Slack incoming webhook URL for the workspace.
          </p>
        </div>
      </template>

      <template v-if="type === 'slack_trigger'">
        <div class="space-y-2">
          <Label for="cred-slack-signing-secret">Signing Secret</Label>
          <Input
            id="cred-slack-signing-secret"
            v-model="signingSecret"
            type="password"
            :placeholder="isEditing ? '(re-enter to update)' : 'Paste your Slack Signing Secret'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Found in your Slack App → Basic Information → App Credentials → Signing Secret.
          </p>
        </div>
      </template>

      <template v-if="type === 'imap'">
        <div class="space-y-2">
          <Label for="cred-imap-host">IMAP Host</Label>
          <Input
            id="cred-imap-host"
            v-model="imapHost"
            :placeholder="isEditing ? '(re-enter to update)' : 'imap.gmail.com'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            IMAP server hostname for the inbox you want to poll.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-imap-port">IMAP Port</Label>
          <Input
            id="cred-imap-port"
            v-model="imapPort"
            placeholder="993"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Port 993 is typical for SSL/TLS. Use 143 only if your server requires non-SSL IMAP.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-imap-username">Username / Email</Label>
          <Input
            id="cred-imap-username"
            v-model="imapUsername"
            :placeholder="isEditing ? '(re-enter to update)' : 'team@example.com'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Account used to sign in to the mailbox.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-imap-password">Password / App Password</Label>
          <div class="relative">
            <Input
              id="cred-imap-password"
              v-model="imapPassword"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'your-app-password'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            Use an app password when your email provider requires one for IMAP access.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-imap-mailbox">Mailbox</Label>
          <Input
            id="cred-imap-mailbox"
            v-model="imapMailbox"
            placeholder="INBOX"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Folder to monitor. Leave as <code>INBOX</code> for the primary mailbox.
          </p>
        </div>

        <div class="rounded-md border p-3 space-y-2">
          <div class="flex items-center gap-2">
            <input
              id="cred-imap-use-ssl"
              v-model="imapUseSsl"
              type="checkbox"
              class="h-4 w-4 rounded border-input bg-background"
              :disabled="saving"
            >
            <Label
              for="cred-imap-use-ssl"
              class="text-sm font-normal"
            >
              Use SSL / TLS
            </Label>
          </div>
          <p class="text-xs text-muted-foreground">
            Recommended for almost all providers. Disable only for legacy self-hosted IMAP servers.
          </p>
        </div>
      </template>

      <template v-if="type === 'smtp'">
        <div class="space-y-2">
          <Label for="cred-smtp-server">SMTP Server</Label>
          <Input
            id="cred-smtp-server"
            v-model="smtpServer"
            :placeholder="isEditing ? '(re-enter to update)' : 'smtp.gmail.com'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            SMTP server hostname (e.g., smtp.gmail.com, smtp.office365.com)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-smtp-port">SMTP Port</Label>
          <Input
            id="cred-smtp-port"
            v-model="smtpPort"
            placeholder="587"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Usually 587 for TLS, 465 for SSL
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-smtp-email">Email Address</Label>
          <Input
            id="cred-smtp-email"
            v-model="smtpEmail"
            :placeholder="isEditing ? '(re-enter to update)' : 'your-email@gmail.com'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Email address used for authentication and as sender
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-smtp-password">Password / App Password</Label>
          <div class="relative">
            <Input
              id="cred-smtp-password"
              v-model="smtpPassword"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'your-app-password'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            For Gmail, use an App Password instead of your account password
          </p>
        </div>
      </template>

      <template v-if="type === 'redis'">
        <div class="space-y-2">
          <Label for="cred-redis-host">Host</Label>
          <Input
            id="cred-redis-host"
            v-model="redisHost"
            :placeholder="isEditing ? '(re-enter to update)' : 'localhost'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Redis server hostname (e.g., localhost, redis.example.com)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-redis-port">Port</Label>
          <Input
            id="cred-redis-port"
            v-model="redisPort"
            placeholder="6379"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Redis port (default: 6379)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-redis-password">Password</Label>
          <div class="relative">
            <Input
              id="cred-redis-password"
              v-model="redisPassword"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : '(optional)'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            Leave empty if Redis has no authentication
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-redis-db">Database Index</Label>
          <Input
            id="cred-redis-db"
            v-model="redisDb"
            placeholder="0"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Redis database number (default: 0)
          </p>
        </div>
      </template>

      <template v-if="type === 'qdrant'">
        <div class="space-y-2">
          <Label for="cred-qdrant-host">QDrant Host</Label>
          <Input
            id="cred-qdrant-host"
            v-model="qdrantHost"
            :placeholder="isEditing ? '(re-enter to update)' : 'localhost'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            QDrant server hostname (e.g., localhost, qdrant.example.com)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-qdrant-port">QDrant Port</Label>
          <Input
            id="cred-qdrant-port"
            v-model="qdrantPort"
            placeholder="6333"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            QDrant HTTP port (default: 6333)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-qdrant-api-key">QDrant API Key</Label>
          <div class="relative">
            <Input
              id="cred-qdrant-api-key"
              v-model="qdrantApiKey"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : '(optional)'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            Leave empty if QDrant has no authentication
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-qdrant-openai-key">OpenAI API Key</Label>
          <div class="relative">
            <Input
              id="cred-qdrant-openai-key"
              v-model="qdrantOpenaiApiKey"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'sk-...'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            OpenAI API key for text-embedding-3-large embeddings
          </p>
        </div>
      </template>

      <template v-if="type === 'grist'">
        <div class="space-y-2">
          <Label for="cred-grist-server-url">Server URL</Label>
          <Input
            id="cred-grist-server-url"
            v-model="gristServerUrl"
            :placeholder="isEditing ? '(re-enter to update)' : 'https://docs.getgrist.com'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Grist server URL (e.g., https://docs.getgrist.com for hosted, or your self-hosted URL)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-grist-api-key">API Key</Label>
          <div class="relative">
            <Input
              id="cred-grist-api-key"
              v-model="gristApiKey"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'Enter API key'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            Grist API key from your profile settings
          </p>
        </div>
      </template>

      <template v-if="type === 'rabbitmq'">
        <div class="space-y-2">
          <Label for="cred-rabbitmq-host">Host</Label>
          <Input
            id="cred-rabbitmq-host"
            v-model="rabbitmqHost"
            :placeholder="isEditing ? '(re-enter to update)' : 'localhost'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            RabbitMQ server hostname (e.g., localhost, rabbitmq.example.com)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-rabbitmq-port">Port</Label>
          <Input
            id="cred-rabbitmq-port"
            v-model="rabbitmqPort"
            placeholder="5672"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            RabbitMQ port (default: 5672)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-rabbitmq-username">Username</Label>
          <Input
            id="cred-rabbitmq-username"
            v-model="rabbitmqUsername"
            :placeholder="isEditing ? '(re-enter to update)' : 'guest'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            RabbitMQ username for authentication
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-rabbitmq-password">Password</Label>
          <div class="relative">
            <Input
              id="cred-rabbitmq-password"
              v-model="rabbitmqPassword"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'Enter password'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            RabbitMQ password for authentication
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-rabbitmq-vhost">Virtual Host</Label>
          <Input
            id="cred-rabbitmq-vhost"
            v-model="rabbitmqVhost"
            placeholder="/"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            RabbitMQ virtual host (default: /)
          </p>
        </div>
      </template>

      <template v-if="type === 'cohere'">
        <div class="space-y-2">
          <Label for="cred-cohere-api-key">API Key</Label>
          <div class="relative">
            <Input
              id="cred-cohere-api-key"
              v-model="cohereApiKey"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'Enter Cohere API key'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            Cohere API key for reranking search results
          </p>
        </div>
      </template>

      <template v-if="type === 'flaresolverr'">
        <div class="space-y-2">
          <Label for="cred-flaresolverr-url">FlareSolverr URL</Label>
          <Input
            id="cred-flaresolverr-url"
            v-model="flaresolverrUrl"
            :placeholder="isEditing ? '(re-enter to update)' : 'http://localhost:8191/v1'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            FlareSolverr API endpoint (e.g., http://localhost:8191/v1)
          </p>
        </div>
      </template>

      <template v-if="type === 'google_sheets'">
        <div class="space-y-2">
          <Label for="cred-gs-client-id">Google Client ID</Label>
          <Input
            id="cred-gs-client-id"
            v-model="gsClientId"
            :placeholder="isEditing ? '(re-enter to update)' : '1234567890-abc.apps.googleusercontent.com'"
            :disabled="saving || gsOAuthConnecting"
          />
          <p class="text-xs text-muted-foreground">
            OAuth2 Client ID from your Google Cloud Console project.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-gs-client-secret">Google Client Secret</Label>
          <div class="relative">
            <Input
              id="cred-gs-client-secret"
              v-model="gsClientSecret"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'GOCSPX-...'"
              :disabled="saving || gsOAuthConnecting"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            OAuth2 Client Secret from your Google Cloud Console project.
          </p>
        </div>

        <div class="rounded-md border p-3 space-y-2">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium">
                Google Account
              </p>
              <p
                v-if="gsOAuthConnected"
                class="text-xs text-green-600 dark:text-green-400"
              >
                Connected
              </p>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Not connected — click to authorize
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              :loading="gsOAuthConnecting"
              :disabled="saving || gsOAuthConnecting || !gsClientId.trim() || !gsClientSecret.trim()"
              @click="startGoogleSheetsOAuth"
            >
              {{ gsOAuthConnected ? 'Reconnect' : 'Connect' }}
            </Button>
          </div>
        </div>
      </template>

      <template v-if="type === 'bigquery'">
        <div class="space-y-2">
          <Label for="cred-bq-client-id">Google Client ID</Label>
          <Input
            id="cred-bq-client-id"
            v-model="bqClientId"
            :placeholder="isEditing ? '(re-enter to update)' : '1234567890-abc.apps.googleusercontent.com'"
            :disabled="saving || bqOAuthConnecting"
          />
          <p class="text-xs text-muted-foreground">
            OAuth2 Client ID from your Google Cloud Console project (BigQuery scope).
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-bq-client-secret">Google Client Secret</Label>
          <div class="relative">
            <Input
              id="cred-bq-client-secret"
              v-model="bqClientSecret"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'GOCSPX-...'"
              :disabled="saving || bqOAuthConnecting"
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              @click="showApiKey = !showApiKey"
            >
              <EyeOff
                v-if="showApiKey"
                class="w-4 h-4"
              />
              <Eye
                v-else
                class="w-4 h-4"
              />
            </button>
          </div>
          <p class="text-xs text-muted-foreground">
            OAuth2 Client Secret from your Google Cloud Console project.
          </p>
        </div>

        <div class="rounded-md border p-3 space-y-2">
          <div class="flex items-center justify-between">
            <div>
              <p class="text-sm font-medium">
                Google Account
              </p>
              <p
                v-if="bqOAuthConnected"
                class="text-xs text-green-600 dark:text-green-400"
              >
                Connected
              </p>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Not connected — click to authorize
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              :loading="bqOAuthConnecting"
              :disabled="saving || bqOAuthConnecting || !bqClientId.trim() || !bqClientSecret.trim()"
              @click="startBigQueryOAuth"
            >
              {{ bqOAuthConnected ? 'Reconnect' : 'Connect' }}
            </Button>
          </div>
        </div>
      </template>

      <p
        v-if="error"
        class="text-sm text-destructive"
      >
        {{ error }}
      </p>

      <div class="flex justify-end gap-3 pt-4">
        <Button
          variant="outline"
          type="button"
          :disabled="saving"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          type="submit"
          :loading="saving"
          :disabled="!isValid"
        >
          {{ isEditing ? 'Save Changes' : ((type === 'google_sheets' && gsOAuthConnected) || (type === 'bigquery' && bqOAuthConnected) ? 'Done' : 'Create') }}
        </Button>
      </div>
    </form>
  </Dialog>
</template>
