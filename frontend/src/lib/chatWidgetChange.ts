import type { ChatWidgetChange } from "@/types/dashboard";

/** A `dashboard` chat stream event as a widget change, or null for anything else. */
export function parseChatWidgetChange(payload: Record<string, unknown>): ChatWidgetChange | null {
  const { type, action, dashboard_id: dashboardId, widget_id: widgetId } = payload;
  if (type !== "dashboard" || typeof action !== "string" || typeof dashboardId !== "string") {
    return null;
  }
  const version = payload.previous_version;
  return {
    action,
    dashboardId,
    widgetId: typeof widgetId === "string" ? widgetId : null,
    previousVersion: typeof version === "number" && Number.isInteger(version) ? version : null,
  };
}
