/** Bot scopes every Slack node operation and Slack Trigger scope needs, in the order Slack lists them. */
export const SLACK_BOT_SCOPES: readonly string[] = [
  "app_mentions:read",
  "channels:history",
  "channels:read",
  "chat:write",
  "chat:write.public",
  "groups:history",
  "groups:read",
  "im:history",
  "im:write",
  "reactions:write",
  "users:read",
  "users:read.email",
];

/** Events the Slack Trigger listens to: messages in channels, private channels and DMs, and mentions. */
export const SLACK_BOT_EVENTS: readonly string[] = ["app_mention", "message.channels", "message.groups", "message.im"];

function credentialUrl(publicBaseUrl: string, credentialId: string, part: string): string {
  const base = publicBaseUrl.trim().replace(/\/+$/, "");
  if (!base || !credentialId) return "";
  return `${base}/api/slack/${part}/${credentialId}`;
}

/** Where Slack posts clicks and modal submissions for one Slack Bot credential. */
export function slackInteractivityUrl(publicBaseUrl: string, credentialId: string): string {
  return credentialUrl(publicBaseUrl, credentialId, "interactions");
}

/** Where Slack posts the app's events; every Slack Trigger on the credential hears them. */
export function slackEventsUrl(publicBaseUrl: string, credentialId: string): string {
  return credentialUrl(publicBaseUrl, credentialId, "events");
}

/**
 * A Slack app manifest with every scope, a Messages tab people can write to, and the
 * interactivity and events URLs once the credential is saved.
 */
export function slackAppManifest(interactivityUrl: string, eventsUrl = ""): string {
  const settings: Record<string, unknown> = {
    org_deploy_enabled: false,
    socket_mode_enabled: false,
    token_rotation_enabled: false,
  };
  if (interactivityUrl) {
    settings.interactivity = { is_enabled: true, request_url: interactivityUrl };
  }
  if (eventsUrl) {
    settings.event_subscriptions = { request_url: eventsUrl, bot_events: SLACK_BOT_EVENTS };
  }
  return JSON.stringify(
    {
      display_information: { name: "Heym" },
      features: {
        app_home: { home_tab_enabled: false, messages_tab_enabled: true, messages_tab_read_only_enabled: false },
        bot_user: { display_name: "Heym", always_online: true },
      },
      oauth_config: { scopes: { bot: SLACK_BOT_SCOPES } },
      settings,
    },
    null,
    2,
  );
}
