export type CredentialType =
  | "openai"
  | "google"
  | "custom"
  | "bearer"
  | "header"
  | "telegram"
  | "slack"
  | "slack_trigger"
  | "imap"
  | "smtp"
  | "redis"
  | "qdrant"
  | "grist"
  | "rabbitmq"
  | "cohere"
  | "flaresolverr"
  | "google_sheets"
  | "bigquery";

export interface Credential {
  id: string;
  name: string;
  type: CredentialType;
  masked_value: string | null;
  header_key: string | null;
  created_at: string;
  updated_at?: string;
}

export interface CredentialListItem {
  id: string;
  name: string;
  type: CredentialType;
  masked_value: string | null;
  header_key: string | null;
  created_at: string;
  is_shared?: boolean;
  shared_by?: string | null;
}

export interface CredentialForIntellisense {
  name: string;
  type: CredentialType;
}

export interface CredentialShare {
  id: string;
  user_id: string;
  email: string;
  name: string;
  shared_at: string;
}

export interface LLMModel {
  id: string;
  name: string;
  is_reasoning: boolean;
  supports_batch: boolean;
  batch_support_reason?: string | null;
}

export interface CredentialConfigOpenAI {
  api_key: string;
}

export interface CredentialConfigGoogle {
  api_key: string;
}

export interface CredentialConfigCustom {
  base_url: string;
  api_key: string;
}

export interface CredentialConfigBearer {
  bearer_token: string;
}

export interface CredentialConfigHeader {
  header_key: string;
  header_value: string;
}

export interface CredentialConfigSlack {
  webhook_url: string;
}

export interface CredentialConfigTelegram {
  bot_token: string;
  secret_token?: string;
}

export interface CredentialConfigSlackTrigger {
  signing_secret: string;
}

export interface CredentialConfigImap {
  imap_host: string;
  imap_port: string;
  imap_username: string;
  imap_password: string;
  imap_mailbox?: string;
  imap_use_ssl?: boolean;
}

export interface CredentialConfigSmtp {
  smtp_server: string;
  smtp_port: string;
  smtp_email: string;
  smtp_password: string;
}

export interface CredentialConfigRedis {
  redis_host: string;
  redis_port: string;
  redis_password: string;
  redis_db: string;
}

export interface CredentialConfigQdrant {
  qdrant_host: string;
  qdrant_port: string;
  qdrant_api_key: string;
  openai_api_key: string;
}

export interface CredentialConfigGrist {
  api_key: string;
  server_url: string;
}

export interface CredentialConfigRabbitmq {
  rabbitmq_host: string;
  rabbitmq_port: string;
  rabbitmq_username: string;
  rabbitmq_password: string;
  rabbitmq_vhost: string;
}

export interface CredentialConfigCohere {
  api_key: string;
}

export interface CredentialConfigFlaresolverr {
  flaresolverr_url: string;
}

export interface CredentialConfigGoogleSheets {
  client_id: string;
  client_secret: string;
  access_token?: string;
  refresh_token?: string;
  token_expiry?: string;
  scope?: string;
}

export type CredentialConfig =
  | CredentialConfigOpenAI
  | CredentialConfigGoogle
  | CredentialConfigCustom
  | CredentialConfigBearer
  | CredentialConfigHeader
  | CredentialConfigTelegram
  | CredentialConfigSlack
  | CredentialConfigSlackTrigger
  | CredentialConfigImap
  | CredentialConfigSmtp
  | CredentialConfigRedis
  | CredentialConfigQdrant
  | CredentialConfigGrist
  | CredentialConfigRabbitmq
  | CredentialConfigCohere
  | CredentialConfigFlaresolverr
  | CredentialConfigGoogleSheets;

export interface CreateCredentialRequest {
  name: string;
  type: CredentialType;
  config: CredentialConfig;
}

export interface UpdateCredentialRequest {
  name?: string;
  config?: CredentialConfig;
}

export const CREDENTIAL_TYPE_LABELS: Record<CredentialType, string> = {
  openai: "OpenAI",
  google: "Google AI",
  custom: "Custom (OpenAI Compatible)",
  bearer: "Authorization Bearer Token",
  header: "Header Authorization",
  telegram: "Telegram Bot",
  slack: "Slack Webhook",
  slack_trigger: "Slack Trigger (Signing Secret)",
  imap: "IMAP Email Inbox",
  smtp: "SMTP Email",
  redis: "Redis",
  qdrant: "QDrant + OpenAI",
  grist: "Grist",
  rabbitmq: "RabbitMQ",
  cohere: "Cohere Reranker",
  flaresolverr: "FlareSolverr",
  google_sheets: "Google Sheets (OAuth2)",
  bigquery: "BigQuery (OAuth2)",
};

export const CREDENTIAL_TYPE_DESCRIPTIONS: Record<CredentialType, string> = {
  openai: "Connect to OpenAI API for GPT models",
  google: "Connect to Google AI for Gemini models",
  custom: "Connect to any OpenAI-compatible API endpoint",
  bearer: "Store a Bearer token for Authorization header",
  header: "Store custom HTTP headers (key:value)",
  telegram: "Connect a Telegram bot for inbound webhook triggers and outbound bot messages",
  slack: "Send messages via Slack incoming webhooks",
  slack_trigger: "Verify incoming Slack event webhooks using a signing secret",
  imap: "Poll an IMAP inbox for new emails and trigger workflows when mail arrives",
  smtp: "Send emails via SMTP server",
  redis: "Connect to Redis for caching and data storage",
  qdrant: "Connect to QDrant for vector storage with OpenAI embeddings",
  grist: "Connect to Grist spreadsheet for data operations",
  rabbitmq: "Connect to RabbitMQ for message queue operations",
  cohere: "Connect to Cohere API for reranking search results",
  flaresolverr: "Connect to FlareSolverr for web scraping with browser automation",
  google_sheets: "Connect to Google Sheets via OAuth2 — read, write, append, and query spreadsheets",
  bigquery: "Connect to Google BigQuery via OAuth2 — run SQL queries and insert rows",
};
