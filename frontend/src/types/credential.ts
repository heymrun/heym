export type CredentialType =
  | "openai"
  | "google"
  | "github"
  | "linear"
  | "custom"
  | "bearer"
  | "header"
  | "discord"
  | "discord_trigger"
  | "telegram"
  | "slack"
  | "slack_trigger"
  | "imap"
  | "smtp"
  | "redis"
  | "qdrant"
  | "pgvector"
  | "grist"
  | "rabbitmq"
  | "cohere"
  | "flaresolverr"
  | "google_sheets"
  | "bigquery"
  | "supabase"
  | "notion"
  | "sentry"
  | "s3"
  | "elevenlabs"
  | "clickhouse";

export interface Credential {
  id: string;
  name: string;
  type: CredentialType;
  masked_value: string | null;
  header_key: string | null;
  public_fields?: Record<string, string | null>;
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
  context_window?: number | null;
}

export interface CredentialConfigOpenAI {
  api_key: string;
}

export interface CredentialConfigGoogle {
  api_key: string;
}

export interface CredentialConfigGitHub {
  api_key: string;
  base_url?: string;
}

export interface CredentialConfigLinear {
  api_key?: string;
  auth_mode?: "api_key" | "oauth";
  client_id?: string;
  client_secret?: string;
  access_token?: string;
  refresh_token?: string;
  token_expiry?: string;
}

export interface CredentialConfigElevenLabs {
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

export interface CredentialConfigDiscord {
  webhook_url: string;
}

export interface CredentialConfigDiscordTrigger {
  public_key: string;
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

export interface CredentialConfigPgvector {
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

export interface CredentialConfigS3 {
  aws_access_key_id: string;
  aws_secret_access_key: string;
  aws_region: string;
  aws_session_token?: string;
}

export interface CredentialConfigSupabase {
  supabase_url: string;
  supabase_key: string;
  supabase_schema?: string;
}

export interface CredentialConfigClickHouse {
  host: string;
  port?: number;
  username?: string;
  password?: string;
  database?: string;
  secure?: boolean;
}

export interface CredentialConfigNotion {
  api_token?: string;
  client_id?: string;
  client_secret?: string;
  access_token?: string;
  auth_mode?: "token" | "oauth";
}

export interface CredentialConfigSentry {
  api_token: string;
  base_url?: string;
}

export type CredentialConfig =
  | CredentialConfigOpenAI
  | CredentialConfigGoogle
  | CredentialConfigGitHub
  | CredentialConfigLinear
  | CredentialConfigCustom
  | CredentialConfigBearer
  | CredentialConfigHeader
  | CredentialConfigTelegram
  | CredentialConfigSlack
  | CredentialConfigDiscord
  | CredentialConfigDiscordTrigger
  | CredentialConfigSlackTrigger
  | CredentialConfigImap
  | CredentialConfigSmtp
  | CredentialConfigRedis
  | CredentialConfigQdrant
  | CredentialConfigPgvector
  | CredentialConfigGrist
  | CredentialConfigRabbitmq
  | CredentialConfigCohere
  | CredentialConfigFlaresolverr
  | CredentialConfigGoogleSheets
  | CredentialConfigSupabase
  | CredentialConfigClickHouse
  | CredentialConfigNotion
  | CredentialConfigSentry
  | CredentialConfigS3
  | CredentialConfigElevenLabs;

export interface CreateCredentialRequest {
  name: string;
  type: CredentialType;
  config: CredentialConfig;
}

export interface UpdateCredentialRequest {
  name?: string;
  config?: CredentialConfig;
}

export interface CredentialTestRequest {
  type: CredentialType;
  config?: CredentialConfig;
  credential_id?: string;
}

export interface CredentialTestResponse {
  success: boolean;
  message: string;
}

export interface SupabaseTablesResponse {
  tables: string[];
  success: boolean;
}

export interface SupabaseColumnsResponse {
  columns: string[];
  success: boolean;
}

export interface ClickHouseColumn {
  name: string;
  type: string;
}

export interface ClickHouseColumnsResponse {
  columns: ClickHouseColumn[];
  success: boolean;
}

export interface NotionDataSourceItem {
  id: string;
  title: string;
  url?: string | null;
}

export interface NotionDataSourcesResponse {
  data_sources: NotionDataSourceItem[];
  next_cursor?: string | null;
  has_more: boolean;
  success: boolean;
}

export interface NotionPageItem {
  id: string;
  title: string;
  url?: string | null;
}

export interface NotionPagesResponse {
  pages: NotionPageItem[];
  next_cursor?: string | null;
  has_more: boolean;
  success: boolean;
}

export const CREDENTIAL_TYPE_LABELS: Record<CredentialType, string> = {
  openai: "OpenAI",
  google: "Google AI",
  github: "GitHub",
  linear: "Linear",
  custom: "Custom (OpenAI Compatible)",
  bearer: "Authorization Bearer Token",
  header: "Header Authorization",
  telegram: "Telegram Bot",
  discord: "Discord Webhook",
  discord_trigger: "Discord Trigger (Public Key)",
  slack: "Slack Webhook",
  slack_trigger: "Slack Trigger (Signing Secret)",
  imap: "IMAP Email Inbox",
  smtp: "SMTP Email",
  redis: "Redis",
  qdrant: "RAG: Qdrant + OpenAI",
  pgvector: "RAG: Psql + OpenAI",
  grist: "Grist",
  rabbitmq: "RabbitMQ",
  cohere: "Cohere Reranker",
  flaresolverr: "FlareSolverr",
  google_sheets: "Google Sheets (OAuth2)",
  bigquery: "BigQuery (OAuth2)",
  supabase: "Supabase",
  clickhouse: "ClickHouse",
  notion: "Notion (Token or OAuth)",
  sentry: "Sentry",
  s3: "Amazon S3",
  elevenlabs: "ElevenLabs (Voice)",
};

export const CREDENTIAL_TYPE_DESCRIPTIONS: Record<CredentialType, string> = {
  openai: "Connect to OpenAI API for GPT models",
  google: "Connect to Google AI for Gemini models",
  github: "Store a GitHub personal access token for GitHub API, MCP, and agent workflows",
  linear: "Connect to Linear for workspace, project, issue, and comment automation",
  custom: "Connect to any OpenAI-compatible API endpoint",
  bearer: "Store a Bearer token for Authorization header",
  header: "Store custom HTTP headers (key:value)",
  telegram: "Connect a Telegram bot for inbound webhook triggers and outbound bot messages",
  discord: "Send messages via Discord incoming webhooks",
  discord_trigger: "Verify incoming Discord interaction webhooks using an application public key",
  slack: "Send messages via Slack incoming webhooks",
  slack_trigger: "Verify incoming Slack event webhooks using a signing secret",
  imap: "Poll an IMAP inbox for new emails and trigger workflows when mail arrives",
  smtp: "Send emails via SMTP server",
  redis: "Connect to Redis for caching and data storage",
  qdrant: "Connect to QDrant for vector storage with OpenAI embeddings",
  pgvector:
    "Vector storage inside Heym's own Postgres database with OpenAI embeddings (no external DB)",
  grist: "Connect to Grist spreadsheet for data operations",
  rabbitmq: "Connect to RabbitMQ for message queue operations",
  cohere: "Connect to Cohere API for reranking search results",
  flaresolverr: "Connect to FlareSolverr for web scraping with browser automation",
  google_sheets: "Connect to Google Sheets via OAuth2 — read, write, append, and query spreadsheets",
  bigquery: "Connect to Google BigQuery via OAuth2 — run SQL queries and insert rows",
  supabase: "Connect to Supabase PostgREST — query and mutate Postgres-backed tables",
  clickhouse:
    "Connect to ClickHouse — run SQL and CRUD over OLAP tables via the HTTP interface",
  notion: "Connect to Notion with an internal token or user-authorized OAuth workspace",
  sentry: "Connect to Sentry for organizations, projects, issues, events, and releases",
  s3: "Connect to Amazon S3 — manage buckets, folders, and objects",
  elevenlabs: "Text-to-speech and speech-to-text for chat voice features",
};
