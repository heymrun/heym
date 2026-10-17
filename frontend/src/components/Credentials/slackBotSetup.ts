/** Bot scopes every Slack node operation needs, in the order Slack lists them. */
export const SLACK_BOT_SCOPES: readonly string[] = [
  "channels:history",
  "channels:read",
  "chat:write",
  "chat:write.public",
  "groups:history",
  "groups:read",
  "im:write",
  "reactions:write",
  "users:read",
  "users:read.email",
];

/** Where Slack posts clicks and modal submissions for one Slack Bot credential. */
export function slackInteractivityUrl(publicBaseUrl: string, credentialId: string): string {
  const base = publicBaseUrl.trim().replace(/\/+$/, "");
  if (!base || !credentialId) return "";
  return `${base}/api/slack/interactions/${credentialId}`;
}

/** A Slack app manifest with every scope, and interactivity when the URL is known. */
export function slackAppManifest(interactivityUrl: string): string {
  const settings: Record<string, unknown> = {
    org_deploy_enabled: false,
    socket_mode_enabled: false,
    token_rotation_enabled: false,
  };
  if (interactivityUrl) {
    settings.interactivity = { is_enabled: true, request_url: interactivityUrl };
  }
  return JSON.stringify(
    {
      display_information: { name: "Heym" },
      features: { bot_user: { display_name: "Heym", always_online: true } },
      oauth_config: { scopes: { bot: SLACK_BOT_SCOPES } },
      settings,
    },
    null,
    2,
  );
}
