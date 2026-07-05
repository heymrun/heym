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
import { AWS_REGION_OPTIONS } from "@/lib/awsRegions";
import {
  CREDENTIAL_TYPE_DESCRIPTIONS,
  CREDENTIAL_TYPE_LABELS,
} from "@/types/credential";

interface Props {
  open: boolean;
  credential?: Credential | null;
  presetType?: CredentialType;
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
const codexAccessToken = ref("");
const codexAuthMode = ref<"chatgpt" | "access_token">("chatgpt");
const codexOAuthConfig = ref<Record<string, unknown> | null>(null);
const codexOAuthState = ref("");
const codexRedirectUrl = ref("");
const codexSigningIn = ref(false);
const codexSignInError = ref("");
const codexSignedInAccount = ref("");
const baseUrl = ref("");
const bearerToken = ref("");
const headerKey = ref("");
const headerValue = ref("");
const telegramBotToken = ref("");
const telegramSecretToken = ref("");
const webhookUrl = ref("");
const signingSecret = ref("");
const discordPublicKey = ref("");
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
const clickhouseHost = ref("");
const clickhousePort = ref("8443");
const clickhouseUsername = ref("default");
const clickhousePassword = ref("");
const clickhouseDatabase = ref("default");
const clickhouseSecure = ref(true);
const qdrantHost = ref("");
const qdrantPort = ref("6333");
const qdrantApiKey = ref("");
const qdrantOpenaiApiKey = ref("");
const pgvectorOpenaiApiKey = ref("");
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
const supabaseUrl = ref("");
const supabaseKey = ref("");
const supabaseSchema = ref("public");
const supabaseTesting = ref(false);
const supabaseTestSuccess = ref<boolean | null>(null);
const supabaseTestMessage = ref("");
const linearTesting = ref(false);
const linearTestSuccess = ref<boolean | null>(null);
const linearTestMessage = ref("");
const linearAuthMode = ref<"api_key" | "oauth">("api_key");
const linearClientId = ref("");
const linearClientSecret = ref("");
const linearOAuthConnected = ref(false);
const linearOAuthConnecting = ref(false);
const linearConnectedCredential = ref<Credential | null>(null);
const notionToken = ref("");
const notionAuthMode = ref<"token" | "oauth">("token");
const notionClientId = ref("");
const notionClientSecret = ref("");
const notionOAuthConnected = ref(false);
const notionOAuthConnecting = ref(false);
const notionConnectedCredential = ref<Credential | null>(null);
const notionTesting = ref(false);
const notionTestSuccess = ref<boolean | null>(null);
const notionTestMessage = ref("");
const sentryTesting = ref(false);
const sentryTestSuccess = ref<boolean | null>(null);
const sentryTestMessage = ref("");
const s3AccessKeyId = ref("");
const s3SecretAccessKey = ref("");
const s3Region = ref("us-east-1");
const s3SessionToken = ref("");
const showApiKey = ref(false);
const saving = ref(false);
const error = ref("");

function parseS3RegionFromMaskedValue(maskedValue: string | null): string {
  if (!maskedValue) {
    return "";
  }
  const match = maskedValue.match(/\(([^)]+)\)$/);
  return match?.[1]?.trim() ?? "";
}

const storedS3Region = computed((): string => {
  if (!props.credential || props.credential.type !== "s3") {
    return "";
  }
  return parseS3RegionFromMaskedValue(props.credential.masked_value);
});

const hasS3CredentialConfigChange = computed((): boolean => {
  return (
    !!s3AccessKeyId.value.trim() ||
    !!s3SecretAccessKey.value.trim() ||
    !!s3SessionToken.value.trim() ||
    (!!s3Region.value.trim() && s3Region.value.trim() !== storedS3Region.value)
  );
});

const storedSupabaseUrl = computed((): string => {
  if (!props.credential || props.credential.type !== "supabase") {
    return "";
  }
  return props.credential.public_fields?.supabase_url ?? "";
});

const storedSupabaseSchema = computed((): string => {
  if (!props.credential || props.credential.type !== "supabase") {
    return "public";
  }
  return props.credential.public_fields?.supabase_schema ?? "public";
});

const hasSupabaseCredentialConfigChange = computed((): boolean => {
  return (
    supabaseUrl.value.trim() !== storedSupabaseUrl.value ||
    !!supabaseKey.value.trim() ||
    (supabaseSchema.value.trim() || "public") !== storedSupabaseSchema.value
  );
});

const typeOptions = [
  { value: "openai", label: CREDENTIAL_TYPE_LABELS.openai },
  { value: "codex", label: CREDENTIAL_TYPE_LABELS.codex },
  { value: "google", label: CREDENTIAL_TYPE_LABELS.google },
  { value: "github", label: CREDENTIAL_TYPE_LABELS.github },
  { value: "linear", label: CREDENTIAL_TYPE_LABELS.linear },
  { value: "elevenlabs", label: CREDENTIAL_TYPE_LABELS.elevenlabs },
  { value: "custom", label: CREDENTIAL_TYPE_LABELS.custom },
  { value: "bearer", label: CREDENTIAL_TYPE_LABELS.bearer },
  { value: "header", label: CREDENTIAL_TYPE_LABELS.header },
  { value: "telegram", label: CREDENTIAL_TYPE_LABELS.telegram },
  { value: "discord", label: CREDENTIAL_TYPE_LABELS.discord },
  { value: "discord_trigger", label: CREDENTIAL_TYPE_LABELS.discord_trigger },
  { value: "slack", label: CREDENTIAL_TYPE_LABELS.slack },
  { value: "slack_trigger", label: CREDENTIAL_TYPE_LABELS.slack_trigger },
  { value: "imap", label: CREDENTIAL_TYPE_LABELS.imap },
  { value: "smtp", label: CREDENTIAL_TYPE_LABELS.smtp },
  { value: "redis", label: CREDENTIAL_TYPE_LABELS.redis },
  { value: "qdrant", label: CREDENTIAL_TYPE_LABELS.qdrant },
  { value: "pgvector", label: CREDENTIAL_TYPE_LABELS.pgvector },
  { value: "grist", label: CREDENTIAL_TYPE_LABELS.grist },
  { value: "rabbitmq", label: CREDENTIAL_TYPE_LABELS.rabbitmq },
  { value: "cohere", label: CREDENTIAL_TYPE_LABELS.cohere },
  { value: "flaresolverr", label: CREDENTIAL_TYPE_LABELS.flaresolverr },
  { value: "google_sheets", label: CREDENTIAL_TYPE_LABELS.google_sheets },
  { value: "bigquery", label: CREDENTIAL_TYPE_LABELS.bigquery },
  { value: "supabase", label: CREDENTIAL_TYPE_LABELS.supabase },
  { value: "clickhouse", label: CREDENTIAL_TYPE_LABELS.clickhouse },
  { value: "notion", label: CREDENTIAL_TYPE_LABELS.notion },
  { value: "sentry", label: CREDENTIAL_TYPE_LABELS.sentry },
  { value: "s3", label: CREDENTIAL_TYPE_LABELS.s3 },
];

function isTrustedOAuthMessage(evt: MessageEvent, popup: Window | null): boolean {
  return evt.origin === window.location.origin && evt.source === popup;
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      if (props.credential) {
        name.value = props.credential.name;
        type.value = props.credential.type;
        apiKey.value = "";
        codexAccessToken.value = "";
        resetCodexOAuthState();
        codexAuthMode.value =
          props.credential.public_fields?.auth_mode === "access_token"
            ? "access_token"
            : "chatgpt";
        codexSignedInAccount.value =
          props.credential.public_fields?.account_id || "";
        baseUrl.value = "";
        bearerToken.value = "";
        headerKey.value = props.credential.header_key || "";
        headerValue.value = "";
        telegramBotToken.value = "";
        telegramSecretToken.value = "";
        webhookUrl.value = "";
        signingSecret.value = "";
        discordPublicKey.value = "";
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
        clickhouseHost.value = "";
        clickhousePort.value = "8443";
        clickhouseUsername.value = "default";
        clickhousePassword.value = "";
        clickhouseDatabase.value = "default";
        clickhouseSecure.value = true;
        qdrantHost.value = "";
        qdrantPort.value = "6333";
        qdrantApiKey.value = "";
        qdrantOpenaiApiKey.value = "";
        pgvectorOpenaiApiKey.value = "";
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
        supabaseUrl.value =
          props.credential.type === "supabase"
            ? props.credential.public_fields?.supabase_url ?? ""
            : "";
        supabaseKey.value = "";
        supabaseSchema.value =
          props.credential.type === "supabase"
            ? props.credential.public_fields?.supabase_schema ?? "public"
            : "public";
        linearAuthMode.value =
          props.credential.type === "linear" &&
          (props.credential.masked_value === "connected" ||
            props.credential.public_fields?.auth_mode === "oauth")
            ? "oauth"
            : "api_key";
        linearClientId.value = "";
        linearClientSecret.value = "";
        linearOAuthConnected.value =
          props.credential.type === "linear" && props.credential.masked_value === "connected";
        linearOAuthConnecting.value = false;
        linearConnectedCredential.value = null;
        notionToken.value = "";
        notionAuthMode.value =
          props.credential.type === "notion" &&
          (props.credential.masked_value === "connected" ||
            props.credential.masked_value?.startsWith("connected (") ||
            props.credential.public_fields?.auth_mode === "oauth")
            ? "oauth"
            : "token";
        notionClientId.value = "";
        notionClientSecret.value = "";
        notionOAuthConnected.value =
          props.credential.type === "notion" &&
          (props.credential.masked_value === "connected" ||
            props.credential.masked_value?.startsWith("connected (") ||
            false);
        notionOAuthConnecting.value = false;
        notionConnectedCredential.value = null;
        sentryTestSuccess.value = null;
        sentryTestMessage.value = "";
        s3AccessKeyId.value = "";
        s3SecretAccessKey.value = "";
        s3Region.value =
          props.credential.type === "s3"
            ? parseS3RegionFromMaskedValue(props.credential.masked_value)
            : "";
        s3SessionToken.value = "";
      } else {
        name.value = "";
        type.value = props.presetType ?? "openai";
        apiKey.value = "";
        codexAccessToken.value = "";
        codexAuthMode.value = "chatgpt";
        resetCodexOAuthState();
        codexSignedInAccount.value = "";
        baseUrl.value = "";
        bearerToken.value = "";
        headerKey.value = "";
        headerValue.value = "";
        telegramBotToken.value = "";
        telegramSecretToken.value = "";
        webhookUrl.value = "";
        signingSecret.value = "";
        discordPublicKey.value = "";
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
        clickhouseHost.value = "";
        clickhousePort.value = "8443";
        clickhouseUsername.value = "default";
        clickhousePassword.value = "";
        clickhouseDatabase.value = "default";
        clickhouseSecure.value = true;
        qdrantHost.value = "";
        qdrantPort.value = "6333";
        qdrantApiKey.value = "";
        qdrantOpenaiApiKey.value = "";
        pgvectorOpenaiApiKey.value = "";
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
        supabaseUrl.value = "";
        supabaseKey.value = "";
        supabaseSchema.value = "public";
        linearAuthMode.value = "api_key";
        linearClientId.value = "";
        linearClientSecret.value = "";
        linearOAuthConnected.value = false;
        linearOAuthConnecting.value = false;
        linearConnectedCredential.value = null;
        notionToken.value = "";
        notionAuthMode.value = "token";
        notionClientId.value = "";
        notionClientSecret.value = "";
        notionOAuthConnected.value = false;
        notionOAuthConnecting.value = false;
        notionConnectedCredential.value = null;
        sentryTestSuccess.value = null;
        sentryTestMessage.value = "";
        s3AccessKeyId.value = "";
        s3SecretAccessKey.value = "";
        s3Region.value = "us-east-1";
        s3SessionToken.value = "";
      }
      showApiKey.value = false;
      error.value = "";
      supabaseTesting.value = false;
      supabaseTestSuccess.value = null;
      supabaseTestMessage.value = "";
      linearTesting.value = false;
      linearTestSuccess.value = null;
      linearTestMessage.value = "";
      notionTesting.value = false;
      notionTestSuccess.value = null;
      notionTestMessage.value = "";
      sentryTesting.value = false;
      sentryTestSuccess.value = null;
      sentryTestMessage.value = "";
    }
  }
);

const isValid = computed(() => {
  if (!name.value.trim()) return false;

  if (type.value === "linear") {
    if (linearAuthMode.value === "oauth") {
      if (!isEditing.value) {
        return linearOAuthConnected.value;
      }
      return (
        linearOAuthConnected.value ||
        props.credential?.masked_value === "connected" ||
        props.credential?.masked_value === "Not connected"
      );
    }
    return !!apiKey.value.trim() || isEditing.value;
  }

  if (
    type.value === "openai" ||
    type.value === "google" ||
    type.value === "github" ||
    type.value === "sentry" ||
    type.value === "elevenlabs"
  ) {
    return !!apiKey.value.trim() || isEditing.value;
  } else if (type.value === "codex") {
    if (codexAuthMode.value === "chatgpt") {
      return !!codexOAuthConfig.value || isEditing.value;
    }
    return !!codexAccessToken.value.trim() || isEditing.value;
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
  } else if (type.value === "discord") {
    return !!webhookUrl.value.trim() || isEditing.value;
  } else if (type.value === "slack_trigger") {
    return !!signingSecret.value.trim() || isEditing.value;
  } else if (type.value === "discord_trigger") {
    return !!discordPublicKey.value.trim() || isEditing.value;
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
  } else if (type.value === "clickhouse") {
    return !!clickhouseHost.value.trim() || isEditing.value;
  } else if (type.value === "qdrant") {
    return (
      !!qdrantHost.value.trim() &&
      !!qdrantPort.value.trim() &&
      !!qdrantOpenaiApiKey.value.trim()
    ) || isEditing.value;
  } else if (type.value === "pgvector") {
    return !!pgvectorOpenaiApiKey.value.trim() || isEditing.value;
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
  } else if (type.value === "supabase") {
    if (isEditing.value) {
      return !!supabaseUrl.value.trim();
    }
    return !!supabaseUrl.value.trim() && !!supabaseKey.value.trim();
  } else if (type.value === "notion") {
    if (notionAuthMode.value === "oauth") {
      if (!isEditing.value) {
        return notionOAuthConnected.value;
      }
      return (
        notionOAuthConnected.value ||
        props.credential?.masked_value === "connected" ||
        (props.credential?.masked_value?.startsWith("connected (") ?? false) ||
        props.credential?.masked_value === "Not connected"
      );
    }
    return !!notionToken.value.trim() || isEditing.value;
  } else if (type.value === "s3") {
    if (isEditing.value) {
      return !hasS3CredentialConfigChange.value || (
        !!s3AccessKeyId.value.trim() &&
        !!s3SecretAccessKey.value.trim() &&
        !!s3Region.value.trim()
      );
    }
    return (
      !!s3AccessKeyId.value.trim() &&
      !!s3SecretAccessKey.value.trim() &&
      !!s3Region.value.trim()
    );
  }
  return false;
});

const canTestSupabaseConnection = computed((): boolean => {
  if (type.value !== "supabase") {
    return false;
  }
  if (!!supabaseUrl.value.trim() && !!supabaseKey.value.trim()) {
    return true;
  }
  return isEditing.value && !!props.credential?.id;
});

const canTestLinearConnection = computed((): boolean => {
  if (type.value !== "linear") {
    return false;
  }
  if (linearAuthMode.value === "oauth") {
    return (
      linearOAuthConnected.value ||
      props.credential?.masked_value === "connected" ||
      !!linearConnectedCredential.value
    );
  }
  if (apiKey.value.trim()) {
    return true;
  }
  return isEditing.value && !!props.credential?.id;
});

function resetCodexOAuthState(): void {
  codexOAuthConfig.value = null;
  codexOAuthState.value = "";
  codexRedirectUrl.value = "";
  codexSignInError.value = "";
  codexSigningIn.value = false;
}

async function startCodexSignIn(): Promise<void> {
  codexSignInError.value = "";
  codexOAuthConfig.value = null;
  try {
    const { authorize_url, state } = await credentialsApi.codexOAuthStart();
    codexOAuthState.value = state;
    window.open(authorize_url, "_blank", "noopener,noreferrer");
  } catch {
    codexSignInError.value = "Could not start ChatGPT sign-in. Try again.";
  }
}

async function completeCodexSignIn(): Promise<void> {
  if (!codexOAuthState.value) {
    codexSignInError.value = "Start the sign-in first.";
    return;
  }
  if (!codexRedirectUrl.value.trim()) {
    codexSignInError.value = "Paste the redirect URL from your browser.";
    return;
  }
  codexSigningIn.value = true;
  codexSignInError.value = "";
  try {
    const { config, account_id } = await credentialsApi.codexOAuthComplete(
      codexOAuthState.value,
      codexRedirectUrl.value.trim(),
    );
    codexOAuthConfig.value = config;
    codexSignedInAccount.value = account_id || "ChatGPT account";
    codexRedirectUrl.value = "";
  } catch (error) {
    codexSignInError.value =
      (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
      "ChatGPT sign-in failed. Restart and try again.";
  } finally {
    codexSigningIn.value = false;
  }
}

function buildConfig(): CredentialConfig {
  if (type.value === "openai") {
    return { api_key: apiKey.value };
  } else if (type.value === "codex") {
    if (codexAuthMode.value === "chatgpt" && codexOAuthConfig.value) {
      return codexOAuthConfig.value as unknown as CredentialConfig;
    }
    return { access_token: codexAccessToken.value.trim(), auth_mode: "access_token" };
  } else if (type.value === "google") {
    return { api_key: apiKey.value };
  } else if (type.value === "github") {
    const trimmedBaseUrl = baseUrl.value.trim();
    return {
      api_key: apiKey.value,
      ...(trimmedBaseUrl ? { base_url: trimmedBaseUrl } : {}),
    };
  } else if (type.value === "sentry") {
    const trimmedBaseUrl = baseUrl.value.trim();
    return {
      api_token: apiKey.value.trim(),
      ...(trimmedBaseUrl ? { base_url: trimmedBaseUrl } : {}),
    };
  } else if (type.value === "linear") {
    return linearAuthMode.value === "oauth"
      ? {
          auth_mode: "oauth",
          client_id: linearClientId.value.trim(),
          client_secret: linearClientSecret.value.trim(),
        }
      : { api_key: apiKey.value.trim(), auth_mode: "api_key" };
  } else if (type.value === "elevenlabs") {
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
  } else if (type.value === "clickhouse") {
    return {
      host: clickhouseHost.value,
      port: Number(clickhousePort.value) || (clickhouseSecure.value ? 8443 : 8123),
      username: clickhouseUsername.value,
      password: clickhousePassword.value,
      database: clickhouseDatabase.value,
      secure: clickhouseSecure.value,
    };
  } else if (type.value === "qdrant") {
    return {
      qdrant_host: qdrantHost.value,
      qdrant_port: qdrantPort.value,
      qdrant_api_key: qdrantApiKey.value,
      openai_api_key: qdrantOpenaiApiKey.value,
    };
  } else if (type.value === "pgvector") {
    return {
      openai_api_key: pgvectorOpenaiApiKey.value,
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
  } else if (type.value === "discord_trigger") {
    return { public_key: discordPublicKey.value.trim() };
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
  } else if (type.value === "supabase") {
    return {
      supabase_url: supabaseUrl.value.trim(),
      supabase_key: supabaseKey.value.trim(),
      supabase_schema: supabaseSchema.value.trim() || "public",
    };
  } else if (type.value === "notion") {
    return notionAuthMode.value === "oauth"
      ? {
          auth_mode: "oauth",
          client_id: notionClientId.value.trim(),
          client_secret: notionClientSecret.value.trim(),
        }
      : { api_token: notionToken.value.trim() };
  } else if (type.value === "s3") {
    return {
      aws_access_key_id: s3AccessKeyId.value.trim(),
      aws_secret_access_key: s3SecretAccessKey.value.trim(),
      aws_region: s3Region.value.trim(),
      aws_session_token: s3SessionToken.value.trim(),
    };
  } else if (type.value === "slack") {
    return { webhook_url: webhookUrl.value.trim() };
  } else if (type.value === "discord") {
    return { webhook_url: webhookUrl.value.trim() };
  } else {
    return { webhook_url: webhookUrl.value.trim() };
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
    if (!popup) {
      throw new Error("OAuth popup was blocked. Allow popups for Heym and try again.");
    }

    const onMessage = (evt: MessageEvent): void => {
      if (!isTrustedOAuthMessage(evt, popup)) {
        return;
      }
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

    const pollClosed = setInterval(() => {
      if (popup?.closed) {
        clearInterval(pollClosed);
        window.removeEventListener("message", onMessage);
        gsOAuthConnecting.value = false;
      }
    }, 500);

    window.addEventListener("message", onMessage);
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
    if (!popup) {
      throw new Error("OAuth popup was blocked. Allow popups for Heym and try again.");
    }

    const onMessage = (evt: MessageEvent): void => {
      if (!isTrustedOAuthMessage(evt, popup)) {
        return;
      }
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

    const pollClosed = setInterval(() => {
      if (popup?.closed) {
        clearInterval(pollClosed);
        window.removeEventListener("message", onMessage);
        bqOAuthConnecting.value = false;
      }
    }, 500);

    window.addEventListener("message", onMessage);
  } catch (err) {
    bqOAuthConnecting.value = false;
    error.value = err instanceof Error ? err.message : "OAuth authorization failed";
  }
}

async function testSupabaseConnection(): Promise<void> {
  if (!canTestSupabaseConnection.value) {
    error.value = "Enter Project URL and API Key to test the connection.";
    return;
  }

  supabaseTesting.value = true;
  supabaseTestSuccess.value = null;
  supabaseTestMessage.value = "";
  error.value = "";

  try {
    const result = await credentialsApi.testConnection({
      type: "supabase",
      config: {
        supabase_url: supabaseUrl.value.trim(),
        supabase_key: supabaseKey.value.trim(),
        supabase_schema: supabaseSchema.value.trim() || "public",
      },
      credential_id: isEditing.value ? props.credential?.id : undefined,
    });
    supabaseTestSuccess.value = result.success;
    supabaseTestMessage.value = result.message;
    if (!result.success) {
      error.value = result.message;
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Connection test failed";
    supabaseTestSuccess.value = false;
    supabaseTestMessage.value = message;
    error.value = message;
  } finally {
    supabaseTesting.value = false;
  }
}

async function testLinearConnection(): Promise<void> {
  const connectedCredentialId =
    props.credential?.id || linearConnectedCredential.value?.id;
  if (!canTestLinearConnection.value) {
    error.value =
      linearAuthMode.value === "oauth"
        ? "Connect Linear OAuth before testing the connection."
        : "Enter an API key to test the connection.";
    return;
  }

  linearTesting.value = true;
  linearTestSuccess.value = null;
  linearTestMessage.value = "";
  error.value = "";

  try {
    const result = await credentialsApi.testConnection({
      type: "linear",
      config:
        linearAuthMode.value === "oauth"
          ? { auth_mode: "oauth" }
          : { api_key: apiKey.value.trim(), auth_mode: "api_key" },
      credential_id:
        linearAuthMode.value === "oauth"
          ? connectedCredentialId
          : isEditing.value
            ? props.credential?.id
            : undefined,
    });
    linearTestSuccess.value = result.success;
    linearTestMessage.value = result.message;
    if (!result.success) {
      error.value = result.message;
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Connection test failed";
    linearTestSuccess.value = false;
    linearTestMessage.value = message;
    error.value = message;
  } finally {
    linearTesting.value = false;
  }
}

async function testNotionConnection(): Promise<void> {
  const connectedCredentialId =
    props.credential?.id || notionConnectedCredential.value?.id;
  if (
    notionAuthMode.value === "token" &&
    !notionToken.value.trim() &&
    !connectedCredentialId
  ) {
    error.value = "Enter an integration token to test the connection.";
    return;
  }
  notionTesting.value = true;
  notionTestSuccess.value = null;
  notionTestMessage.value = "";
  error.value = "";
  try {
    const result = await credentialsApi.testConnection({
      type: "notion",
      config:
        notionAuthMode.value === "oauth"
          ? { auth_mode: "oauth" }
          : { api_token: notionToken.value.trim() },
      credential_id: connectedCredentialId,
    });
    notionTestSuccess.value = result.success;
    notionTestMessage.value = result.message;
    if (!result.success) {
      error.value = result.message;
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Connection test failed";
    notionTestSuccess.value = false;
    notionTestMessage.value = message;
    error.value = message;
  } finally {
    notionTesting.value = false;
  }
}

async function testSentryConnection(): Promise<void> {
  if (!apiKey.value.trim() && !isEditing.value) {
    error.value = "Enter a Sentry auth token to test the connection.";
    return;
  }
  sentryTesting.value = true;
  sentryTestSuccess.value = null;
  sentryTestMessage.value = "";
  error.value = "";
  try {
    const trimmedBaseUrl = baseUrl.value.trim();
    const result = await credentialsApi.testConnection({
      type: "sentry",
      config: {
        api_token: apiKey.value.trim(),
        ...(trimmedBaseUrl ? { base_url: trimmedBaseUrl } : {}),
      },
      credential_id: isEditing.value ? props.credential?.id : undefined,
    });
    sentryTestSuccess.value = result.success;
    sentryTestMessage.value = result.message;
    if (!result.success) {
      error.value = result.message;
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Connection test failed";
    sentryTestSuccess.value = false;
    sentryTestMessage.value = message;
    error.value = message;
  } finally {
    sentryTesting.value = false;
  }
}

const notionWorkspaceName = computed((): string => {
  const fromCredential =
    props.credential?.public_fields?.workspace_name ||
    notionConnectedCredential.value?.public_fields?.workspace_name;
  if (fromCredential) {
    return fromCredential;
  }
  const masked = props.credential?.masked_value || "";
  const match = masked.match(/^connected \((.+)\)$/);
  return match?.[1]?.trim() ?? "";
});

const notionOAuthStatusLabel = computed((): string => {
  if (notionOAuthConnected.value) {
    return notionWorkspaceName.value
      ? `Connected to ${notionWorkspaceName.value}`
      : "Connected";
  }
  if (isEditing.value && props.credential?.masked_value === "Not connected") {
    return "Not connected";
  }
  return "";
});

const linearOAuthStatusLabel = computed((): string => {
  if (linearOAuthConnected.value) {
    return "Connected";
  }
  if (isEditing.value && props.credential?.masked_value === "Not connected") {
    return "Not connected";
  }
  return "";
});

async function startLinearOAuth(): Promise<void> {
  if (!linearClientId.value.trim() || !linearClientSecret.value.trim()) {
    error.value = "Enter Client ID and Client Secret before connecting.";
    return;
  }
  if (!name.value.trim()) {
    error.value = "Enter a name for this credential before connecting.";
    return;
  }
  linearOAuthConnecting.value = true;
  error.value = "";
  try {
    let credentialId: string;
    if (isEditing.value && props.credential) {
      await credentialsApi.update(props.credential.id, {
        name: name.value,
        config: buildConfig(),
      });
      credentialId = props.credential.id;
    } else {
      const saved = await credentialsApi.create({
        name: name.value,
        type: "linear",
        config: buildConfig(),
      });
      credentialId = saved.id;
    }
    const { auth_url } = await credentialsApi.linearOAuthAuthorize(credentialId);
    const popup = window.open(auth_url, "linear-oauth", "width=520,height=680");
    if (!popup) {
      throw new Error("OAuth popup was blocked. Allow popups for Heym and try again.");
    }
    const onMessage = (event: MessageEvent): void => {
      if (!isTrustedOAuthMessage(event, popup)) {
        return;
      }
      if (
        event.data?.type === "linear-oauth-success" &&
        event.data.credentialId === credentialId
      ) {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
        popup.close();
        credentialsApi.get(credentialId).then((credential) => {
          linearConnectedCredential.value = credential;
          linearOAuthConnected.value = true;
          linearOAuthConnecting.value = false;
        }).catch(() => {
          linearOAuthConnected.value = true;
          linearOAuthConnecting.value = false;
        });
      } else if (event.data?.type === "linear-oauth-error") {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
        linearOAuthConnecting.value = false;
        error.value = event.data.message || "Linear OAuth authorization failed";
      }
    };
    const pollClosed = setInterval(() => {
      if (popup.closed) {
        clearInterval(pollClosed);
        window.removeEventListener("message", onMessage);
        linearOAuthConnecting.value = false;
      }
    }, 500);
    window.addEventListener("message", onMessage);
  } catch (err) {
    linearOAuthConnecting.value = false;
    error.value = err instanceof Error ? err.message : "Linear OAuth authorization failed";
  }
}

async function startNotionOAuth(): Promise<void> {
  if (!notionClientId.value.trim() || !notionClientSecret.value.trim()) {
    error.value = "Enter Client ID and Client Secret before connecting.";
    return;
  }
  if (!name.value.trim()) {
    error.value = "Enter a name for this credential before connecting.";
    return;
  }
  notionOAuthConnecting.value = true;
  error.value = "";
  try {
    let credentialId: string;
    if (isEditing.value && props.credential) {
      await credentialsApi.update(props.credential.id, {
        name: name.value,
        config: buildConfig(),
      });
      credentialId = props.credential.id;
    } else {
      const saved = await credentialsApi.create({
        name: name.value,
        type: "notion",
        config: buildConfig(),
      });
      credentialId = saved.id;
    }
    const { auth_url } = await credentialsApi.notionOAuthAuthorize(credentialId);
    const popup = window.open(auth_url, "notion-oauth", "width=520,height=680");
    if (!popup) {
      throw new Error("OAuth popup was blocked. Allow popups for Heym and try again.");
    }
    const onMessage = (event: MessageEvent): void => {
      if (!isTrustedOAuthMessage(event, popup)) {
        return;
      }
      if (
        event.data?.type === "notion-oauth-success" &&
        event.data.credentialId === credentialId
      ) {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
        popup.close();
        credentialsApi.get(credentialId).then((credential) => {
          notionConnectedCredential.value = credential;
          notionOAuthConnected.value = true;
          notionOAuthConnecting.value = false;
        }).catch(() => {
          notionOAuthConnected.value = true;
          notionOAuthConnecting.value = false;
        });
      } else if (event.data?.type === "notion-oauth-error") {
        window.removeEventListener("message", onMessage);
        clearInterval(pollClosed);
        notionOAuthConnecting.value = false;
        error.value = event.data.message || "Notion OAuth authorization failed";
      }
    };
    const pollClosed = setInterval(() => {
      if (popup.closed) {
        clearInterval(pollClosed);
        window.removeEventListener("message", onMessage);
        notionOAuthConnecting.value = false;
      }
    }, 500);
    window.addEventListener("message", onMessage);
  } catch (err) {
    notionOAuthConnecting.value = false;
    error.value = err instanceof Error ? err.message : "Notion OAuth authorization failed";
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
      // OAuth configs are managed by their callbacks after connection.
      const hasConfigChange =
        type.value !== "google_sheets" &&
        type.value !== "bigquery" &&
        !(type.value === "linear" && linearAuthMode.value === "oauth") &&
        !(type.value === "notion" && notionAuthMode.value === "oauth") &&
        (apiKey.value.trim() ||
          codexAccessToken.value.trim() ||
          !!codexOAuthConfig.value ||
          baseUrl.value.trim() ||
          bearerToken.value.trim() ||
          headerKeyChanged ||
          headerValue.value.trim() ||
          telegramBotToken.value.trim() ||
          telegramSecretToken.value.trim() ||
          webhookUrl.value.trim() ||
          signingSecret.value.trim() ||
          discordPublicKey.value.trim() ||
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
          pgvectorOpenaiApiKey.value.trim() ||
          gristApiKey.value.trim() ||
          gristServerUrl.value.trim() ||
          rabbitmqHost.value.trim() ||
          rabbitmqPort.value.trim() ||
          rabbitmqUsername.value.trim() ||
          rabbitmqPassword.value.trim() ||
          rabbitmqVhost.value.trim() ||
          (type.value === "s3" && hasS3CredentialConfigChange.value) ||
          (type.value === "supabase" && hasSupabaseCredentialConfigChange.value) ||
          notionToken.value.trim() ||
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
    } else if (type.value === "notion" && notionConnectedCredential.value) {
      saved = notionConnectedCredential.value;
    } else if (
      type.value === "linear" &&
      linearAuthMode.value === "oauth" &&
      linearConnectedCredential.value
    ) {
      saved = linearConnectedCredential.value;
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
        <p
          v-if="type !== 'codex'"
          class="text-xs text-muted-foreground"
        >
          Access via: <code class="bg-muted px-1 rounded">${{ `credentials.${name || 'name'}` }}</code>
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Codex tokens are only exposed to the isolated Codex runner.
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
        v-if="type === 'openai' || type === 'google' || type === 'github' || type === 'sentry' || type === 'elevenlabs'"
        class="space-y-2"
      >
        <Label for="cred-api-key">API Key</Label>
        <div class="relative">
          <Input
            id="cred-api-key"
            v-model="apiKey"
            :type="showApiKey ? 'text' : 'password'"
            :placeholder="isEditing ? '••••••• (re-enter to update)' : (type === 'github' ? 'github_pat_... or ghp_...' : type === 'sentry' ? 'sntrys_... or sentry auth token' : 'sk-...')"
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
        <p
          v-if="type === 'elevenlabs'"
          class="text-xs text-muted-foreground"
        >
          Grant this API key the <strong>Text to Speech</strong>,
          <strong>Speech to Text</strong>, and <strong>Voices</strong> permissions in your
          ElevenLabs account.
        </p>
        <p
          v-else-if="type === 'github'"
          class="text-xs text-muted-foreground"
        >
          Use a GitHub personal access token. Fine-grained PATs are recommended. This credential currently targets PAT-based auth, not GitHub App installation flows.
        </p>
        <p
          v-else-if="type === 'sentry'"
          class="text-xs text-muted-foreground"
        >
          Use a Sentry auth token with access to the organizations and projects you want to automate.
        </p>
      </div>

      <template v-if="type === 'codex'">
        <div class="space-y-2">
          <Label>Authentication</Label>
          <Select
            :model-value="codexAuthMode"
            :options="[
              { value: 'chatgpt', label: 'Sign in with ChatGPT (subscription, no API cost)' },
              { value: 'access_token', label: 'Access token' },
            ]"
            :disabled="saving"
            @update:model-value="codexAuthMode = $event as 'chatgpt' | 'access_token'"
          />
        </div>

        <div
          v-if="codexAuthMode === 'chatgpt'"
          class="space-y-2"
        >
          <div
            v-if="codexOAuthConfig || (isEditing && codexSignedInAccount)"
            class="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-600 dark:text-emerald-400"
          >
            Connected to ChatGPT{{ codexSignedInAccount ? ` (${codexSignedInAccount})` : "" }}.
            <template v-if="isEditing && !codexOAuthConfig">
              Sign in again only if you need to reconnect.
            </template>
          </div>

          <div class="space-y-2">
            <Button
              type="button"
              variant="outline"
              :disabled="saving || codexSigningIn"
              class="w-full"
              @click="startCodexSignIn"
            >
              {{ codexOAuthConfig || codexSignedInAccount ? "Re-sign in with ChatGPT" : "Sign in with ChatGPT" }}
            </Button>
            <p class="text-xs text-muted-foreground">
              A new tab opens the OpenAI sign-in. After you authorize, your browser lands on a
              <code class="bg-muted px-1 rounded">localhost:1455</code> page (it may fail to load —
              that is expected). Copy that full URL from the address bar and paste it below.
            </p>
            <Input
              v-model="codexRedirectUrl"
              placeholder="http://localhost:1455/auth/callback?code=..."
              :disabled="saving || codexSigningIn || !codexOAuthState"
            />
            <Button
              type="button"
              :disabled="saving || codexSigningIn || !codexOAuthState || !codexRedirectUrl.trim()"
              class="w-full"
              @click="completeCodexSignIn"
            >
              {{ codexSigningIn ? "Finishing sign-in..." : "Finish sign-in" }}
            </Button>
            <p
              v-if="codexSignInError"
              class="text-xs text-destructive"
            >
              {{ codexSignInError }}
            </p>
          </div>
        </div>

        <div
          v-else
          class="space-y-2"
        >
          <Label for="cred-codex-access-token">Access Token</Label>
          <div class="relative">
            <Input
              id="cred-codex-access-token"
              v-model="codexAccessToken"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'Codex access token'"
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
            Paste a ChatGPT/Codex access token. API keys are intentionally not accepted for this
            credential type.
          </p>
        </div>
      </template>

      <template v-if="type === 'linear'">
        <div class="space-y-2">
          <Label>Authentication</Label>
          <Select
            v-model="linearAuthMode"
            :options="[
              { value: 'api_key', label: 'Personal API Key' },
              { value: 'oauth', label: 'OAuth2' },
            ]"
            :disabled="saving || linearOAuthConnecting"
          />
        </div>

        <div
          v-if="linearAuthMode === 'api_key'"
          class="space-y-2"
        >
          <Label for="cred-linear-api-key">API Key</Label>
          <div class="relative">
            <Input
              id="cred-linear-api-key"
              v-model="apiKey"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'lin_api_...'"
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
            Create a personal API key in Linear under Settings → Security & Access → Personal API keys.
          </p>
        </div>

        <template v-if="linearAuthMode === 'oauth'">
          <div class="space-y-2">
            <Label for="cred-linear-client-id">OAuth Client ID</Label>
            <Input
              id="cred-linear-client-id"
              v-model="linearClientId"
              placeholder="Linear OAuth client ID"
              :disabled="saving || linearOAuthConnecting"
            />
          </div>
          <div class="space-y-2">
            <Label for="cred-linear-client-secret">OAuth Client Secret</Label>
            <Input
              id="cred-linear-client-secret"
              v-model="linearClientSecret"
              type="password"
              placeholder="Linear OAuth client secret"
              :disabled="saving || linearOAuthConnecting"
            />
          </div>
          <div class="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              :loading="linearOAuthConnecting"
              :disabled="saving || linearOAuthConnecting || !linearClientId.trim() || !linearClientSecret.trim()"
              @click="startLinearOAuth"
            >
              {{ linearOAuthConnected ? "Reconnect" : "Connect" }}
            </Button>
            <span
              v-if="linearOAuthStatusLabel"
              class="text-xs"
              :class="linearOAuthConnected ? 'text-emerald-600' : 'text-muted-foreground'"
            >
              {{ linearOAuthStatusLabel }}
            </span>
          </div>
          <p class="text-xs text-muted-foreground">
            Register
            <code>/api/credentials/linear/oauth/callback</code>
            in your Linear OAuth application.
          </p>
        </template>

        <div
          v-if="linearAuthMode === 'api_key' || linearOAuthConnected"
          class="flex items-center gap-3"
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="linear-test-connection-button"
            :loading="linearTesting"
            :disabled="saving || linearTesting || !canTestLinearConnection"
            @click="testLinearConnection"
          >
            Test Connection
          </Button>
          <p
            v-if="linearTestMessage"
            class="text-xs"
            :class="linearTestSuccess ? 'text-emerald-600' : 'text-destructive'"
          >
            {{ linearTestMessage }}
          </p>
        </div>
      </template>

      <div
        v-if="type === 'github'"
        class="space-y-2"
      >
        <Label for="cred-github-base-url">GitHub API Base URL (Optional)</Label>
        <Input
          id="cred-github-base-url"
          v-model="baseUrl"
          placeholder="https://github.example.com/api/v3"
          :disabled="saving"
        />
        <p class="text-xs text-muted-foreground">
          Leave empty for GitHub.com. For GitHub Enterprise Server, enter the full REST API
          endpoint, including <code>/api/v3</code> (for example,
          <code>https://github.example.com/api/v3</code>), not the web UI URL.
        </p>
      </div>

      <template v-if="type === 'sentry'">
        <div class="space-y-2">
          <Label for="cred-sentry-base-url">Sentry Base URL (Optional)</Label>
          <Input
            id="cred-sentry-base-url"
            v-model="baseUrl"
            placeholder="https://sentry.io"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Leave empty for Sentry SaaS. For self-hosted Sentry, enter the root URL, not
            the <code>/api/0</code> path.
          </p>
        </div>

        <div class="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="sentry-test-connection-button"
            :loading="sentryTesting"
            :disabled="saving || sentryTesting || (!apiKey.trim() && !isEditing)"
            @click="testSentryConnection"
          >
            Test Connection
          </Button>
          <p
            v-if="sentryTestMessage"
            class="text-xs"
            :class="sentryTestSuccess ? 'text-emerald-600' : 'text-destructive'"
          >
            {{ sentryTestMessage }}
          </p>
        </div>
      </template>

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

      <template v-if="type === 'discord'">
        <div class="space-y-2">
          <Label for="cred-discord-webhook">Webhook URL</Label>
          <Input
            id="cred-discord-webhook"
            v-model="webhookUrl"
            placeholder="https://discord.com/api/webhooks/..."
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Discord incoming webhook URL from channel Integrations → Webhooks.
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

      <template v-if="type === 'discord_trigger'">
        <div class="space-y-2">
          <Label for="cred-discord-public-key">Application Public Key</Label>
          <Input
            id="cred-discord-public-key"
            v-model="discordPublicKey"
            :placeholder="isEditing ? '(re-enter to update)' : 'Paste your Discord Application Public Key'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Found in the Discord Developer Portal → your application → General Information → Public Key.
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

      <template v-if="type === 'clickhouse'">
        <div class="space-y-2">
          <Label for="cred-clickhouse-host">Host</Label>
          <Input
            id="cred-clickhouse-host"
            v-model="clickhouseHost"
            :placeholder="isEditing ? '(re-enter to update)' : 'your-instance.clickhouse.cloud'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            ClickHouse HTTP host (without scheme), e.g. your-instance.clickhouse.cloud
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-clickhouse-port">Port</Label>
          <Input
            id="cred-clickhouse-port"
            v-model="clickhousePort"
            placeholder="8443"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            HTTP interface port (8443 for HTTPS, 8123 for HTTP)
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-clickhouse-username">Username</Label>
          <Input
            id="cred-clickhouse-username"
            v-model="clickhouseUsername"
            placeholder="default"
            :disabled="saving"
          />
        </div>

        <div class="space-y-2">
          <Label for="cred-clickhouse-password">Password</Label>
          <div class="relative">
            <Input
              id="cred-clickhouse-password"
              v-model="clickhousePassword"
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
        </div>

        <div class="space-y-2">
          <Label for="cred-clickhouse-database">Database</Label>
          <Input
            id="cred-clickhouse-database"
            v-model="clickhouseDatabase"
            placeholder="default"
            :disabled="saving"
          />
        </div>

        <div class="space-y-2">
          <label class="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              class="rounded border-input"
              :checked="clickhouseSecure"
              :disabled="saving"
              @change="clickhouseSecure = ($event.target as HTMLInputElement).checked"
            >
            Use HTTPS (secure connection)
          </label>
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

      <template v-if="type === 'pgvector'">
        <div class="space-y-2">
          <Label for="cred-pgvector-openai-key">OpenAI API Key</Label>
          <div class="relative">
            <Input
              id="cred-pgvector-openai-key"
              v-model="pgvectorOpenaiApiKey"
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
            OpenAI API key for text-embedding-3-large embeddings. Vectors are stored
            in Heym's own Postgres database — no external service required.
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

      <template v-if="type === 'supabase'">
        <div class="space-y-2">
          <Label for="cred-supabase-url">Project URL</Label>
          <Input
            id="cred-supabase-url"
            v-model="supabaseUrl"
            placeholder="https://your-project.supabase.co"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Supabase project URL. Heym uses the PostgREST API under `/rest/v1`.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-supabase-key">API Key</Label>
          <div class="relative">
            <Input
              id="cred-supabase-key"
              v-model="supabaseKey"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'service_role or secret key'"
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
            Use a key that can read and write the tables your workflows touch.
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-supabase-schema">Default Schema</Label>
          <Input
            id="cred-supabase-schema"
            v-model="supabaseSchema"
            placeholder="public"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Optional. Nodes can override this per workflow step.
          </p>
        </div>

        <div class="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            size="sm"
            :loading="supabaseTesting"
            :disabled="saving || supabaseTesting || !canTestSupabaseConnection"
            @click="testSupabaseConnection"
          >
            Test Connection
          </Button>
          <p
            v-if="supabaseTestMessage"
            class="text-xs"
            :class="supabaseTestSuccess ? 'text-emerald-600' : 'text-destructive'"
          >
            {{ supabaseTestMessage }}
          </p>
        </div>
      </template>

      <template v-if="type === 'notion'">
        <div class="space-y-2">
          <Label>Authentication</Label>
          <Select
            v-model="notionAuthMode"
            :options="[
              { value: 'token', label: 'Internal Integration Token' },
              { value: 'oauth', label: 'OAuth (Public Integration)' },
            ]"
            :disabled="saving || notionOAuthConnecting"
          />
        </div>

        <div class="space-y-2">
          <Label
            v-if="notionAuthMode === 'token'"
            for="cred-notion-token"
          >
            Internal Integration Token
          </Label>
          <div class="relative">
            <Input
              v-if="notionAuthMode === 'token'"
              id="cred-notion-token"
              v-model="notionToken"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'ntn_...'"
              :disabled="saving"
              class="pr-10"
            />
            <button
              v-if="notionAuthMode === 'token'"
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
          <p
            v-if="notionAuthMode === 'token'"
            class="text-xs text-muted-foreground"
          >
            Create an internal integration in Notion, then share the required pages and data sources with it.
          </p>
        </div>

        <template v-if="notionAuthMode === 'oauth'">
          <div class="space-y-2">
            <Label for="cred-notion-client-id">OAuth Client ID</Label>
            <Input
              id="cred-notion-client-id"
              v-model="notionClientId"
              placeholder="Public integration OAuth client ID"
              :disabled="saving || notionOAuthConnecting"
            />
          </div>
          <div class="space-y-2">
            <Label for="cred-notion-client-secret">OAuth Client Secret</Label>
            <Input
              id="cred-notion-client-secret"
              v-model="notionClientSecret"
              type="password"
              placeholder="Public integration OAuth client secret"
              :disabled="saving || notionOAuthConnecting"
            />
          </div>
          <div class="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              :loading="notionOAuthConnecting"
              :disabled="saving || notionOAuthConnecting || !notionClientId.trim() || !notionClientSecret.trim()"
              @click="startNotionOAuth"
            >
              {{ notionOAuthConnected ? "Reconnect" : "Connect" }}
            </Button>
            <span
              v-if="notionOAuthStatusLabel"
              class="text-xs"
              :class="
                notionOAuthConnected
                  ? 'text-emerald-600'
                  : 'text-muted-foreground'
              "
            >
              {{ notionOAuthStatusLabel }}
            </span>
          </div>
          <p class="text-xs text-muted-foreground">
            Register
            <code>/api/credentials/notion/oauth/callback</code>
            in your Notion public integration.
          </p>
        </template>

        <div
          v-if="notionAuthMode === 'token' || notionOAuthConnected"
          class="flex items-center gap-3"
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            :loading="notionTesting"
            :disabled="saving || notionTesting || (notionAuthMode === 'token' && !notionToken.trim() && !isEditing)"
            @click="testNotionConnection"
          >
            Test Connection
          </Button>
          <p
            v-if="notionTestMessage"
            class="text-xs"
            :class="notionTestSuccess ? 'text-emerald-600' : 'text-destructive'"
          >
            {{ notionTestMessage }}
          </p>
        </div>
      </template>

      <template v-if="type === 's3'">
        <div class="space-y-2">
          <Label for="cred-s3-access-key-id">Access Key ID <span class="text-destructive">*</span></Label>
          <Input
            id="cred-s3-access-key-id"
            v-model="s3AccessKeyId"
            :placeholder="isEditing ? '(re-enter to update)' : 'AKIA...'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            IAM access key ID for an AWS account with the required S3 permissions.
            <span v-if="isEditing"> Leave all S3 fields blank to keep the current config unchanged.</span>
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-s3-secret-access-key">Secret Access Key <span class="text-destructive">*</span></Label>
          <div class="relative">
            <Input
              id="cred-s3-secret-access-key"
              v-model="s3SecretAccessKey"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="isEditing ? '••••••• (re-enter to update)' : 'Enter secret key'"
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

        <div class="space-y-2">
          <Label for="cred-s3-region">Region <span class="text-destructive">*</span></Label>
          <Select
            id="cred-s3-region"
            v-model="s3Region"
            :options="AWS_REGION_OPTIONS"
            placeholder="Select AWS region..."
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            AWS region where the bucket lives (for example `us-east-1`).
            <span v-if="isEditing"> Re-enter access key, secret key, and region together to replace the stored config.</span>
          </p>
        </div>

        <div class="space-y-2">
          <Label for="cred-s3-session-token">Session Token</Label>
          <Input
            id="cred-s3-session-token"
            v-model="s3SessionToken"
            :placeholder="isEditing ? '(optional: re-enter to update)' : '(optional)'"
            :disabled="saving"
          />
          <p class="text-xs text-muted-foreground">
            Optional. Use when authenticating with temporary AWS STS credentials.
          </p>
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
